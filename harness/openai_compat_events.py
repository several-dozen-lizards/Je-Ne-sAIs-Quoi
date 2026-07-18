"""Async OpenAI-compatible Chat Completions -> neutral JNSQ events."""
from __future__ import annotations

import asyncio
import copy
import json
import math
from collections.abc import AsyncIterator, Sequence

import httpx

from adapters.model_events import (
    CancellationToken, ModelEvent, ModelExchange, ToolCall, ToolSpec,
)
from harness.clients import (
    build_openai_compat_body, openai_compat_headers,
    openai_compat_wire_correction,
)


_FAIL_FINISH_REASONS = {
    "error", "sensitive", "network_error",
    "model_context_window_exceeded",
}


class OpenAICompatEventParser:
    """Pure incremental normalizer for complete SSE ``data`` payloads."""

    def __init__(self, tools: Sequence[ToolSpec] = ()):
        self.seq = 0
        self.terminal = False
        self.finish_reason = None
        self.completion_seq = None
        self.calls_finalized = False
        self.usage = {}
        self.tool_calls = {}
        self.first_seen = []
        self.call_ids = set()
        self.saw_choice_zero = False
        self.saw_nonzero_choice = False
        self.deviations = []
        self.advertised_tools = {tool.name for tool in tools}

    def _next(self) -> int:
        self.seq += 1
        return self.seq

    def _terminal(self, event: ModelEvent) -> tuple:
        if self.terminal:
            return ()
        self.terminal = True
        return (event,)

    def _fail(self, message: str) -> tuple:
        return self._terminal(ModelEvent.failed(self._next(), message))

    def _merge_identity(self, call: dict, field: str, value) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            return f"tool {field} was not a string"
        existing = call.get(field)
        if not existing:
            call[field] = value
        elif existing != value:
            if field == "name":
                call[field] += value
                self.deviations.append("split_tool_name")
            else:
                return f"tool {field} changed across stream fragments"
        return None

    def _tool_delta(self, item) -> str | None:
        if not isinstance(item, dict):
            return "tool call delta was not an object"
        index = item.get("index")
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            return "tool call index must be a non-negative integer"
        if index not in self.tool_calls:
            self.tool_calls[index] = {
                "id": None,
                "type": None,
                "name": None,
                "argument_mode": None,
                "argument_fragments": [],
                "argument_object": None,
            }
            self.first_seen.append(index)
        call = self.tool_calls[index]
        problem = self._merge_identity(call, "id", item.get("id"))
        if problem:
            return problem
        problem = self._merge_identity(call, "type", item.get("type"))
        if problem:
            return problem
        function = item.get("function")
        if function is None:
            return None
        if not isinstance(function, dict):
            return "tool function delta was not an object"
        problem = self._merge_identity(call, "name", function.get("name"))
        if problem:
            return problem
        arguments = function.get("arguments")
        if arguments is None:
            return None
        if isinstance(arguments, str):
            if call["argument_mode"] not in {None, "string"}:
                return "tool arguments switched from object to string"
            call["argument_mode"] = "string"
            call["argument_fragments"].append(arguments)
        elif isinstance(arguments, dict):
            if call["argument_mode"] not in {None, "object"}:
                return "tool arguments switched from string to object"
            if call["argument_object"] is not None:
                return "tool arguments object repeated across fragments"
            call["argument_mode"] = "object"
            call["argument_object"] = copy.deepcopy(arguments)
        else:
            return "tool arguments must be a JSON string or object"
        return None

    def _finalize_calls(self) -> tuple:
        calls = []
        observed_ids = set()
        for index in sorted(self.first_seen):
            item = self.tool_calls[index]
            if not item["id"] or not item["name"]:
                return self._fail(
                    f"tool call index {index} lacked provider id or name")
            if item["type"] not in {None, "function"}:
                return self._fail(
                    f"tool call index {index} had unsupported type "
                    f"{item['type']!r}")
            if item["argument_mode"] == "object":
                arguments = copy.deepcopy(item["argument_object"])
            else:
                encoded = "".join(item["argument_fragments"]) or "{}"
                try:
                    arguments = json.loads(encoded)
                except json.JSONDecodeError:
                    return self._fail(
                        f"tool call {item['id']!r} arguments were invalid JSON")
            if not isinstance(arguments, dict):
                return self._fail(
                    f"tool call {item['id']!r} arguments were not an object")
            try:
                call = ToolCall(item["id"], item["name"], arguments)
            except Exception as error:
                return self._fail(f"OpenAI-compatible tool call invalid: {error}")
            if call.name not in self.advertised_tools:
                return self._fail(
                    f"OpenAI-compatible provider requested unadvertised "
                    f"tool {call.name!r}")
            if call.call_id in observed_ids:
                return self._fail(
                    f"duplicate tool call id {call.call_id!r}")
            observed_ids.add(call.call_id)
            calls.append(call)
        self.call_ids.update(observed_ids)
        return tuple(
            ModelEvent.tool_call(self._next(), call) for call in calls)

    def feed(self, payload: str) -> tuple:
        if self.terminal:
            return ()
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return self._fail("OpenAI-compatible stream emitted invalid JSON")
        if not isinstance(data, dict):
            return self._fail(
                "OpenAI-compatible stream payload was not an object")
        if data.get("error") is not None:
            error = data.get("error")
            if isinstance(error, dict):
                kind = error.get("code") or error.get("type") or "provider_error"
                message = error.get("message") or "unknown provider error"
            else:
                kind, message = "provider_error", error
            return self._fail(
                f"OpenAI-compatible {kind}: {str(message)[:240]}")
        usage = data.get("usage")
        if isinstance(usage, dict):
            self.usage.update(copy.deepcopy(usage))
        choices = data.get("choices") or []
        if not isinstance(choices, list):
            return self._fail("OpenAI-compatible choices was not a list")
        choice = None
        for candidate in choices:
            if not isinstance(candidate, dict):
                continue
            if candidate.get("index") == 0:
                choice = candidate
                self.saw_choice_zero = True
                break
            self.saw_nonzero_choice = True
        if choice is None:
            if self.finish_reason is not None and self.completion_seq is not None:
                return (ModelEvent.completed(
                    self.completion_seq, self.finish_reason, self.usage),)
            return ()
        delta = choice.get("delta") or {}
        if not isinstance(delta, dict):
            return self._fail(
                "OpenAI-compatible choice delta was not an object")
        events = []
        content = delta.get("content")
        if content is not None:
            if not isinstance(content, str):
                return self._fail(
                    "OpenAI-compatible visible content was not text")
            if content:
                events.append(ModelEvent.text_delta(self._next(), content))
        tool_deltas = delta.get("tool_calls") or []
        if not isinstance(tool_deltas, list):
            return self._fail(
                "OpenAI-compatible tool_calls delta was not a list")
        for item in tool_deltas:
            problem = self._tool_delta(item)
            if problem:
                return self._fail(problem)
        finish = choice.get("finish_reason")
        if finish is None and delta.get("finish_reason") is not None:
            finish = delta.get("finish_reason")
            self.deviations.append("finish_reason_in_delta")
        if finish is None:
            return tuple(events)
        self.finish_reason = str(finish)
        if self.finish_reason in _FAIL_FINISH_REASONS:
            return self._fail(
                f"OpenAI-compatible generation ended with "
                f"{self.finish_reason}")
        if self.finish_reason == "tool_calls" and not self.tool_calls:
            return self._fail(
                "finish_reason tool_calls arrived without tool calls")
        call_events = ()
        if not self.calls_finalized:
            call_events = self._finalize_calls()
            self.calls_finalized = True
        if self.terminal:
            return tuple(events) + call_events
        if self.tool_calls and self.finish_reason != "tool_calls":
            self.deviations.append(
                f"tool_calls_with_finish_{self.finish_reason}")
        events.extend(call_events)
        if self.completion_seq is None:
            self.completion_seq = self._next()
        events.append(ModelEvent.completed(
            self.completion_seq, self.finish_reason, self.usage))
        return tuple(events)

    def done(self) -> tuple:
        if self.terminal:
            return ()
        if self.finish_reason is not None:
            self.terminal = True
            return ()
        return self._fail(
            "OpenAI-compatible stream sent [DONE] before a finish reason")

    def eof(self) -> tuple:
        if self.terminal:
            return ()
        if self.finish_reason is not None:
            self.terminal = True
            return ()
        if not self.saw_choice_zero and self.saw_nonzero_choice:
            return self._fail(
                "OpenAI-compatible stream contained only nonzero choices")
        return self._fail(
            "OpenAI-compatible stream ended without a finish reason")


class OpenAICompatAsyncTransport:
    """Async request, retry, response-closure, and cancellation owner."""

    def __init__(
            self, model: str, key: str, url: str, *,
            token_limit_param: str = "max_tokens", stops=(),
            temperature_policy: dict = None, reasoning_effort: str = None,
            wire: dict = None, timeout_s: float = 360.0,
            timeouts: dict = None,
            client: httpx.AsyncClient = None):
        self.model = model
        self.key = key
        self.url = url
        self.token_limit_param = token_limit_param
        self.stops = tuple(stops or ())
        self.temperature_policy = dict(temperature_policy or {})
        self.reasoning_effort = reasoning_effort
        self.wire = dict(wire or {})
        self.timeout_s = timeout_s
        configured = dict(timeouts or {})
        self.timeouts = {
            name: float(configured.get(name, timeout_s))
            for name in ("connect", "read", "write", "pool")
        }
        if any(not math.isfinite(value) or value <= 0
               for value in self.timeouts.values()):
            raise ValueError(
                "OpenAI-compatible HTTP timeouts must be positive and finite")
        self._client = client
        self._owns_client = client is None
        self.last_terminal_receipt = None
        self.last_attempt_receipts = ()
        self.last_parser_deviations = ()

    def _safe(self, value) -> str:
        text = str(value or "")
        if self.key:
            text = text.replace(self.key, "[credential]")
        return text

    def _terminal(self, event: ModelEvent = None, *,
                  kind: str = None, error: str = ""):
        if self.last_terminal_receipt is not None:
            return
        receipt = (event.to_receipt() if event is not None
                   else {"kind": kind, "error": error})
        receipt["transport"] = "openai_compat_httpx_async"
        self.last_terminal_receipt = receipt

    def _sanitize(self, event: ModelEvent) -> ModelEvent:
        if event.kind == "failed":
            safe = self._safe(event.error)
            if safe != event.error:
                return ModelEvent.failed(event.seq, safe)
        return event

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=self.timeouts["connect"],
                    read=self.timeouts["read"],
                    write=self.timeouts["write"],
                    pool=self.timeouts["pool"]))
        return self._client

    async def aclose(self):
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def _adaptive_body(body: dict, max_tokens: int, usage: dict) -> dict:
        retry = dict(body)
        limit_key = ("max_completion_tokens"
                     if "max_completion_tokens" in retry else "max_tokens")
        limit = int(retry.get(limit_key) or max_tokens)
        observed = int((usage or {}).get("completion_tokens") or 0)
        increment = min(limit, observed if observed > 0 else limit)
        retry[limit_key] = limit + increment
        effort = retry.get("reasoning_effort")
        if effort:
            ladder = ["high", "medium", "low", "minimal", "none"]
            if effort in ladder:
                retry["reasoning_effort"] = ladder[
                    min(ladder.index(effort) + 1, len(ladder) - 1)]
        return retry

    async def events(
            self, system: str, user: str, *,
            max_tokens: int = 400, temperature: float = 0.7,
            images: list = None, tools: Sequence[ToolSpec] = (),
            exchanges: Sequence[ModelExchange] = (),
            cancel: CancellationToken = None) -> AsyncIterator[ModelEvent]:
        self.last_terminal_receipt = None
        self.last_attempt_receipts = ()
        self.last_parser_deviations = ()
        if cancel is not None and cancel.cancelled:
            event = ModelEvent.cancelled(1, cancel.reason)
            self._terminal(event)
            yield event
            return
        body = build_openai_compat_body(
            self.model, system, user,
            token_limit_param=self.token_limit_param,
            max_tokens=max_tokens, temperature=temperature,
            temperature_policy=self.temperature_policy,
            reasoning_effort=self.reasoning_effort, stops=self.stops,
            images=images, tools=tools, exchanges=exchanges, stream=True,
            wire=self.wire)
        headers = openai_compat_headers(self.key)
        task = asyncio.current_task()
        loop = asyncio.get_running_loop()
        unsubscribe = None
        if cancel is not None:
            unsubscribe = cancel.subscribe(
                lambda reason: loop.call_soon_threadsafe(task.cancel, reason))
        attempt_receipts = []
        try:
            client = await self._http()
            generation_body = body
            for generation in range(2):
                effective_body = generation_body
                parser = None
                for wire_attempt in range(2):
                    if cancel is not None and cancel.cancelled:
                        raise asyncio.CancelledError(cancel.reason)
                    parser = OpenAICompatEventParser(tools)
                    async with client.stream(
                            "POST", self.url, headers=headers,
                            json=effective_body) as response:
                        if response.status_code != 200:
                            raw = (await response.aread()).decode(
                                "utf-8", errors="replace")
                            error = {}
                            try:
                                parsed = json.loads(raw)
                                error = (parsed.get("error") or {}
                                         if isinstance(parsed, dict) else {})
                            except Exception:
                                pass
                            correction = (
                                openai_compat_wire_correction(
                                    effective_body, error)
                                if response.status_code == 400
                                and wire_attempt == 0 else None)
                            if correction is not None:
                                effective_body, changed = correction
                                attempt_receipts.append({
                                    "generation": generation + 1,
                                    "wire_attempt": wire_attempt + 1,
                                    "kind": "wire_correction",
                                    "parameter": changed,
                                })
                                continue
                            event = ModelEvent.failed(
                                1,
                                f"OpenAI-compatible API "
                                f"{response.status_code}: "
                                f"{self._safe(raw)[:300]}")
                            self._terminal(event)
                            yield event
                            return

                        data_lines = []
                        visible = False
                        called = False
                        completed = None
                        async for line in response.aiter_lines():
                            if line == "":
                                if not data_lines:
                                    continue
                                payload = "\n".join(data_lines)
                                data_lines.clear()
                                if payload == "[DONE]":
                                    parsed_events = parser.done()
                                else:
                                    parsed_events = parser.feed(payload)
                                for event in parsed_events:
                                    event = self._sanitize(event)
                                    if event.kind == "text_delta":
                                        visible = True
                                        yield event
                                    elif event.kind == "tool_call":
                                        called = True
                                        yield event
                                    elif event.kind == "completed":
                                        completed = event
                                    else:
                                        self._terminal(event)
                                        yield event
                                        return
                                if parser.terminal:
                                    break
                                continue
                            if line.startswith(":"):
                                continue
                            if line.startswith("data:"):
                                data_lines.append(line[5:].lstrip())
                        if data_lines and not parser.terminal:
                            payload = "\n".join(data_lines)
                            parsed_events = (
                                parser.done() if payload == "[DONE]"
                                else parser.feed(payload))
                            for event in parsed_events:
                                event = self._sanitize(event)
                                if event.kind == "text_delta":
                                    visible = True
                                    yield event
                                elif event.kind == "tool_call":
                                    called = True
                                    yield event
                                elif event.kind == "completed":
                                    completed = event
                                else:
                                    self._terminal(event)
                                    yield event
                                    return
                        if not parser.terminal:
                            eof_events = parser.eof()
                            for event in eof_events:
                                event = self._sanitize(event)
                                self._terminal(event)
                                yield event
                            if eof_events:
                                return
                    self.last_parser_deviations = tuple(parser.deviations)
                    if visible or called:
                        if completed is None:
                            event = ModelEvent.failed(
                                parser.seq + 1,
                                "OpenAI-compatible stream lacked completion")
                            self._terminal(event)
                            yield event
                            return
                        self._terminal(completed)
                        yield completed
                        self.last_attempt_receipts = tuple(attempt_receipts)
                        return
                    if completed is None:
                        return
                    if generation == 0:
                        attempt_receipts.append({
                            "generation": 1,
                            "kind": "empty_generation_retry",
                            "finish_reason": completed.finish_reason,
                        })
                        generation_body = self._adaptive_body(
                            effective_body, max_tokens, completed.usage)
                        await asyncio.sleep(0)
                        break
                    event = ModelEvent.failed(
                        completed.seq,
                        "OpenAI-compatible API returned no visible text or "
                        "tool call after adaptive retry")
                    self._terminal(event)
                    yield event
                    self.last_attempt_receipts = tuple(attempt_receipts)
                    return
            self.last_attempt_receipts = tuple(attempt_receipts)
        except asyncio.CancelledError:
            reason = (
                cancel.reason if cancel is not None and cancel.cancelled
                else "async model task cancelled")
            self._terminal(kind="cancelled", error=reason)
            self.last_attempt_receipts = tuple(attempt_receipts)
            raise
        except Exception as error:
            event = ModelEvent.failed(
                1, f"OpenAI-compatible transport failed: "
                   f"{error.__class__.__name__}: "
                   f"{self._safe(error)[:220]}")
            self._terminal(event)
            self.last_attempt_receipts = tuple(attempt_receipts)
            yield event
        finally:
            if unsubscribe is not None:
                unsubscribe()

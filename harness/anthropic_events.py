"""Async Anthropic SSE -> neutral JNSQ model events.

The transport owns I/O and cancellation.  ``AnthropicEventParser`` is a pure,
incremental state machine: fixtures can feed it provider payloads without a
network or API key.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Sequence

import httpx

from adapters.model_events import (
    CancellationToken, ModelEvent, ModelExchange, ToolCall, ToolSpec,
)
from harness.clients import (
    ANTHROPIC_URL, anthropic_headers, build_anthropic_body,
)


class AnthropicEventParser:
    """Normalize complete Anthropic SSE data payloads in provider order."""

    def __init__(self, tools: Sequence[ToolSpec] = ()):
        self.seq = 0
        self.tool_blocks = {}
        self.finish_reason = None
        self.usage = {}
        self.terminal = False
        self.unknown_event_types = []
        self.advertised_tools = {tool.name for tool in tools}

    def _next(self) -> int:
        self.seq += 1
        return self.seq

    def _terminal(self, event: ModelEvent) -> tuple:
        if self.terminal:
            return ()
        self.terminal = True
        return (event,)

    def feed(self, payload: str) -> tuple:
        """Consume one JSON ``data:`` payload and return neutral events."""
        if self.terminal:
            return ()
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return self._terminal(ModelEvent.failed(
                self._next(), "Anthropic stream emitted invalid JSON"))
        event_type = data.get("type")

        if event_type == "message_start":
            usage = (data.get("message") or {}).get("usage") or {}
            self.usage.update(usage)
            return ()

        if event_type == "content_block_start":
            index = data.get("index")
            block = data.get("content_block") or {}
            block_type = block.get("type")
            if block_type == "tool_use":
                self.tool_blocks[index] = {
                    "id": block.get("id"),
                    "name": block.get("name"),
                    "input_json": "",
                }
                return ()
            if block_type == "text":
                text = block.get("text") or ""
                if text:
                    return (ModelEvent.text_delta(self._next(), text),)
                return ()
            self.unknown_event_types.append(
                f"content_block_start:{block_type}")
            return ()

        if event_type == "content_block_delta":
            index = data.get("index")
            delta = data.get("delta") or {}
            delta_type = delta.get("type")
            if delta_type == "text_delta":
                text = delta.get("text") or ""
                if text:
                    return (ModelEvent.text_delta(self._next(), text),)
                return ()
            if delta_type == "input_json_delta":
                block = self.tool_blocks.get(index)
                if block is None:
                    return self._terminal(ModelEvent.failed(
                        self._next(),
                        "Anthropic tool input delta had no tool block"))
                block["input_json"] += delta.get("partial_json") or ""
                return ()
            self.unknown_event_types.append(
                f"content_block_delta:{delta_type}")
            return ()

        if event_type == "content_block_stop":
            index = data.get("index")
            block = self.tool_blocks.pop(index, None)
            if block is None:
                return ()
            try:
                arguments = json.loads(block["input_json"] or "{}")
            except json.JSONDecodeError:
                return self._terminal(ModelEvent.failed(
                    self._next(),
                    "Anthropic tool input did not form valid JSON"))
            if not isinstance(arguments, dict):
                return self._terminal(ModelEvent.failed(
                    self._next(),
                    "Anthropic tool input was not a JSON object"))
            try:
                call = ToolCall(block["id"], block["name"], arguments)
            except Exception as error:
                return self._terminal(ModelEvent.failed(
                    self._next(),
                    f"Anthropic tool call was invalid: {error}"))
            if call.name not in self.advertised_tools:
                return self._terminal(ModelEvent.failed(
                    self._next(),
                    f"Anthropic requested unadvertised tool {call.name!r}"))
            return (ModelEvent.tool_call(self._next(), call),)

        if event_type == "message_delta":
            delta = data.get("delta") or {}
            self.finish_reason = (
                delta.get("stop_reason") or self.finish_reason)
            self.usage.update(data.get("usage") or {})
            return ()

        if event_type == "message_stop":
            return self._terminal(ModelEvent.completed(
                self._next(), self.finish_reason, self.usage))

        if event_type == "error":
            error = data.get("error") or {}
            kind = error.get("type") or "provider_error"
            message = str(error.get("message") or "unknown provider error")
            return self._terminal(ModelEvent.failed(
                self._next(), f"Anthropic {kind}: {message[:240]}"))

        if event_type == "ping":
            return ()

        self.unknown_event_types.append(str(event_type or "missing"))
        return ()

    def eof(self) -> tuple:
        if self.terminal:
            return ()
        return self._terminal(ModelEvent.failed(
            self._next(),
            "Anthropic stream ended without message_stop"))


class AnthropicAsyncTransport:
    """Long-lived async HTTP owner for one adapter/run boundary."""

    def __init__(self, model: str, key: str, *, url: str = ANTHROPIC_URL,
                 timeout_s: float = 120.0,
                 client: httpx.AsyncClient = None):
        self.model = model
        self.key = key
        self.url = url
        self.timeout_s = timeout_s
        self._client = client
        self._owns_client = client is None
        self.last_terminal_receipt = None
        self.last_unknown_event_types = ()

    def _terminal(self, event: ModelEvent = None, *,
                  kind: str = None, error: str = ""):
        if self.last_terminal_receipt is not None:
            return
        if event is not None:
            receipt = event.to_receipt()
        else:
            receipt = {"kind": kind, "error": error}
        receipt["transport"] = "anthropic_httpx_async"
        self.last_terminal_receipt = receipt

    def _safe(self, value) -> str:
        text = str(value or "")
        if self.key:
            text = text.replace(self.key, "[credential]")
        return text

    def _sanitize(self, event: ModelEvent) -> ModelEvent:
        if event.kind == "failed":
            safe = self._safe(event.error)
            if safe != event.error:
                return ModelEvent.failed(event.seq, safe)
        return event

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_s))
        return self._client

    async def aclose(self):
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def events(
            self, system: str | list, user: str, *,
            max_tokens: int = 400, temperature: float = 0.7,
            images: list = None, tools: Sequence[ToolSpec] = (),
            exchanges: Sequence[ModelExchange] = (),
            cancel: CancellationToken = None) -> AsyncIterator[ModelEvent]:
        self.last_terminal_receipt = None
        self.last_unknown_event_types = ()
        if cancel is not None and cancel.cancelled:
            event = ModelEvent.cancelled(1, cancel.reason)
            self._terminal(event)
            yield event
            return

        body = build_anthropic_body(
            self.model, system, user, max_tokens=max_tokens,
            temperature=temperature, images=images, tools=tools,
            exchanges=exchanges, stream=True)
        parser = AnthropicEventParser(tools)
        task = asyncio.current_task()
        loop = asyncio.get_running_loop()
        unsubscribe = None
        if cancel is not None:
            unsubscribe = cancel.subscribe(
                lambda reason: loop.call_soon_threadsafe(
                    task.cancel, reason))

        data_lines = []
        try:
            client = await self._http()
            async with client.stream(
                    "POST", self.url, headers=anthropic_headers(self.key),
                    json=body) as response:
                if response.status_code != 200:
                    raw = (await response.aread()).decode(
                        "utf-8", errors="replace")
                    event = ModelEvent.failed(
                        1, f"Anthropic API {response.status_code}: "
                           f"{self._safe(raw)[:300]}")
                    self._terminal(event)
                    yield event
                    return

                async for line in response.aiter_lines():
                    if line == "":
                        if not data_lines:
                            continue
                        payload = "\n".join(data_lines)
                        data_lines.clear()
                        for event in parser.feed(payload):
                            event = self._sanitize(event)
                            if event.terminal:
                                self._terminal(event)
                            yield event
                        if parser.terminal:
                            self.last_unknown_event_types = tuple(
                                parser.unknown_event_types)
                            return
                        continue
                    if line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())

                if data_lines and not parser.terminal:
                    for event in parser.feed("\n".join(data_lines)):
                        event = self._sanitize(event)
                        if event.terminal:
                            self._terminal(event)
                        yield event
                for event in parser.eof():
                    event = self._sanitize(event)
                    self._terminal(event)
                    yield event
                self.last_unknown_event_types = tuple(
                    parser.unknown_event_types)
        except asyncio.CancelledError:
            reason = (
                cancel.reason
                if cancel is not None and cancel.cancelled
                else "async model task cancelled")
            self._terminal(kind="cancelled", error=reason)
            raise
        except Exception as error:
            event = ModelEvent.failed(
                max(1, parser.seq + 1),
                f"Anthropic transport failed: "
                f"{error.__class__.__name__}: "
                f"{self._safe(error)[:220]}")
            self._terminal(event)
            yield event
        finally:
            if unsubscribe is not None:
                unsubscribe()

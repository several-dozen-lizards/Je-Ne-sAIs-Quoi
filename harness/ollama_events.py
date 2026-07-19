"""Interruptible native Ollama chat transport for the model-event contract."""
from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator, Sequence

import httpx

from adapters.model_events import CancellationToken, ModelEvent, ToolSpec


class OllamaAsyncTransport:
    """Own one native NDJSON stream, including hard cancellation closure."""

    def __init__(self, model: str, *, host: str = "http://localhost:11434",
                 stops=(), num_ctx: int = None, think: bool = None,
                 keep_alive=None, timeout_s: float = 360.0,
                 client: httpx.AsyncClient = None):
        self.model = str(model)
        self.url = host.rstrip("/") + "/api/chat"
        self.stops = tuple(stops or ())
        self.num_ctx = num_ctx
        self.think = think
        self.keep_alive = keep_alive
        self.timeout_s = float(timeout_s)
        self._client = client
        self._owns_client = client is None
        self.last_terminal_receipt = None
        self.last_attempt_receipts = ()

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout_s)
        return self._client

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _terminal(self, event: ModelEvent = None, *, kind: str = None,
                  error: str = "") -> None:
        if self.last_terminal_receipt is not None:
            return
        receipt = (event.to_receipt() if event is not None else {
            "kind": kind, "error": error})
        receipt["transport"] = "ollama_native_httpx_async"
        self.last_terminal_receipt = receipt

    def _body(self, system: str, user: str, max_tokens: int,
              temperature: float, images: list) -> dict:
        user_message = {"role": "user", "content": user}
        if images:
            user_message["images"] = [image["data"] for image in images]
        options = {
            "num_predict": int(max_tokens),
            "temperature": float(temperature),
        }
        if self.stops:
            options["stop"] = list(self.stops)
        if self.num_ctx:
            options["num_ctx"] = int(self.num_ctx)
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system}, user_message],
            "stream": True,
            "options": options,
        }
        if self.think is not None:
            body["think"] = self.think
        if self.keep_alive is not None:
            body["keep_alive"] = self.keep_alive
        return body

    async def events(
            self, system: str, user: str, *, max_tokens: int = 400,
            temperature: float = 0.7, images: list = None,
            tools: Sequence[ToolSpec] = (), cancel: CancellationToken = None,
            ) -> AsyncIterator[ModelEvent]:
        self.last_terminal_receipt = None
        self.last_attempt_receipts = ()
        if tools:
            event = ModelEvent.failed(
                1, "native Ollama desk transport does not admit tools")
            self._terminal(event)
            yield event
            return
        if cancel is not None and cancel.cancelled:
            event = ModelEvent.cancelled(1, cancel.reason)
            self._terminal(event)
            yield event
            return
        body = self._body(
            system, user, max_tokens, temperature, list(images or []))
        task = asyncio.current_task()
        loop = asyncio.get_running_loop()
        unsubscribe = None
        if cancel is not None:
            unsubscribe = cancel.subscribe(
                lambda reason: loop.call_soon_threadsafe(task.cancel, reason))
        seq = 0
        completed = False
        try:
            client = await self._http()
            async with client.stream("POST", self.url, json=body) as response:
                if response.status_code != 200:
                    raw = (await response.aread()).decode(
                        "utf-8", errors="replace")
                    event = ModelEvent.failed(
                        1, f"Ollama API {response.status_code}: {raw[:300]}")
                    self._terminal(event)
                    yield event
                    return
                async for line in response.aiter_lines():
                    if cancel is not None and cancel.cancelled:
                        raise asyncio.CancelledError(cancel.reason)
                    if not line.strip():
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        event = ModelEvent.failed(
                            seq + 1, "Ollama stream contained invalid JSON")
                        self._terminal(event)
                        yield event
                        return
                    if payload.get("error"):
                        event = ModelEvent.failed(
                            seq + 1, "Ollama stream failed: "
                            + str(payload.get("error"))[:260])
                        self._terminal(event)
                        yield event
                        return
                    text = str((payload.get("message") or {}).get(
                        "content") or "")
                    if text:
                        seq += 1
                        yield ModelEvent.text_delta(seq, text)
                    if payload.get("done"):
                        input_tokens = int(payload.get(
                            "prompt_eval_count") or 0)
                        output_tokens = int(payload.get("eval_count") or 0)
                        # Ollama reports nanosecond-native phase timings on the
                        # terminal frame.  Preserve those content-free receipts
                        # so local autonomous work is measurable beside paid
                        # provider calls instead of appearing to take 0 ms.
                        total_ms = float(payload.get("total_duration") or 0) / 1e6
                        prompt_ms = float(
                            payload.get("prompt_eval_duration") or 0) / 1e6
                        gen_ms = float(payload.get("eval_duration") or 0) / 1e6
                        load_ms = float(payload.get("load_duration") or 0) / 1e6
                        seq += 1
                        event = ModelEvent.completed(
                            seq, str(payload.get("done_reason") or "stop"), {
                                "input_tokens": input_tokens,
                                "output_tokens": output_tokens,
                                "total_tokens": input_tokens + output_tokens,
                                "total_ms": total_ms,
                                "provider_ms": total_ms,
                                "prompt_ms": prompt_ms,
                                "gen_ms": gen_ms,
                                "load_ms": load_ms,
                            })
                        completed = True
                        self._terminal(event)
                        yield event
                        return
            if not completed:
                event = ModelEvent.failed(
                    seq + 1, "Ollama stream ended without completion")
                self._terminal(event)
                yield event
        except asyncio.CancelledError:
            reason = (cancel.reason if cancel is not None and cancel.cancelled
                      else "async model task cancelled")
            self._terminal(kind="cancelled", error=reason)
            raise
        except Exception as exc:
            event = ModelEvent.failed(
                seq + 1, "Ollama transport failed: "
                f"{type(exc).__name__}: {str(exc)[:220]}")
            self._terminal(event)
            yield event
        finally:
            if unsubscribe is not None:
                unsubscribe()

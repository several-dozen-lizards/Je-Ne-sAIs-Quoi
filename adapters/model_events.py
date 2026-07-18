"""Neutral structured model-event contract for the future agentic seam.

This module is deliberately transport-free.  It does not call a provider,
execute a tool, alter PromptAssembly, or change the existing adapter
``call(...) -> str`` path.  It names the boundary P1/P2 must implement:

* tools are JSON-schema declarations;
* model output is an ordered stream of visible text and structured tool calls;
* tool results return by stable call id;
* one terminal event closes every model turn;
* cancellation belongs to the host and carries an inspectable reason.

Provider translation remains in family adapters.  Authority remains above this
contract: a valid tool call is a request, never permission to execute it.
"""
from __future__ import annotations

import copy
import re
import threading
from collections.abc import AsyncIterable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
EVENT_KINDS = frozenset({
    "text_delta", "tool_call", "completed", "failed", "cancelled",
})
TERMINAL_KINDS = frozenset({"completed", "failed", "cancelled"})


class EventContractError(ValueError):
    """A malformed neutral event stream or tool exchange."""


class UnexpectedToolCall(EventContractError):
    """The legacy text surface received a tool call it cannot discard."""


class ModelTurnFailed(RuntimeError):
    """A structured model turn ended in a provider/adapter failure."""


class ModelCancelled(RuntimeError):
    """A host cancellation reached the model-event boundary."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"model turn cancelled: {reason}")


@dataclass(frozen=True)
class AuthorityDecision:
    """Host-owned effect permission; valid model output is never authority."""

    allowed: bool
    reason: str


class CancellationToken:
    """Thread-safe, first-reason-wins cancellation request.

    ``cancel()`` is intentionally idempotent.  The first caller records why
    the run must stop; later callers cannot launder that causal receipt.
    P0 proves the signal contract only.  Provider transports must prove that
    they can abort in-flight I/O before P2 may claim hard interruption.
    """

    def __init__(self):
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._reason = ""
        self._callbacks = []

    def cancel(self, reason: str) -> bool:
        reason = str(reason or "").strip()
        if not reason:
            raise ValueError("cancellation requires a reason")
        with self._lock:
            if self._event.is_set():
                return False
            self._reason = reason
            self._event.set()
            callbacks = tuple(self._callbacks)
            self._callbacks.clear()
        for callback in callbacks:
            try:
                callback(reason)
            except Exception:
                # The cancellation signal is already committed.  A stale
                # observer must not prevent other owners from seeing it.
                pass
        return True

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        with self._lock:
            return self._reason

    def wait(self, timeout: float = None) -> bool:
        return self._event.wait(timeout)

    def raise_if_cancelled(self):
        if self.cancelled:
            raise ModelCancelled(self.reason)

    def subscribe(self, callback: Callable[[str], None]) -> Callable[[], None]:
        """Run ``callback`` once when cancellation first lands.

        The callback executes in the thread that calls ``cancel``.  Async
        owners should use ``loop.call_soon_threadsafe`` inside it.  Returning
        an unsubscribe function keeps completed requests from retaining their
        task closures.  This is an edge-triggered wakeup, not a polling loop.
        """
        if not callable(callback):
            raise TypeError("cancellation callback must be callable")
        with self._lock:
            if self._event.is_set():
                reason = self._reason
            else:
                self._callbacks.append(callback)
                reason = None
        if reason is not None:
            try:
                callback(reason)
            except Exception:
                pass

        def unsubscribe():
            with self._lock:
                try:
                    self._callbacks.remove(callback)
                except ValueError:
                    pass

        return unsubscribe


def _tool_name(value: str) -> str:
    value = str(value or "")
    if not TOOL_NAME_RE.fullmatch(value):
        raise EventContractError(
            "tool name must match ^[A-Za-z0-9_-]{1,64}$")
    return value


def _mapping(value, label: str) -> dict:
    if not isinstance(value, Mapping):
        raise EventContractError(f"{label} must be a mapping")
    return copy.deepcopy(dict(value))


@dataclass(frozen=True)
class ToolSpec:
    """Provider-neutral function-tool declaration."""

    name: str
    description: str
    input_schema: Mapping[str, Any]

    def __post_init__(self):
        object.__setattr__(self, "name", _tool_name(self.name))
        description = str(self.description or "").strip()
        if not description:
            raise EventContractError("tool description must not be empty")
        object.__setattr__(self, "description", description)
        schema = _mapping(self.input_schema, "tool input_schema")
        if schema.get("type") != "object":
            raise EventContractError(
                "tool input_schema must be a JSON Schema object")
        object.__setattr__(self, "input_schema", schema)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": copy.deepcopy(dict(self.input_schema)),
        }


@dataclass(frozen=True)
class ToolCall:
    """One model request to execute a named tool."""

    call_id: str
    name: str
    arguments: Mapping[str, Any]

    def __post_init__(self):
        call_id = str(self.call_id or "").strip()
        if not call_id:
            raise EventContractError("tool call requires a call_id")
        object.__setattr__(self, "call_id", call_id)
        object.__setattr__(self, "name", _tool_name(self.name))
        object.__setattr__(
            self, "arguments", _mapping(self.arguments, "tool arguments"))

    def to_dict(self) -> dict:
        return {
            "call_id": self.call_id,
            "name": self.name,
            "arguments": copy.deepcopy(dict(self.arguments)),
        }


@dataclass(frozen=True)
class ToolResult:
    """One host result returned to the model for a prior call id."""

    call_id: str
    name: str
    content: Any
    is_error: bool = False

    def __post_init__(self):
        call_id = str(self.call_id or "").strip()
        if not call_id:
            raise EventContractError("tool result requires a call_id")
        object.__setattr__(self, "call_id", call_id)
        object.__setattr__(self, "name", _tool_name(self.name))
        object.__setattr__(self, "content", copy.deepcopy(self.content))
        object.__setattr__(self, "is_error", bool(self.is_error))

    def to_dict(self) -> dict:
        return {
            "call_id": self.call_id,
            "name": self.name,
            "content": copy.deepcopy(self.content),
            "is_error": self.is_error,
        }


@dataclass(frozen=True)
class ModelEvent:
    """One ordered event from a single provider model turn."""

    seq: int
    kind: str
    text: str = ""
    call: ToolCall | None = None
    finish_reason: str | None = None
    usage: Mapping[str, Any] = field(default_factory=dict)
    error: str = ""

    def __post_init__(self):
        if not isinstance(self.seq, int) or self.seq < 1:
            raise EventContractError("event seq must be a positive integer")
        if self.kind not in EVENT_KINDS:
            raise EventContractError(f"unknown model event kind {self.kind!r}")
        usage = _mapping(self.usage, "event usage")
        object.__setattr__(self, "usage", usage)
        text = str(self.text or "")
        error = str(self.error or "").strip()
        object.__setattr__(self, "text", text)
        object.__setattr__(self, "error", error)

        if self.kind == "text_delta":
            if not text:
                raise EventContractError("text_delta must contain text")
            if self.call or self.finish_reason is not None or error or usage:
                raise EventContractError(
                    "text_delta cannot carry call, terminal, error, or usage")
        elif self.kind == "tool_call":
            if not isinstance(self.call, ToolCall):
                raise EventContractError("tool_call must carry ToolCall")
            if text or self.finish_reason is not None or error or usage:
                raise EventContractError(
                    "tool_call cannot carry text, terminal, error, or usage")
        elif self.kind == "completed":
            if text or self.call or error:
                raise EventContractError(
                    "completed cannot carry text, call, or error")
        elif self.kind in {"failed", "cancelled"}:
            if not error:
                raise EventContractError(
                    f"{self.kind} must carry an inspectable reason")
            if text or self.call or self.finish_reason is not None or usage:
                raise EventContractError(
                    f"{self.kind} cannot carry text, call, finish, or usage")

    @classmethod
    def text_delta(cls, seq: int, text: str) -> "ModelEvent":
        return cls(seq=seq, kind="text_delta", text=text)

    @classmethod
    def tool_call(cls, seq: int, call: ToolCall) -> "ModelEvent":
        return cls(seq=seq, kind="tool_call", call=call)

    @classmethod
    def completed(cls, seq: int, finish_reason: str = None,
                  usage: Mapping[str, Any] = None) -> "ModelEvent":
        return cls(seq=seq, kind="completed", finish_reason=finish_reason,
                   usage=usage or {})

    @classmethod
    def failed(cls, seq: int, error: str) -> "ModelEvent":
        return cls(seq=seq, kind="failed", error=error)

    @classmethod
    def cancelled(cls, seq: int, reason: str) -> "ModelEvent":
        return cls(seq=seq, kind="cancelled", error=reason)

    @property
    def terminal(self) -> bool:
        return self.kind in TERMINAL_KINDS

    def to_receipt(self) -> dict:
        receipt = {"seq": self.seq, "kind": self.kind}
        if self.text:
            receipt["text_chars"] = len(self.text)
        if self.call:
            receipt["tool_call"] = self.call.to_dict()
        if self.finish_reason is not None:
            receipt["finish_reason"] = self.finish_reason
        if self.usage:
            receipt["usage"] = copy.deepcopy(dict(self.usage))
        if self.error:
            receipt["error"] = self.error
        return receipt


def validate_event_stream(events: Iterable[ModelEvent],
                          tools: Sequence[ToolSpec] = ()) -> tuple:
    """Freeze and validate one complete model-turn event stream."""
    frozen = tuple(events)
    if not frozen:
        raise EventContractError("model event stream must not be empty")
    advertised = {tool.name for tool in tools}
    call_ids = set()
    terminal_at = None
    for expected, event in enumerate(frozen, start=1):
        if not isinstance(event, ModelEvent):
            raise EventContractError("stream contains a non-ModelEvent")
        if event.seq != expected:
            raise EventContractError(
                f"event seq gap: expected {expected}, got {event.seq}")
        if terminal_at is not None:
            raise EventContractError("event appeared after terminal event")
        if event.kind == "tool_call":
            if advertised and event.call.name not in advertised:
                raise EventContractError(
                    f"model requested unadvertised tool {event.call.name!r}")
            if event.call.call_id in call_ids:
                raise EventContractError(
                    f"duplicate tool call id {event.call.call_id!r}")
            call_ids.add(event.call.call_id)
        if event.terminal:
            terminal_at = event.seq
    if terminal_at is None:
        raise EventContractError("model event stream has no terminal event")
    return frozen


def validate_tool_results(calls: Sequence[ToolCall],
                          results: Sequence[ToolResult]) -> tuple:
    """Prove each result names one known call exactly once."""
    known = {call.call_id: call for call in calls}
    if len(known) != len(calls):
        raise EventContractError("tool calls contain duplicate call ids")
    seen = set()
    for result in results:
        if not isinstance(result, ToolResult):
            raise EventContractError("results contain a non-ToolResult")
        if result.call_id in seen:
            raise EventContractError(
                f"duplicate tool result id {result.call_id!r}")
        call = known.get(result.call_id)
        if call is None:
            raise EventContractError(
                f"tool result references unknown call {result.call_id!r}")
        if result.name != call.name:
            raise EventContractError(
                f"tool result name {result.name!r} does not match "
                f"call {call.name!r}")
        seen.add(result.call_id)
    return tuple(results)


@dataclass(frozen=True)
class ModelTurn:
    """One completed assistant turn retained for an explicit continuation."""

    events: Sequence[ModelEvent]

    def __post_init__(self):
        frozen = validate_event_stream(self.events)
        terminal = frozen[-1]
        if terminal.kind != "completed":
            raise EventContractError(
                "only a completed model turn can enter continuation history")
        object.__setattr__(self, "events", frozen)

    @property
    def calls(self) -> tuple:
        return tuple(
            event.call for event in self.events
            if event.kind == "tool_call")

    @property
    def finish_reason(self) -> str | None:
        return self.events[-1].finish_reason

    @property
    def usage(self) -> dict:
        return copy.deepcopy(dict(self.events[-1].usage))

    def to_receipt(self) -> dict:
        return {
            "events": [event.to_receipt() for event in self.events],
            "tool_call_ids": [call.call_id for call in self.calls],
        }


@dataclass(frozen=True)
class ModelExchange:
    """An assistant tool-call turn plus its complete correlated results."""

    assistant: ModelTurn
    tool_results: Sequence[ToolResult]
    continuation: Sequence[str] = ()

    def __post_init__(self):
        if not isinstance(self.assistant, ModelTurn):
            raise EventContractError(
                "exchange assistant must be a ModelTurn")
        calls = self.assistant.calls
        if not calls:
            raise EventContractError(
                "exchange assistant turn contains no tool calls")
        results = validate_tool_results(calls, self.tool_results)
        expected = {call.call_id for call in calls}
        observed = {result.call_id for result in results}
        if observed != expected:
            missing = sorted(expected - observed)
            raise EventContractError(
                f"exchange requires one result for every tool call; "
                f"missing={missing}")
        continuation = []
        for item in self.continuation:
            if not isinstance(item, str) or not item.strip():
                raise EventContractError(
                    "exchange continuation items must be nonempty strings")
            continuation.append(item)
        object.__setattr__(self, "tool_results", results)
        object.__setattr__(self, "continuation", tuple(continuation))

    def to_receipt(self) -> dict:
        return {
            "assistant": self.assistant.to_receipt(),
            "tool_results": [{
                "call_id": result.call_id,
                "name": result.name,
                "is_error": result.is_error,
                "content_type": type(result.content).__name__,
                "content_chars": len(
                    result.content
                    if isinstance(result.content, str)
                    else repr(result.content)),
            } for result in self.tool_results],
            "continuation": {
                "count": len(self.continuation),
                "item_chars": [len(item) for item in self.continuation],
            },
        }


def validate_exchanges(exchanges: Sequence[ModelExchange]) -> tuple:
    """Freeze explicit continuation history and reject call-id collisions."""
    frozen = tuple(exchanges)
    seen = set()
    for exchange in frozen:
        if not isinstance(exchange, ModelExchange):
            raise EventContractError(
                "continuation contains a non-ModelExchange")
        for call in exchange.assistant.calls:
            if call.call_id in seen:
                raise EventContractError(
                    f"continuation repeats tool call id {call.call_id!r}")
            seen.add(call.call_id)
    return frozen


def collect_legacy_text(events: Iterable[ModelEvent],
                        cancel: CancellationToken = None) -> str:
    """Compatibility law for the existing ``call(...) -> str`` surface.

    Future adapters may implement ``call`` by collecting a structured turn
    only when no tools were advertised.  An unexpected tool request is never
    dropped or rendered as prose; it is a loud contract failure.
    """
    frozen = []
    for event in events:
        if cancel is not None:
            cancel.raise_if_cancelled()
        frozen.append(event)
    stream = validate_event_stream(frozen)
    text = []
    for event in stream:
        if event.kind == "text_delta":
            text.append(event.text)
        elif event.kind == "tool_call":
            raise UnexpectedToolCall(
                f"legacy text call received tool {event.call.name!r}")
        elif event.kind == "failed":
            raise ModelTurnFailed(event.error)
        elif event.kind == "cancelled":
            raise ModelCancelled(event.error)
    return "".join(text)


@dataclass(frozen=True)
class ToolCapabilityStatus:
    declared: bool
    event_bridge: bool
    usable: bool
    reason: str


def tool_capability_status(spec: Mapping[str, Any],
                           event_bridge: bool = False) -> ToolCapabilityStatus:
    """Separate a model declaration from a genuinely wired tool pathway."""
    capabilities = (spec.get("capabilities") or {}
                    if isinstance(spec, Mapping) else {})
    declared = bool(capabilities.get("tool_use"))
    event_bridge = bool(event_bridge)
    usable = declared and event_bridge
    if usable:
        reason = "declared and structured event bridge present"
    elif not declared:
        reason = "model spec does not declare tool use"
    else:
        reason = "model declares tool use but no structured event bridge exists"
    return ToolCapabilityStatus(declared, event_bridge, usable, reason)


@runtime_checkable
class StructuredModelAdapter(Protocol):
    """Synchronous P0 fixture surface retained for compatibility spikes."""

    def events(self, assembly: Any, *, tools: Sequence[ToolSpec] = (),
               tool_results: Sequence[ToolResult] = (),
               max_tokens: int = 400, temperature: float = 0.7,
               cancel: CancellationToken = None) -> Iterable[ModelEvent]:
        ...


@runtime_checkable
class AsyncStructuredModelAdapter(Protocol):
    """The production transport-neutral async event surface."""

    def events(self, assembly: Any, *, tools: Sequence[ToolSpec] = (),
               exchanges: Sequence[ModelExchange] = (),
               max_tokens: int = 400, temperature: float = 0.7,
               cancel: CancellationToken = None) -> AsyncIterable[ModelEvent]:
        ...

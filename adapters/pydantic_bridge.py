"""Pydantic AI bridge over JNSQ's neutral async model-event seam.

The persona-local agency runtime may import this bridge only after a genuine
field winner, organ/config policy, model capability, and runtime dependency all
admit a run.  It gives that bounded run a fresh JNSQ assembly for every
provider request while keeping authority, cancellation, provider
configuration, and teardown host-owned.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import inspect
import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable, Mapping, Sequence

from adapters.model_events import (
    AuthorityDecision, CancellationToken, ModelCancelled, ModelEvent,
    ModelExchange, ModelTurn, ModelTurnFailed, ToolCall, ToolResult, ToolSpec,
    validate_event_stream,
)
from pydantic_ai import Agent
from pydantic_ai.capabilities import Hooks
from pydantic_ai.exceptions import ApprovalRequired
from pydantic_ai.messages import (
    ModelRequest, ModelResponse, RetryPromptPart, TextPart, ToolCallPart,
    ToolReturnPart, UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.tools import DeferredToolRequests
from pydantic_ai.usage import RequestUsage, UsageLimits


class BridgeContractError(ValueError):
    """Pydantic messages or host wiring violated the bounded bridge grammar."""


def _plain(value):
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return copy.deepcopy(value)


@dataclass(frozen=True)
class AssemblySnapshot:
    assembly: Any
    state_ref: str
    temperature: float = 0.7
    projection_receipt: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        state_ref = str(self.state_ref or "").strip()
        if not state_ref:
            raise ValueError("assembly snapshot requires a state_ref")
        temperature = float(self.temperature)
        if not math.isfinite(temperature):
            raise ValueError("assembly snapshot temperature must be finite")
        object.__setattr__(self, "state_ref", state_ref)
        object.__setattr__(self, "temperature", temperature)
        object.__setattr__(
            self, "projection_receipt",
            _plain(dict(self.projection_receipt or {})))


@dataclass(frozen=True)
class BridgeBudget:
    """Run budget derived from admitted graph shape, never framework defaults."""

    admitted_tool_rounds: int
    correction_turns: int
    tool_slots: int
    max_tokens_per_request: int = 400
    input_tokens_limit: int | None = None
    output_tokens_limit: int | None = None
    total_tokens_limit: int | None = None

    def __post_init__(self):
        for name in (
                "admitted_tool_rounds", "correction_turns", "tool_slots"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must not be negative")
        if self.max_tokens_per_request < 1:
            raise ValueError("max_tokens_per_request must be positive")

    @property
    def request_limit(self) -> int:
        return 1 + self.admitted_tool_rounds + self.correction_turns

    def usage_limits(self) -> UsageLimits:
        return UsageLimits(
            request_limit=self.request_limit,
            tool_calls_limit=self.tool_slots,
            input_tokens_limit=self.input_tokens_limit,
            output_tokens_limit=self.output_tokens_limit,
            total_tokens_limit=self.total_tokens_limit,
        )


AssemblyFactory = Callable[["BridgeRunState"], AssemblySnapshot | Any |
                           Awaitable[AssemblySnapshot | Any]]
AuthorityCheck = Callable[
    ["BridgeRunState", ToolCallPart, Mapping[str, Any], str],
    AuthorityDecision | bool | Awaitable[AuthorityDecision | bool],
]


@dataclass
class BridgeRunState:
    run_id: str
    task: str
    substrate_mode: str
    captured_epoch: int
    live_epoch: Callable[[], int]
    cancellation: CancellationToken
    assembly_factory: AssemblyFactory
    adapter: Any
    authority: AuthorityCheck
    budget: BridgeBudget
    tool_tiers: Mapping[str, str] = field(default_factory=dict)
    receipts: list[dict[str, Any]] = field(default_factory=list)
    snapshot: AssemblySnapshot | None = None
    snapshot_consumed: bool = True
    request_count: int = 0
    provider_http_attempts: int = 0

    @property
    def task_digest(self) -> str:
        return _digest(self.task)

    def receipt(self, kind: str, **values: Any) -> None:
        self.receipts.append({"kind": kind, **values})


@dataclass(frozen=True)
class BridgeRunResult:
    output: str | DeferredToolRequests
    receipts: tuple[dict[str, Any], ...]
    usage: dict[str, Any]
    messages: tuple[Any, ...]
    provider: None
    request_limit: int
    provider_http_attempts: int


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, default=str,
        separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


def enqueue_bridge_steering(ctx, text: str) -> None:
    """Return a descriptive tool consequence to the next model request."""
    if not isinstance(text, str) or not text.strip():
        raise BridgeContractError("bridge steering must be a nonempty string")
    ctx.enqueue(text, priority="asap")
    ctx.deps.receipt(
        "steering_enqueued", text_chars=len(text), text_digest=_digest(text))


def _tool_specs(info: AgentInfo) -> tuple[ToolSpec, ...]:
    if info.output_tools:
        raise BridgeContractError(
            "P2C1 does not admit Pydantic output tools")
    if not info.allow_text_output:
        raise BridgeContractError("P2C1 requires plain text output")
    specs = []
    for tool in info.function_tools:
        if tool.kind != "function":
            raise BridgeContractError(
                f"P2C1 does not admit tool kind {tool.kind!r}")
        if not tool.description:
            raise BridgeContractError(
                f"tool {tool.name!r} requires a description")
        specs.append(ToolSpec(
            tool.name, tool.description, tool.parameters_json_schema))
    return tuple(specs)


def _initial_task(messages: Sequence[Any]) -> str:
    if not messages or not isinstance(messages[0], ModelRequest):
        raise BridgeContractError(
            "bridge history must start with a ModelRequest")
    parts = tuple(messages[0].parts)
    if len(parts) != 1 or not isinstance(parts[0], UserPromptPart) \
            or not isinstance(parts[0].content, str):
        raise BridgeContractError(
            "initial request must contain exactly one text user prompt")
    return parts[0].content


def _response_turn(message: ModelResponse) -> ModelTurn:
    events = []
    for part in message.parts:
        if isinstance(part, TextPart):
            if part.content:
                events.append(ModelEvent.text_delta(
                    len(events) + 1, part.content))
        elif isinstance(part, ToolCallPart):
            if not part.tool_call_id:
                raise BridgeContractError(
                    "Pydantic history lost the provider tool call id")
            events.append(ModelEvent.tool_call(
                len(events) + 1,
                ToolCall(part.tool_call_id, part.tool_name,
                         part.args_as_dict(raise_if_invalid=True))))
        else:
            raise BridgeContractError(
                f"unsupported response part {type(part).__name__}")
    finish = message.provider_details or {}
    original = finish.get("jnsq_finish_reason")
    if not original:
        original = (
            "tool_calls" if any(
                event.kind == "tool_call" for event in events)
            else (message.finish_reason or "stop"))
    usage = {
        "input_tokens": message.usage.input_tokens,
        "output_tokens": message.usage.output_tokens,
        "cache_read_tokens": message.usage.cache_read_tokens,
        "cache_write_tokens": message.usage.cache_write_tokens,
    }
    usage = {key: value for key, value in usage.items() if value}
    events.append(ModelEvent.completed(
        len(events) + 1, str(original), usage))
    return ModelTurn(events)


def _exchange(
        response: ModelResponse, request: ModelRequest) -> ModelExchange:
    turn = _response_turn(response)
    calls = {call.call_id: call for call in turn.calls}
    results = []
    continuation = []
    for part in request.parts:
        if isinstance(part, ToolReturnPart):
            call = calls.get(part.tool_call_id)
            if call is None or part.tool_name != call.name:
                raise BridgeContractError(
                    "tool return does not correlate to the preceding call")
            results.append(ToolResult(
                part.tool_call_id, part.tool_name, part.content,
                is_error=part.outcome != "success"))
        elif isinstance(part, RetryPromptPart):
            call = calls.get(part.tool_call_id)
            if call is None or part.tool_name != call.name:
                raise BridgeContractError(
                    "retry prompt does not correlate to the preceding call")
            results.append(ToolResult(
                part.tool_call_id, part.tool_name, part.model_response(),
                is_error=True))
        elif isinstance(part, UserPromptPart) and \
                isinstance(part.content, str):
            continuation.append(part.content)
        else:
            raise BridgeContractError(
                f"unsupported continuation part {type(part).__name__}")
    return ModelExchange(turn, results, continuation)


def _exchanges(messages: Sequence[Any]) -> tuple[ModelExchange, ...]:
    _initial_task(messages)
    tail = list(messages[1:])
    if not tail:
        return ()
    if len(tail) % 2:
        raise BridgeContractError(
            "bridge history must contain response/request exchange pairs")
    exchanges = []
    for index in range(0, len(tail), 2):
        response, request = tail[index:index + 2]
        if not isinstance(response, ModelResponse) \
                or not isinstance(request, ModelRequest):
            raise BridgeContractError(
                "bridge history alternation must be response then request")
        exchanges.append(_exchange(response, request))
    return tuple(exchanges)


def _usage(values: Mapping[str, Any]) -> RequestUsage:
    def number(*names):
        for name in names:
            value = values.get(name)
            if isinstance(value, (int, float)) and value >= 0:
                return int(value)
        return 0

    details = {
        str(key): int(value) for key, value in values.items()
        if isinstance(value, (int, float)) and key not in {
            "input_tokens", "prompt_tokens", "output_tokens",
            "completion_tokens", "cache_read_tokens",
            "cached_tokens", "cache_write_tokens",
        }
    }
    return RequestUsage(
        input_tokens=number("input_tokens", "prompt_tokens"),
        output_tokens=number("output_tokens", "completion_tokens"),
        cache_read_tokens=number("cache_read_tokens", "cached_tokens"),
        cache_write_tokens=number("cache_write_tokens"),
        details=details,
    )


def _response(events: Sequence[ModelEvent]) -> ModelResponse:
    stream = validate_event_stream(events)
    parts = []
    terminal = stream[-1]
    for event in stream:
        if event.kind == "text_delta":
            parts.append(TextPart(event.text))
        elif event.kind == "tool_call":
            parts.append(ToolCallPart(
                event.call.name, dict(event.call.arguments),
                event.call.call_id))
        elif event.kind == "failed":
            raise ModelTurnFailed(event.error)
        elif event.kind == "cancelled":
            raise ModelCancelled(event.error)
    finish = str(terminal.finish_reason or "")
    if finish in {"tool_calls", "tool_use"}:
        normalized = "tool_call"
    elif finish in {"length", "max_tokens"}:
        normalized = "length"
    elif finish in {"content_filter"}:
        normalized = "content_filter"
    elif finish in {"error"}:
        normalized = "error"
    else:
        normalized = "stop"
    return ModelResponse(
        parts,
        usage=_usage(terminal.usage),
        finish_reason=normalized,
        provider_details={"jnsq_finish_reason": finish or None},
    )


def _http_attempts(adapter: Any) -> int:
    transport = getattr(adapter, "event_transport", None)
    if transport is None:
        return int(getattr(adapter, "last_http_attempts", 1))
    attempts = getattr(transport, "last_attempt_receipts", None)
    if attempts is not None:
        return 1 + len(attempts)
    terminal = getattr(transport, "last_terminal_receipt", None) or {}
    return int(terminal.get("attempts") or 1)


class PydanticJNSQBridge:
    def __init__(self, state: BridgeRunState):
        self.state = state

    async def request(
            self, messages: list[Any], info: AgentInfo) -> ModelResponse:
        state = self.state
        state.cancellation.raise_if_cancelled()
        if state.snapshot is None or state.snapshot_consumed:
            raise BridgeContractError(
                "model request has no fresh unconsumed JNSQ assembly")
        if _digest(_initial_task(messages)) != state.task_digest:
            raise BridgeContractError(
                "Pydantic task diverged from the run envelope")
        tools = _tool_specs(info)
        exchanges = _exchanges(messages)
        snapshot = state.snapshot
        state.snapshot_consumed = True
        state.request_count += 1
        state.receipt(
            "bridge_request", request=state.request_count,
            state_ref=snapshot.state_ref, exchange_count=len(exchanges),
            tool_count=len(tools))
        events = [
            event async for event in state.adapter.events(
                snapshot.assembly, tools=tools, exchanges=exchanges,
                max_tokens=state.budget.max_tokens_per_request,
                temperature=snapshot.temperature,
                cancel=state.cancellation)
        ]
        frozen = validate_event_stream(events, tools=tools)
        attempts = _http_attempts(state.adapter)
        state.provider_http_attempts += attempts
        state.receipt(
            "provider_turn", request=state.request_count,
            http_attempts=attempts,
            event_kinds=[event.kind for event in frozen],
            finish_reason=frozen[-1].finish_reason)
        return _response(frozen)


def _hooks() -> Hooks[BridgeRunState]:
    hooks = Hooks[BridgeRunState]()

    @hooks.on.before_model_request
    async def fresh_assembly(ctx, request_context):
        state = ctx.deps
        state.cancellation.raise_if_cancelled()
        live = state.live_epoch()
        if live != state.captured_epoch:
            state.cancellation.cancel(
                f"demand epoch changed {state.captured_epoch}->{live}")
            state.cancellation.raise_if_cancelled()
        value = await _maybe_await(state.assembly_factory(state))
        if isinstance(value, AssemblySnapshot):
            snapshot = value
        else:
            snapshot = AssemblySnapshot(
                value, f"assembly-{state.request_count + 1}")
        state.snapshot = snapshot
        state.snapshot_consumed = False
        state.receipt(
            "assembly_fresh", request=state.request_count + 1,
            state_ref=snapshot.state_ref,
            substrate_mode=state.substrate_mode,
            temperature=snapshot.temperature,
            projection=copy.deepcopy(
                dict(snapshot.projection_receipt or {})))
        return request_context

    @hooks.on.before_tool_execute
    async def check_authority(ctx, *, call, tool_def, args):
        state = ctx.deps
        state.cancellation.raise_if_cancelled()
        tier = state.tool_tiers.get(call.tool_name, "unclassified")
        state.receipt(
            "authority_requested", call_id=call.tool_call_id,
            tool=call.tool_name, tier=tier, args_digest=_digest(args),
            state_ref=(state.snapshot.state_ref if state.snapshot else None))
        raw = await _maybe_await(
            state.authority(state, call, args, tier))
        if isinstance(raw, AuthorityDecision):
            decision = raw
        else:
            decision = AuthorityDecision(bool(raw), "host boolean decision")
        state.receipt(
            "authority_decided", call_id=call.tool_call_id,
            tool=call.tool_name, allowed=decision.allowed,
            reason=decision.reason)
        if not decision.allowed:
            raise ApprovalRequired({
                "run_id": state.run_id,
                "tool": call.tool_name,
                "tier": tier,
                "reason": decision.reason,
            })
        return args

    @hooks.on.after_tool_execute
    async def record_result(ctx, *, call, tool_def, args, result):
        ctx.deps.receipt(
            "tool_result", call_id=call.tool_call_id,
            tool=call.tool_name, result_type=type(result).__name__,
            result_digest=_digest(result))
        return result

    return hooks


class JNSQBridgeRunOwner:
    """Own one active Pydantic graph, adapter, cancellation edge, and close."""

    def __init__(
            self, *, state: BridgeRunState, tools: Sequence[Callable]):
        self.state = state
        self.bridge = PydanticJNSQBridge(state)
        self.model = FunctionModel(
            self.bridge.request, model_name="jnsq-p2c1-bridge")
        self.agent = Agent(
            self.model,
            output_type=[str, DeferredToolRequests],
            deps_type=BridgeRunState,
            tools=tools,
            capabilities=[_hooks()],
            retries={"tools": 0, "output": 0},
            name="jnsq-s1-p2c1-bridge",
        )
        self.agent.instrument = False

    async def run(self) -> BridgeRunResult:
        state = self.state
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("bridge run requires an asyncio task")
        loop = asyncio.get_running_loop()
        unsubscribe = state.cancellation.subscribe(
            lambda _reason: loop.call_soon_threadsafe(task.cancel))
        state.receipt(
            "run_started", run_id=state.run_id,
            task_digest=state.task_digest,
            request_limit=state.budget.request_limit,
            tool_slots=state.budget.tool_slots,
            instrumentation=False)
        completed = None
        try:
            result = await self.agent.run(
                state.task,
                deps=state,
                message_history=None,
                conversation_id="new",
                usage_limits=state.budget.usage_limits(),
            )
            state.receipt(
                "run_completed",
                output_type=type(result.output).__name__,
                deferred=isinstance(result.output, DeferredToolRequests))
            usage_value = (
                result.usage() if callable(result.usage) else result.usage)
            completed = (
                result.output,
                asdict(usage_value),
                tuple(result.all_messages()),
            )
        except asyncio.CancelledError:
            state.receipt(
                "run_interrupted",
                reason=state.cancellation.reason or "async task cancelled")
            raise
        except Exception as exc:
            state.receipt(
                "run_failed", error_type=type(exc).__name__,
                error=str(exc)[:240])
            raise
        finally:
            unsubscribe()
            try:
                await state.adapter.aclose_events()
            except Exception as exc:
                state.receipt(
                    "adapter_close_failed",
                    error_type=type(exc).__name__,
                    error=str(exc)[:240])
                raise
            else:
                state.receipt("adapter_closed")
        if completed is None:  # pragma: no cover - exceptions leave above
            raise RuntimeError("bridge run ended without a result")
        output, usage, messages = completed
        return BridgeRunResult(
            output=output,
            receipts=tuple(state.receipts),
            usage=usage,
            messages=messages,
            provider=self.model.provider,
            request_limit=state.budget.request_limit,
            provider_http_attempts=state.provider_http_attempts,
        )

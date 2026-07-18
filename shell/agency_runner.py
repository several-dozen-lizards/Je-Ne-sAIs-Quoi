"""Bounded production binding from persona ownership to the JNSQ bridge.

This module still contains no trigger, queue, route, organ, or policy.  The
agency runtime must already possess an immutable task envelope, an admitted
graph-derived budget, a tool/authority binding, and a persona controller
context.  The binding owns one fresh model adapter for that run and returns
only after the Pydantic/JNSQ owner has closed it.
"""
from __future__ import annotations

import inspect
import time
from contextlib import nullcontext
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

from adapters.family_adapters import adapter_for
from adapters.pydantic_bridge import (
    AssemblySnapshot, AuthorityCheck, AuthorityDecision, BridgeBudget,
    BridgeRunResult, BridgeRunState, JNSQBridgeRunOwner,
)
from core.agency_projection import (
    AgencyTaskEnvelope, SUBSTRATE_MODES,
)
from harness.model_call_receipts import (model_call_scope,
                                         record_model_call)
from pydantic_ai.tools import DeferredToolRequests
from shell.agency_controller import (
    AgencyRunContext, AgencyRunOutcome,
)


def deny_all_authority(
        _state, _call, _args, _tier) -> AuthorityDecision:
    """Default authority for a dormant binding: no effect is admitted."""
    return AuthorityDecision(False, "no agency authority admitted")


def _plain_tiers(values: Mapping[str, str]) -> Mapping[str, str]:
    tiers = {}
    for name, tier in dict(values or {}).items():
        name = str(name or "").strip()
        tier = str(tier or "").strip()
        if not name or not tier:
            raise ValueError("agency tool tiers require nonempty names/values")
        tiers[name] = tier
    return MappingProxyType(tiers)


def _usage_number(usage: Mapping[str, Any], name: str) -> int:
    value = dict(usage or {}).get(name, 0)
    return int(value) if isinstance(value, (int, float)) and value >= 0 else 0


def _metrics(result: BridgeRunResult, elapsed_ms: float) -> dict[str, Any]:
    deferred = isinstance(result.output, DeferredToolRequests)
    return {
        "model_requests": _usage_number(result.usage, "requests"),
        "provider_http_attempts": result.provider_http_attempts,
        "tool_calls": _usage_number(result.usage, "tool_calls"),
        "input_tokens": _usage_number(result.usage, "input_tokens"),
        "output_tokens": _usage_number(result.usage, "output_tokens"),
        "elapsed_ms": round(max(0.0, elapsed_ms), 3),
        "request_limit": result.request_limit,
        "output_type": type(result.output).__name__,
        "deferred": deferred,
    }


async def _close_unowned(adapter: Any) -> None:
    close = getattr(adapter, "aclose_events", None)
    if not callable(close):
        return
    value = close()
    if inspect.isawaitable(value):
        await value


@dataclass(frozen=True)
class AgencyRunnerBinding:
    """One immutable recipe for a controller-admitted agency run."""

    engine: Any
    envelope: AgencyTaskEnvelope
    substrate_mode: str
    budget: BridgeBudget
    model_spec: Mapping[str, Any] | None = None
    model_name: str | None = None
    tools: tuple[Callable, ...] = ()
    tool_tiers: Mapping[str, str] = field(default_factory=dict)
    authority: AuthorityCheck = deny_all_authority

    def __post_init__(self):
        if not isinstance(self.envelope, AgencyTaskEnvelope):
            raise TypeError("agency runner requires AgencyTaskEnvelope")
        if self.substrate_mode not in SUBSTRATE_MODES:
            raise ValueError("unknown agency substrate mode")
        if not isinstance(self.budget, BridgeBudget):
            raise TypeError("agency runner requires an explicit BridgeBudget")
        if not callable(self.authority):
            raise TypeError("agency authority must be callable")
        persona = str(getattr(self.engine, "persona", "") or "").strip()
        if not persona:
            raise ValueError("agency runner engine requires a persona")
        if not isinstance(getattr(self.engine, "spec", None), Mapping):
            raise ValueError("agency runner engine requires a model spec")
        build = getattr(self.engine, "build_agency_snapshot", None)
        if not callable(build):
            raise TypeError("agency runner engine lacks agency projection")
        tools = tuple(self.tools or ())
        if any(not callable(tool) for tool in tools):
            raise TypeError("agency tools must be callable")
        object.__setattr__(self, "tools", tools)
        selected_spec = (self.engine.spec if self.model_spec is None
                         else self.model_spec)
        if not isinstance(selected_spec, Mapping):
            raise TypeError("agency model spec must be a mapping")
        object.__setattr__(
            self, "model_spec", MappingProxyType(dict(selected_spec)))
        selected_name = str(self.model_name or (
            selected_spec.get("identity") or {}).get("name")
            or getattr(self.engine, "model", "") or "").strip()
        if not selected_name:
            raise ValueError("agency runner requires a model name")
        object.__setattr__(self, "model_name", selected_name)
        object.__setattr__(
            self, "tool_tiers", _plain_tiers(self.tool_tiers))

    async def __call__(self, context: AgencyRunContext) -> AgencyRunOutcome:
        if not isinstance(context, AgencyRunContext):
            raise TypeError("agency runner requires AgencyRunContext")
        if context.persona != self.engine.persona:
            raise ValueError("agency runner persona does not own this engine")

        adapter = adapter_for(self.model_spec)
        owner_entered = False
        started = time.monotonic()

        def fresh_assembly(state: BridgeRunState) -> AssemblySnapshot:
            engine_spec = dict(getattr(self.engine, "spec", {}) or {})
            selected_spec = dict(self.model_spec)
            cross_model = (
                self.model_name != getattr(self.engine, "model", None)
                or selected_spec != engine_spec)
            product = self.engine.build_agency_snapshot(
                self.envelope,
                substrate_mode=state.substrate_mode,
                external_demand_epoch=state.captured_epoch,
                agency_spec=(self.model_spec if cross_model else None),
                agency_model=(self.model_name if cross_model else None),
            )
            return AssemblySnapshot(
                product.assembly,
                product.state_ref,
                temperature=product.temperature,
                projection_receipt=product.projection_receipt,
            )

        state = None
        try:
            state = BridgeRunState(
                run_id=context.run_id,
                task=self.envelope.task,
                substrate_mode=self.substrate_mode,
                captured_epoch=context.captured_epoch,
                live_epoch=context.live_epoch,
                cancellation=context.cancellation,
                assembly_factory=fresh_assembly,
                adapter=adapter,
                authority=self.authority,
                budget=self.budget,
                tool_tiers=self.tool_tiers,
            )
            owner = JNSQBridgeRunOwner(state=state, tools=self.tools)
            owner_entered = True
            identity = self.model_spec.get("identity") or {}
            provider = str(identity.get("provider") or "unknown")
            endpoint_declared = identity.get("endpoint")
            endpoint = str(endpoint_declared or self.model_name)
            receipt_scope = (model_call_scope(
                cycle_id=context.run_id, persona=context.persona,
                purpose="agency") if endpoint_declared else nullcontext())
            with receipt_scope:
                try:
                    result = await owner.run()
                except Exception as error:
                    if endpoint_declared:
                        record_model_call(
                            provider, endpoint,
                            {"total_ms": (
                                time.monotonic() - started) * 1000.0,
                             "attempts": getattr(
                                 state, "provider_http_attempts", 0),
                             "error_type": type(error).__name__},
                            status="error")
                    raise
                if endpoint_declared:
                    record_model_call(
                        provider, endpoint,
                        {**dict(result.usage or {}),
                         "total_ms": (
                             time.monotonic() - started) * 1000.0,
                         "attempts": result.provider_http_attempts},
                        status="ok")
        finally:
            if not owner_entered:
                await _close_unowned(adapter)

        elapsed_ms = (time.monotonic() - started) * 1000.0
        deferred = isinstance(result.output, DeferredToolRequests)
        return AgencyRunOutcome(
            status="deferred" if deferred else "completed",
            result=result,
            metrics=_metrics(result, elapsed_ms),
        )


def bind_agency_runner(
        engine, envelope: AgencyTaskEnvelope, *,
        substrate_mode: str, budget: BridgeBudget,
        model_spec: Mapping[str, Any] = None,
        model_name: str = None,
        tools: Sequence[Callable] = (),
        tool_tiers: Mapping[str, str] = None,
        authority: AuthorityCheck = deny_all_authority,
) -> AgencyRunnerBinding:
    """Build one runner recipe; this function itself never starts it."""
    return AgencyRunnerBinding(
        engine=engine,
        envelope=envelope,
        substrate_mode=substrate_mode,
        budget=budget,
        model_spec=model_spec,
        model_name=model_name,
        tools=tuple(tools or ()),
        tool_tiers=dict(tool_tiers or {}),
        authority=authority,
    )

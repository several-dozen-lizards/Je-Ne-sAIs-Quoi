"""Persona-local ownership for one bounded async agency run.

This controller deliberately knows nothing about Pydantic AI, proposals,
tools, DMN, or provider configuration.  It owns the cross-thread lifecycle
seam the cockpit needs before any of those may be attached:

* one dedicated asyncio loop thread per persona;
* one active run at a time;
* a monotonic external-demand epoch;
* first-reason cancellation through JNSQ's neutral CancellationToken;
* non-overlapping explicit replacement;
* bounded lifecycle status and receipts;
* complete shutdown before the persona engine closes.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping

from adapters.model_events import CancellationToken


class AgencyControllerError(RuntimeError):
    """Base controller contract failure."""


class ActiveAgencyRun(AgencyControllerError):
    """A new ordinary run was refused because this persona is occupied."""


class AgencyControllerClosed(AgencyControllerError):
    """The persona controller is shutting down or already closed."""


@dataclass(frozen=True)
class AgencyRunOutcome:
    """One runner's terminal value after its own teardown has completed."""

    status: str = "completed"
    result: Any = None
    metrics: Mapping[str, int | float | str | bool | None] = field(
        default_factory=dict)

    def __post_init__(self):
        if self.status not in {"completed", "deferred"}:
            raise ValueError(
                "agency outcome status must be completed or deferred")


@dataclass(frozen=True)
class AgencyRunContext:
    """Host state handed to one injected async runner."""

    persona: str
    run_id: str
    proposal_id: str | None
    captured_epoch: int
    cancellation: CancellationToken
    live_epoch: Callable[[], int]


Runner = Callable[[AgencyRunContext],
                  Awaitable[AgencyRunOutcome | Any]]
ReceiptSink = Callable[[str, float, Mapping[str, Any]], Any]


@dataclass
class _ActiveRecord:
    run_id: str
    proposal_id: str | None
    captured_epoch: int
    cancellation: CancellationToken
    started_at: float
    done: asyncio.Event
    task: asyncio.Task | None = None
    status: str = "starting"
    cancellation_requested: bool = False


def _metrics(values: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only bounded, non-content accounting fields."""
    allowed = {
        "model_requests", "provider_http_attempts", "tool_calls",
        "input_tokens", "output_tokens", "elapsed_ms", "request_limit",
        "output_type", "deferred",
    }
    return {
        str(key): value for key, value in dict(values or {}).items()
        if key in allowed
        and (value is None or isinstance(value, (int, float, str, bool)))
    }


class AgencyRunController:
    """One persona's thread-safe async run owner."""

    def __init__(self, persona: str, receipt_sink: ReceiptSink = None):
        persona = str(persona or "").strip()
        if not persona:
            raise ValueError("agency controller requires a persona")
        self.persona = persona
        self._receipt_sink = receipt_sink
        self._meta_lock = threading.RLock()
        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._loop_main, daemon=True,
            name=f"agency-{persona}")
        self._loop = None
        self._op_lock = None
        self._external_demand_epoch = 0
        self._active: _ActiveRecord | None = None
        self._replacement_pending: str | None = None
        self._latest_terminal: dict[str, Any] | None = None
        self._futures: set[concurrent.futures.Future] = set()
        self._closed = False
        self._thread.start()
        self._ready.wait()

    def _loop_main(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._op_lock = asyncio.Lock()
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            loop.close()

    def _emit(self, kind: str, **payload: Any) -> None:
        now = time.time()
        bounded = {"persona": self.persona, **payload}
        sink = self._receipt_sink
        if sink is not None:
            try:
                sink(kind, now, bounded)
            except Exception:
                # Observatory failure cannot alter lifecycle truth.
                pass

    def live_epoch(self) -> int:
        with self._meta_lock:
            return self._external_demand_epoch

    def start(
            self, run_id: str, runner: Runner, *,
            proposal_id: str = None,
            replace: bool = False) -> concurrent.futures.Future:
        run_id = str(run_id or "").strip()
        if not run_id:
            raise ValueError("agency run requires a run_id")
        if not callable(runner):
            raise TypeError("agency runner must be callable")
        with self._meta_lock:
            if self._closed:
                raise AgencyControllerClosed(
                    "persona agency controller is closed")
            loop = self._loop
        future = asyncio.run_coroutine_threadsafe(
            self._admit_and_run(
                run_id, proposal_id, runner, bool(replace)),
            loop)
        with self._meta_lock:
            self._futures.add(future)

        def finished(done):
            with self._meta_lock:
                self._futures.discard(done)

        future.add_done_callback(finished)
        return future

    async def _admit_and_run(
            self, run_id: str, proposal_id: str | None,
            runner: Runner, replace: bool):
        old_done = None
        old_id = None
        async with self._op_lock:
            with self._meta_lock:
                if self._closed:
                    raise AgencyControllerClosed(
                        "persona agency controller is closing")
                active = self._active
                pending = self._replacement_pending
                if active is not None:
                    if not replace or pending is not None:
                        self._emit(
                            "agency_refused", run_id=run_id,
                            proposal_id=proposal_id,
                            reason=("replacement_pending" if pending
                                    else "active_run"),
                            active_run_id=active.run_id,
                            external_demand_epoch=
                            self._external_demand_epoch)
                        raise ActiveAgencyRun(
                            f"persona {self.persona!r} already owns "
                            f"agency run {active.run_id!r}")
                    self._external_demand_epoch += 1
                    self._replacement_pending = run_id
                    active.cancellation_requested = True
                    old_done = active.done
                    old_id = active.run_id
                    reason = f"run_replaced:{run_id}"
                    active.cancellation.cancel(reason)
                    self._emit(
                        "agency_replaced", run_id=old_id,
                        replacement_run_id=run_id,
                        reason=reason,
                        external_demand_epoch=
                        self._external_demand_epoch)

        if old_done is not None:
            await old_done.wait()

        async with self._op_lock:
            with self._meta_lock:
                if self._closed:
                    if self._replacement_pending == run_id:
                        self._replacement_pending = None
                    raise AgencyControllerClosed(
                        "persona agency controller closed during replacement")
                if self._active is not None:
                    raise AgencyControllerError(
                        "active run remained after replacement teardown")
                captured_epoch = self._external_demand_epoch
                record = _ActiveRecord(
                    run_id=run_id,
                    proposal_id=proposal_id,
                    captured_epoch=captured_epoch,
                    cancellation=CancellationToken(),
                    started_at=time.time(),
                    done=asyncio.Event(),
                )
                self._active = record
                if self._replacement_pending == run_id:
                    self._replacement_pending = None

        return await self._run_record(record, runner)

    async def _run_record(self, record: _ActiveRecord, runner: Runner):
        task = asyncio.current_task()
        record.task = task
        record.status = "running"
        loop = asyncio.get_running_loop()
        unsubscribe = record.cancellation.subscribe(
            lambda _reason: loop.call_soon_threadsafe(task.cancel))
        self._emit(
            "agency_started", run_id=record.run_id,
            proposal_id=record.proposal_id,
            captured_epoch=record.captured_epoch,
            external_demand_epoch=self.live_epoch())
        terminal = None
        try:
            value = await runner(AgencyRunContext(
                persona=self.persona,
                run_id=record.run_id,
                proposal_id=record.proposal_id,
                captured_epoch=record.captured_epoch,
                cancellation=record.cancellation,
                live_epoch=self.live_epoch,
            ))
            outcome = (
                value if isinstance(value, AgencyRunOutcome)
                else AgencyRunOutcome(result=value))
            record.status = outcome.status
            terminal = {
                "run_id": record.run_id,
                "proposal_id": record.proposal_id,
                "status": outcome.status,
                "captured_epoch": record.captured_epoch,
                "external_demand_epoch": self.live_epoch(),
                "finished_at": time.time(),
                "metrics": _metrics(outcome.metrics),
            }
            self._emit(
                "agency_deferred"
                if outcome.status == "deferred"
                else "agency_completed",
                **terminal)
            return outcome
        except asyncio.CancelledError:
            record.status = "interrupted"
            terminal = {
                "run_id": record.run_id,
                "proposal_id": record.proposal_id,
                "status": "interrupted",
                "captured_epoch": record.captured_epoch,
                "external_demand_epoch": self.live_epoch(),
                "finished_at": time.time(),
                "reason": (record.cancellation.reason
                           or "async task cancelled"),
            }
            self._emit("agency_interrupted", **terminal)
            raise
        except Exception as exc:
            record.status = "failed"
            terminal = {
                "run_id": record.run_id,
                "proposal_id": record.proposal_id,
                "status": "failed",
                "captured_epoch": record.captured_epoch,
                "external_demand_epoch": self.live_epoch(),
                "finished_at": time.time(),
                "error_type": type(exc).__name__,
                "error": str(exc)[:240],
            }
            self._emit("agency_failed", **terminal)
            raise
        finally:
            unsubscribe()
            with self._meta_lock:
                if terminal is not None:
                    self._latest_terminal = dict(terminal)
                if self._active is record:
                    self._active = None
            record.done.set()

    def external_demand(
            self, reason: str, *, source: str = "human") -> dict:
        reason = str(reason or "").strip()
        source = str(source or "").strip()
        if not reason:
            raise ValueError("external demand requires a reason")
        if not source:
            raise ValueError("external demand requires a source")
        with self._meta_lock:
            self._external_demand_epoch += 1
            epoch = self._external_demand_epoch
            active = self._active
            cancelled = False
            if active is not None:
                active.cancellation_requested = True
                cancelled = active.cancellation.cancel(reason)
                run_id = active.run_id
            else:
                run_id = None
        if cancelled:
            self._emit(
                "agency_interruption_requested",
                run_id=run_id, reason=reason, source=source,
                external_demand_epoch=epoch)
        return {
            "external_demand_epoch": epoch,
            "active_run_id": run_id,
            "cancellation_requested": cancelled,
        }

    def status(self) -> dict:
        with self._meta_lock:
            active = self._active
            if active is None:
                active_view = None
            else:
                active_view = {
                    "run_id": active.run_id,
                    "proposal_id": active.proposal_id,
                    "captured_epoch": active.captured_epoch,
                    "status": active.status,
                    "started_at": active.started_at,
                    "cancellation_requested":
                        active.cancellation_requested,
                }
            return {
                "persona": self.persona,
                "external_demand_epoch": self._external_demand_epoch,
                "active": active_view,
                "replacement_pending": self._replacement_pending,
                "latest_terminal": (
                    dict(self._latest_terminal)
                    if self._latest_terminal is not None else None),
                "controller_open": (
                    not self._closed and self._thread.is_alive()),
            }

    def close(self) -> None:
        if threading.current_thread() is self._thread:
            raise RuntimeError(
                "agency controller cannot synchronously close its own loop")
        with self._meta_lock:
            if self._closed:
                return
            self._closed = True
        self.external_demand(
            "persona_process_stopping", source="shutdown")
        while True:
            with self._meta_lock:
                futures = tuple(self._futures)
            if not futures:
                break
            for future in futures:
                try:
                    future.result()
                except (Exception, asyncio.CancelledError):
                    pass
        loop = self._loop
        if loop is not None:
            loop.call_soon_threadsafe(loop.stop)
        self._thread.join()

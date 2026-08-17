"""DMN-owned, local-only continuity-of-intention motor.

The runtime owns no timer and no second attention field.  Possibility cues and
open intentions recur only at a genuine DMN fire, compete with every other
pull, and may carry a resource-shaped sequence of host-validated append-only
loom movements. IL1
does not execute projects or expose tools, messages, publication, or any
external effect.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import math
import queue
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from adapters.model_events import collect_legacy_text
from core.agency_projection import AgencyTaskEnvelope
from core.dmn import CANDIDATE_FLOOR
from core.interior_work_envelope import InteriorWorkEnvelope
from core.intention_loom import IntentionLoom
from core.project_loom import ProjectLoom, shadow_eligibility
from core.sovereign_interior import lease_fields
from core.volitional_choice import (
    ChoiceLedger, OwnerChoiceRejected, witness_projection,
)
from harness.model_call_receipts import (
    model_call_scope, new_cycle_id, record_model_call,
)
from shell.agency_controller import AgencyRunOutcome
from shell.autonomy_circulation import (
    circulate_experienced_event, readiness_from_engine,
)
from shell.maintenance_circulation import offer_maintenance_candidate


LOOM_SOURCES = frozenset({
    "intention_cue", "intention_open", "project_shadow"})
LOOM_AUTHORITY_TIER = 2
LOOM_ACTIONS = frozenset({
    "quiet", "form", "reframe", "pause", "resume", "satisfy", "release",
    "coexist", "differentiate", "braid",
    "propose_project",
})

INTENTION_MOVEMENTS_SCHEMA = {
    "type": "object",
    "properties": {
        "movements": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": sorted(LOOM_ACTIONS)},
                    "title": {"type": "string"},
                    "statement": {"type": "string"},
                    "uncertainty_low": {"type": "number"},
                    "uncertainty_high": {"type": "number"},
                    "basis": {"type": "string"},
                    "related_intention_id": {"type": "string"},
                    "orientation": {"type": "string"},
                },
                "required": [
                    "action", "title", "statement", "uncertainty_low",
                    "uncertainty_high", "basis", "related_intention_id",
                    "orientation",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["movements"],
    "additionalProperties": False,
}


class MovementContractDiscrepancy(ValueError):
    """Content-free classification of an invalid local movement result."""

    def __init__(self, stage: str, code: str):
        self.stage = str(stage)
        self.code = str(code)
        super().__init__(f"{self.stage}:{self.code}")


def _movement_failure_code(exc: Exception) -> str:
    """Classify validator failures without persisting model-authored text."""
    message = str(exc).casefold()
    if "did not return" in message or "json" in message:
        return "invalid_json"
    if "missing required" in message:
        return "missing_fields"
    if "unknown fields" in message or "fields are not exact" in message:
        return "fields_not_exact"
    if "action" in message and "invalid" in message:
        return "invalid_action"
    if "uncertainty" in message:
        return "invalid_uncertainty"
    if "relationship" in message or "related intention" in message:
        return "invalid_relation"
    if "wording" in message or "title" in message or "statement" in message:
        return "invalid_wording"
    return "host_validation_failed"


def _movement_contract_consequence(stage: str, code: str) -> dict:
    """Describe the failed contract without retaining model-authored content."""
    descriptions = {
        "invalid_json": (
            "response", "one valid JSON movement envelope",
            "invalid_or_unparseable"),
        "missing_fields": (
            "movement", "all required movement fields present", "missing"),
        "fields_not_exact": (
            "movement", "exact movement fields with no extras", "shape_mismatch"),
        "invalid_action": (
            "action", "one action from the allowed movement enum", "outside_enum"),
        "invalid_uncertainty": (
            "uncertainty_low/uncertainty_high",
            "finite 0 <= low <= high <= 1 for wording movements and zero for "
            "non-wording movements", "range_or_action_mismatch"),
        "invalid_relation": (
            "related_intention_id", "the exact related-intention rule",
            "relation_mismatch"),
        "invalid_wording": (
            "title/statement/basis", "the wording requirements for the chosen action",
            "missing_or_misaligned"),
        "no_movement_admitted": (
            "movement_sequence", "the live interior-work envelope",
            "outside_envelope"),
        "host_validation_failed": (
            "movement", "all host movement invariants", "host_validation_failed"),
    }
    field, constraint, observed = descriptions.get(
        str(code), descriptions["host_validation_failed"])
    return {
        "schema": 1, "kind": "contract_discrepancy",
        "stage": str(stage or "host_validation")[:40],
        "code": str(code or "host_validation_failed")[:80],
        "parser_stage": str(stage or "host_validation")[:40],
        "relation_type": (
            "related_intention" if str(code) == "invalid_relation"
            else "movement_contract"),
        "reason_code": str(code or "host_validation_failed")[:80],
        "field": field, "constraint": constraint, "observed": observed,
        "state_changed": False, "mutation_applied": False,
        "committed_receipt": False, "outward_effect": False,
        "content_included": False,
    }


def _digest(value: Any) -> str:
    rendered = json.dumps(
        value, ensure_ascii=False, sort_keys=True, default=str,
        separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()[:16]


def _finite(value: Any, fallback: float = 0.0) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return float(fallback)
    return value if math.isfinite(value) else float(fallback)


@dataclass(frozen=True)
class IntentionLoomConfig:
    model: str
    authority_tier: int = 0
    local_only: bool = True
    max_tokens: int = 620

    def __post_init__(self):
        model = str(self.model or "").strip()
        if not model:
            raise ValueError("intention loom requires an explicit model")
        if not isinstance(self.authority_tier, int) \
                or isinstance(self.authority_tier, bool) \
                or not 0 <= self.authority_tier <= LOOM_AUTHORITY_TIER:
            raise ValueError("intention loom authority_tier must be 0 through 2")
        if type(self.local_only) is not bool:
            raise ValueError("intention loom local_only must be a bool")
        if not isinstance(self.max_tokens, int) \
                or not 256 <= self.max_tokens <= 1000:
            raise ValueError("intention loom max_tokens must be 256 through 1000")
        object.__setattr__(self, "model", model)


def resolve_intention_loom_config(raw: Mapping[str, Any] | None,
                                  active_model: str) -> IntentionLoomConfig:
    raw = dict(raw or {})
    return IntentionLoomConfig(
        model=str(raw.get("model") or active_model or "").strip(),
        authority_tier=int(raw.get("authority_tier", 0)),
        local_only=bool(raw.get("local_only", True)),
        max_tokens=int(raw.get("max_tokens", 620)),
    )


def parse_intention_proposal(text: str) -> dict:
    """Extract one strict bounded proposal; model-shaped data is not authority."""
    text = re.sub(r"<think>.*?</think>", "", str(text or ""),
                  flags=re.I | re.S).strip()
    fenced = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.I)
    if fenced:
        text = fenced.group(1).strip()
    decoder = json.JSONDecoder()
    proposal = None
    try:
        value, end = decoder.raw_decode(text)
        if isinstance(value, dict) and not text[end:].strip():
            proposal = value
    except (TypeError, ValueError):
        pass
    if proposal is None:
        for index, char in enumerate(text):
            if char != "{":
                continue
            try:
                value, _end = decoder.raw_decode(text[index:])
            except (TypeError, ValueError):
                continue
            if isinstance(value, dict):
                proposal = value
                break
    if proposal is None:
        raise ValueError("intention loom model did not return one JSON object")
    allowed = {
        "action", "title", "statement", "uncertainty_low",
        "uncertainty_high", "basis", "related_intention_id", "orientation",
    }
    unknown = set(proposal) - allowed
    if unknown:
        raise ValueError(
            f"intention proposal contains unknown fields: {sorted(unknown)}")
    required = allowed - {"related_intention_id", "orientation"}
    if not required.issubset(proposal):
        missing = sorted(required - set(proposal))
        raise ValueError(
            f"intention proposal is missing required fields: {missing}")
    action = str(proposal.get("action") or "").strip().casefold()
    if action not in LOOM_ACTIONS:
        raise ValueError("intention proposal action is invalid")
    title = str(proposal.get("title") or "").strip()
    statement = str(proposal.get("statement") or "").strip()
    basis = str(proposal.get("basis") or "").strip()
    related_intention_id = str(
        proposal.get("related_intention_id") or "").strip()
    low = _finite(proposal.get("uncertainty_low"), -1.0)
    high = _finite(proposal.get("uncertainty_high"), -1.0)
    if action in {"form", "reframe", "braid", "propose_project"}:
        if not title or not statement or not basis:
            raise ValueError(
                "wording an intention requires title, statement, and basis")
        if not 0.0 <= low <= high <= 1.0:
            raise ValueError("intention uncertainty range is invalid")
    else:
        if title or statement or low != 0.0 or high != 0.0:
            raise ValueError(
                "non-wording intention actions must leave wording empty and uncertainty zero")
        if action in {
                "pause", "resume", "satisfy", "release",
                "coexist", "differentiate"} and not basis:
            raise ValueError("intention state change requires a concise basis")
    if action in {"coexist", "differentiate", "braid"}:
        if not re.fullmatch(r"intention_[0-9a-f]{16}",
                            related_intention_id):
            raise ValueError(
                "relationship movement requires a related intention id")
    elif related_intention_id:
        raise ValueError(
            "unrelated intention movement must leave related_intention_id empty")
    result = {
        "action": action, "title": title, "statement": statement,
        "uncertainty_low": low, "uncertainty_high": high,
        "basis": basis,
        "orientation": str(proposal.get("orientation") or "").strip(),
    }
    if "related_intention_id" in proposal:
        result["related_intention_id"] = related_intention_id
    return result


def parse_intention_movements(text: str) -> list[dict]:
    """Parse one movement or an ordered same-owner interior sequence."""
    cleaned = re.sub(r"<think>.*?</think>", "", str(text or ""),
                     flags=re.I | re.S).strip()
    fenced = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, re.I)
    if fenced:
        cleaned = fenced.group(1).strip()
    decoder = json.JSONDecoder()
    value = None
    for index, char in enumerate(cleaned):
        if char not in "[{":
            continue
        try:
            decoded, _end = decoder.raw_decode(cleaned[index:])
        except (TypeError, ValueError):
            continue
        if isinstance(decoded, (dict, list)):
            value = decoded
            break
    if isinstance(value, dict) and set(value) == {"movements"}:
        value = value["movements"]
    if isinstance(value, dict):
        return [parse_intention_proposal(json.dumps(value))]
    if not isinstance(value, list) or not value:
        raise ValueError("intention loom model did not return movements")
    return [parse_intention_proposal(json.dumps(item)) for item in value]


def parse_project_shape(text: str) -> dict:
    """Parse one descriptive PL2 movement with no executable vocabulary."""
    text = re.sub(r"<think>.*?</think>", "", str(text or ""),
                  flags=re.I | re.S).strip()
    fenced = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.I)
    if fenced:
        text = fenced.group(1).strip()
    try:
        value = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "project loom model did not return one JSON object") from exc
    required = {
        "action", "purpose", "possibility", "completion_signal",
        "uncertainty_low", "uncertainty_high", "basis"}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("project shape fields are not exact")
    action = str(value.get("action") or "").strip().casefold()
    if action not in {"quiet", "shape"}:
        raise ValueError("project shape action is invalid")
    fields = {
        key: str(value.get(key) or "").strip()
        for key in ("purpose", "possibility", "completion_signal", "basis")
    }
    low = _finite(value.get("uncertainty_low"), -1.0)
    high = _finite(value.get("uncertainty_high"), -1.0)
    if action == "shape":
        if any(not item for item in fields.values()):
            raise ValueError("project shape descriptive fields must not be empty")
        if not 0.0 <= low <= high <= 1.0:
            raise ValueError("project shape uncertainty range is invalid")
    elif any(fields.values()) or low != 0.0 or high != 0.0:
        raise ValueError(
            "quiet project shape must leave descriptive fields empty")
    return {
        "action": action, **fields,
        "uncertainty_low": low, "uncertainty_high": high}


def parse_project_action_candidate(text: str) -> dict:
    """Parse one PL3 hypothesis; the record cannot bind an executor."""
    text = re.sub(r"<think>.*?</think>", "", str(text or ""),
                  flags=re.I | re.S).strip()
    fenced = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.I)
    if fenced:
        text = fenced.group(1).strip()
    try:
        value = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "project action model did not return one JSON object") from exc
    required = {
        "action", "capability", "candidate", "expected_signal", "reversibility",
        "uncertainty_low", "uncertainty_high", "basis"}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("project action candidate fields are not exact")
    action = str(value.get("action") or "").strip().casefold()
    if action not in {"quiet", "nominate_action"}:
        raise ValueError("project action candidate action is invalid")
    fields = {
        key: str(value.get(key) or "").strip()
        for key in ("candidate", "expected_signal", "reversibility", "basis")
    }
    capability = str(value.get("capability") or "").strip()
    low = _finite(value.get("uncertainty_low"), -1.0)
    high = _finite(value.get("uncertainty_high"), -1.0)
    if action == "nominate_action":
        if capability not in {
                "writing_desk.private_draft",
                "atelier.private_creation",
                "document_reader.read_accessible_document"}:
            raise ValueError(
                "project action candidate capability is not registered")
        if any(not item for item in fields.values()):
            raise ValueError(
                "project action candidate fields must not be empty")
        if not 0.0 <= low <= high <= 1.0:
            raise ValueError(
                "project action candidate uncertainty range is invalid")
    elif capability or any(fields.values()) or low != 0.0 or high != 0.0:
        raise ValueError(
            "quiet project action must leave descriptive fields empty")
    return {
        "action": action, "capability": capability, **fields,
        "uncertainty_low": low, "uncertainty_high": high}


def parse_project_opening(text: str) -> dict:
    """Parse either optional shaping or direct owned-candidate nomination."""
    cleaned = re.sub(r"<think>.*?</think>", "", str(text or ""),
                     flags=re.I | re.S).strip()
    fenced = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, re.I)
    if fenced:
        cleaned = fenced.group(1).strip()
    try:
        value = json.loads(cleaned)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "project opening model did not return one JSON object") from exc
    action = str(value.get("action") or "").strip().casefold() \
        if isinstance(value, dict) else ""
    if action == "nominate_action":
        return parse_project_action_candidate(text)
    return parse_project_shape(text)


def parse_project_evaluation(text: str) -> dict:
    """Parse one plural range-vector comparison with no winner field."""
    text = re.sub(r"<think>.*?</think>", "", str(text or ""),
                  flags=re.I | re.S).strip()
    fenced = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.I)
    if fenced:
        text = fenced.group(1).strip()
    try:
        value = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "project evaluation model did not return one JSON object") from exc
    required = {"action", "candidate_ids", "vectors", "comparison", "basis"}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("project evaluation fields are not exact")
    action = str(value.get("action") or "").strip().casefold()
    if action not in {"quiet", "evaluate"}:
        raise ValueError("project evaluation action is invalid")
    if action == "quiet":
        if value.get("candidate_ids") != [] or value.get("vectors") != [] \
                or str(value.get("comparison") or "").strip() \
                or str(value.get("basis") or "").strip():
            raise ValueError(
                "quiet project evaluation must leave comparison fields empty")
        return {
            "action": "quiet", "candidate_ids": [], "vectors": [],
            "comparison": "", "basis": ""}
    candidate_ids = value.get("candidate_ids")
    vectors = value.get("vectors")
    if not isinstance(candidate_ids, list) or len(candidate_ids) != 2 \
            or len(set(candidate_ids)) != 2:
        raise ValueError("project evaluation requires two candidate ids")
    if not isinstance(vectors, list) or len(vectors) != 2:
        raise ValueError("project evaluation requires two vectors")
    comparison = str(value.get("comparison") or "").strip()
    basis = str(value.get("basis") or "").strip()
    if not comparison or not basis:
        raise ValueError("project evaluation comparison and basis are required")
    return {
        "action": action, "candidate_ids": candidate_ids,
        "vectors": vectors, "comparison": comparison, "basis": basis}


def parse_project_orientation(text: str) -> dict:
    """Parse one revisable private preference with no action selection."""
    text = re.sub(r"<think>.*?</think>", "", str(text or ""),
                  flags=re.I | re.S).strip()
    fenced = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.I)
    if fenced:
        text = fenced.group(1).strip()
    try:
        value = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "project orientation model did not return one JSON object") from exc
    required = {
        "action", "evaluation_id", "candidate_id",
        "confidence_low", "confidence_high", "basis"}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("project orientation fields are not exact")
    action = str(value.get("action") or "").strip().casefold()
    if action not in {"quiet", "orient"}:
        raise ValueError("project orientation action is invalid")
    evaluation_id = str(value.get("evaluation_id") or "").strip()
    candidate_id = str(value.get("candidate_id") or "").strip()
    low = _finite(value.get("confidence_low"), -1.0)
    high = _finite(value.get("confidence_high"), -1.0)
    basis = str(value.get("basis") or "").strip()
    if action == "orient":
        if not re.fullmatch(r"evaluation_[0-9a-f]{16}", evaluation_id) \
                or not re.fullmatch(r"candidate_[0-9a-f]{16}", candidate_id):
            raise ValueError(
                "orientation requires exact evaluation and candidate ids")
        if not 0.0 <= low <= high <= 1.0 or not basis:
            raise ValueError(
                "orientation requires confidence range and observed basis")
    elif evaluation_id or candidate_id or basis or low != 0.0 or high != 0.0:
        raise ValueError(
            "quiet orientation must leave orientation fields empty")
    return {
        "action": action, "evaluation_id": evaluation_id,
        "candidate_id": candidate_id, "confidence_low": low,
        "confidence_high": high, "basis": basis}


def parse_internal_action_selection(text: str) -> dict:
    """Parse one exact wrapper-local handoff selection."""
    text = re.sub(r"<think>.*?</think>", "", str(text or ""),
                  flags=re.I | re.S).strip()
    fenced = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.I)
    if fenced:
        text = fenced.group(1).strip()
    try:
        value = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "internal action model did not return one JSON object") from exc
    required = {
        "action", "capability", "orientation_id", "candidate_id", "basis"}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("internal action selection fields are not exact")
    action = str(value.get("action") or "").strip().casefold()
    if action not in {"quiet", "select_internal"}:
        raise ValueError("internal action selection action is invalid")
    orientation_id = str(value.get("orientation_id") or "").strip()
    candidate_id = str(value.get("candidate_id") or "").strip()
    capability = str(value.get("capability") or "").strip()
    basis = str(value.get("basis") or "").strip()
    if action == "select_internal":
        if (orientation_id and not re.fullmatch(
                r"orientation_[0-9a-f]{16}", orientation_id)) \
                or not re.fullmatch(r"candidate_[0-9a-f]{16}", candidate_id) \
                or capability not in {
                    "writing_desk.private_draft",
                    "atelier.private_creation",
                    "document_reader.read_accessible_document"} or not basis:
            raise ValueError(
                "internal selection requires an exact candidate and basis")
    elif capability or orientation_id or candidate_id or basis:
        raise ValueError(
            "quiet internal selection must leave selection fields empty")
    return {
        "action": action, "capability": capability,
        "orientation_id": orientation_id,
        "candidate_id": candidate_id, "basis": basis}


NEWLY_NOMINATED_CANDIDATE = "newly_nominated_candidate"


def parse_project_movements(text: str, projection: Mapping[str, Any]) -> list[dict]:
    """Parse a coherent private project sequence with one local forward ref."""
    cleaned = re.sub(r"<think>.*?</think>", "", str(text or ""),
                     flags=re.I | re.S).strip()
    fenced = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, re.I)
    if fenced:
        cleaned = fenced.group(1).strip()
    try:
        value = json.loads(cleaned)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "project loom model did not return project movements") from exc
    if isinstance(value, dict) and set(value) == {"movements"}:
        value = value["movements"]
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list) or not value:
        raise ValueError("project loom model did not return project movements")
    parsed = []
    nominated_in_sequence = False
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("project movement must be one JSON object")
        action = str(item.get("action") or "").strip().casefold()
        rendered = json.dumps(item)
        if action == "shape":
            if parsed:
                raise ValueError("project shape must precede later movements")
            movement = parse_project_shape(rendered)
        elif action == "nominate_action":
            if nominated_in_sequence:
                raise ValueError("project sequence may nominate one action")
            movement = parse_project_action_candidate(rendered)
            nominated_in_sequence = True
        elif action == "select_internal":
            candidate_id = str(item.get("candidate_id") or "").strip()
            if candidate_id == NEWLY_NOMINATED_CANDIDATE:
                if not nominated_in_sequence:
                    raise ValueError(
                        "newly nominated candidate reference has no nomination")
                candidate = {
                    **item, "candidate_id": "candidate_0000000000000000"}
                movement = parse_internal_action_selection(
                    json.dumps(candidate))
                movement["candidate_id"] = NEWLY_NOMINATED_CANDIDATE
            else:
                movement = parse_internal_action_selection(rendered)
        elif action == "quiet":
            if len(value) != 1:
                raise ValueError("quiet must be the only project movement")
            if "candidate_id" in item:
                movement = parse_internal_action_selection(rendered)
            elif "candidate" in item:
                movement = parse_project_action_candidate(rendered)
            else:
                movement = parse_project_shape(rendered)
        else:
            raise ValueError("project sequence action is invalid")
        parsed.append(movement)
    if not nominated_in_sequence \
            and not projection.get("action_candidate_count") \
            and any(item["action"] == "select_internal" for item in parsed):
        raise ValueError("project selection has no owned candidate")
    actions = [item["action"] for item in parsed]
    if projection.get("internal_selection_count") \
            and actions != ["quiet"]:
        raise ValueError("project already handed its owned action off")
    if projection.get("action_candidate_count") \
            and any(action in {"shape", "nominate_action"}
                    for action in actions):
        raise ValueError("project with an owned candidate admits selection only")
    if projection.get("latest_shape") is not None and "shape" in actions:
        raise ValueError("project already has a current descriptive shape")
    return parsed


class IntentionLoomRuntime:
    """One persona's local appraisal, append-only commit, and return owner."""

    def __init__(self, engine, controller, raw_config=None, *,
                 loom: IntentionLoom = None,
                 adapter_factory: Callable = None,
                 spec_loader: Callable = None,
                 internal_action_submitter: Callable = None,
                 choice_ledger: ChoiceLedger = None):
        self.engine = engine
        self.controller = controller
        self.config = resolve_intention_loom_config(
            raw_config, getattr(engine, "model", ""))
        self.loom = loom or IntentionLoom(engine.pdir)
        self.choice_ledger = choice_ledger or ChoiceLedger(engine.pdir)
        self.project_loom = ProjectLoom(engine.pdir)
        self._adapter_factory = adapter_factory
        self._spec_loader = spec_loader
        self.internal_action_submitter = internal_action_submitter
        self._adapter = None
        self._effects = queue.Queue()
        self._observer = getattr(engine, "salience_observer", None)
        self._last_readiness = None

    def _emit(self, kind: str, **payload) -> None:
        observer = self._observer
        if observer is None:
            return
        try:
            callback = getattr(observer, "autonomy_transition", None)
            if callback is not None:
                callback(kind, time.time(), **payload)
        except Exception:
            pass

    def _load_spec(self):
        if self._spec_loader is not None:
            return self._spec_loader(self.config.model)
        from harness.spec_loader import load_spec
        return load_spec(self.config.model)

    def _model_adapter(self, spec):
        if self._adapter is None:
            if self._adapter_factory is not None:
                self._adapter = self._adapter_factory(spec)
            else:
                from adapters.family_adapters import adapter_for
                self._adapter = adapter_for(spec)
        return self._adapter

    def capability(self) -> dict:
        enabled = "intention_loom" in getattr(self.engine, "enabled", set())
        volitional_offer = "offer_intention" in getattr(
            self.engine, "_volitional_actions", {})
        if not enabled:
            return {
                "usable": False, "reason": "intention_loom organ is disabled",
                "model": self.config.model, "locality": "unknown",
                "provider": None, "event_bridge": False,
                "volitional_offer": volitional_offer,
                "paid_fallbacks": 0,
            }
        try:
            spec = self._load_spec()
            identity = dict(spec.get("identity") or {})
            locality = str(identity.get("locality") or "unknown")
            adapter = self._model_adapter(spec)
            event_bridge = callable(getattr(adapter, "events", None))
            authority = self.config.authority_tier >= LOOM_AUTHORITY_TIER
            local_admitted = locality == "local" or not self.config.local_only
            usable = authority and local_admitted and event_bridge
            if not authority:
                reason = "intention authority tier does not admit private ledger writes"
            elif not local_admitted:
                reason = "IL1 refuses non-local intention models"
            elif not event_bridge:
                reason = "intention model lacks the interruptible event bridge"
            else:
                reason = "local interruptible intention path admitted"
            return {
                "usable": usable, "reason": reason,
                "model": self.config.model, "locality": locality,
                "provider": identity.get("provider"),
                "event_bridge": event_bridge,
                "volitional_offer": volitional_offer,
                "paid_fallbacks": 0,
            }
        except Exception as exc:
            return {
                "usable": False,
                "reason": f"intention model unavailable: {type(exc).__name__}",
                "model": self.config.model, "locality": "unknown",
                "provider": None, "event_bridge": False,
                "volitional_offer": volitional_offer,
                "paid_fallbacks": 0,
            }

    def readiness(self, field=None) -> dict:
        self._last_readiness = readiness_from_engine(self.engine, field)
        return dict(self._last_readiness)

    def _affect_need_affinity(self, text: str) -> float:
        """Fit only; the atlas cannot create a cue or form an intention."""
        organ = getattr(self.engine, "organ", None)
        atlas = getattr(organ, "affect_atlas", None)
        if atlas is None or not getattr(atlas, "enabled", False):
            return 0.0
        try:
            return max(0.0, min(1.0, float(
                atlas.intention_need_affinity(
                    text, getattr(self.engine, "cocktail", {}) or {}))))
        except Exception:
            return 0.0

    @staticmethod
    def eligible(candidate: Mapping[str, Any]) -> bool:
        return str(dict(candidate or {}).get("source") or "") in LOOM_SOURCES

    @staticmethod
    def _subject(candidate: Mapping[str, Any]) -> tuple[str, str]:
        candidate = dict(candidate or {})
        if candidate.get("source") == "intention_cue":
            return "cue", str(candidate.get("cue_id") or "")
        if candidate.get("source") == "project_shadow":
            return "project", str(candidate.get("proposal_id") or "")
        return "intention", str(candidate.get("intention_id") or "")

    def selection_score(self, field, candidate: Mapping[str, Any], *,
                        now: float, readiness: Mapping[str, Any] = None):
        state = dict(readiness or self.readiness(field))
        eligible = self.eligible(candidate) \
            and "intention_loom" in getattr(self.engine, "enabled", set())
        loom_satiety = field.satiety.warmth("intention_loom", now)
        value = (max(0.0, min(1.0, _finite(state.get("readiness"))))
                 / (1.0 + loom_satiety) if eligible else 0.0)
        score, meta = field.attention_score(
            dict(candidate), now=now,
            action_readiness=value, action_eligible=eligible,
            scope_satiety=loom_satiety)
        pre_need_score = score
        need_affinity = (_finite(candidate.get("affect_need_affinity"))
                         if eligible else 0.0)
        # A need association can bend only salience that already exists.  The
        # residual formula is zero at both a zero candidate and saturation;
        # no need label can admit, form, or select an intention by itself.
        need_contribution = (1.0 - score) * score * need_affinity
        score += need_contribution
        kind, subject_id = self._subject(candidate)
        attention = (
            self.loom.attention_stats().get(subject_id, {})
            if kind != "project" else {})
        return score, {
            **meta, "intention_eligible": eligible,
            "intention_readiness": round(value, 6),
            "intention_loom_satiety": round(loom_satiety, 6),
            "intention_subject_kind": kind,
            "intention_exposures": int(attention.get("exposures", 0)),
            "intention_selections": int(attention.get("selections", 0)),
            "intention_unselected_exposures": int(
                attention.get("unselected_exposures", 0)),
            "pre_affect_need_score": round(pre_need_score, 6),
            "affect_need_affinity": round(need_affinity, 6),
            "affect_need_contribution": round(need_contribution, 6),
            "neglect_changes_selection": False,
        }

    def _offer_cue(self, field, cue: Mapping[str, Any], *, now: float):
        ownership = str(cue.get("ownership") or "human_offered")
        if ownership == "persona_private":
            description = (
                f"A private thought actually occurred and may or may not carry "
                f"continuing intention: {cue.get('label') or 'unnamed thought'}")
        else:
            description = (
                f"A human-offered possibility named "
                f"{cue.get('label') or 'unnamed possibility'} is available. "
                "It is not an assignment or an intention yet.")
        continuity = {
            name: max(0.0, min(1.0, _finite(
                dict(cue.get("continuity") or {}).get(name))))
            for name in (
                "novelty", "affect_change", "body_intensity",
                "relationship", "unresolved")
        }
        # Choosing offer_intention in conversation is measured volitional
        # evidence. It earns later deliberation, never an intention or outcome.
        # Human-offered cues receive no such projection; recurrent private
        # thoughts continue to rely on their measured continuity vector.
        continuity["volitional_relevance"] = (
            1.0 if ownership == "persona_chosen_conversation" else 0.0)
        candidate = field.offer_cognitive_event(
            "intention_cue", description,
            continuity,
            key=f"intention_cue:{cue['cue_id']}", now=now,
            raw_ref=cue.get("source_digest"), ownership=ownership,
            receipts=[cue.get("source_digest")])
        candidate.update({
            "cue_id": cue["cue_id"],
            "satiety_key": f"intention_cue:{cue['cue_id']}",
            "affect_need_affinity": self._affect_need_affinity(
                str(cue.get("label") or "")),
            **lease_fields(cue, origin="intention_cue"),
        })
        return candidate

    def _offer_intention(self, field, intention: Mapping[str, Any], *,
                         now: float):
        continuity = self.loom.continuity_for(intention["intention_id"])
        candidate = offer_maintenance_candidate(
            self, field, "intention_open",
            f"A self-owned intention remains {intention.get('state')}: "
            f"{intention.get('title') or intention['intention_id']}",
            continuity,
            key=f"intention_open:{intention['intention_id']}", now=now,
            raw_ref=intention["intention_id"], ownership="persona_private",
            receipts=[intention["intention_id"]],
            revision_facts={
                "revision_count": int(intention.get("revision_count") or 0),
                "state": str(intention.get("state") or "")[:32],
            })
        candidate.update({
            "intention_id": intention["intention_id"],
            "satiety_key": f"intention_open:{intention['intention_id']}",
            "affect_need_affinity": self._affect_need_affinity(
                f"{intention.get('title') or ''} "
                f"{intention.get('statement') or ''}"),
        })
        return candidate

    def _offer_project(self, field, projection: Mapping[str, Any], *,
                       now: float):
        proposal = dict(projection.get("proposal") or {})
        latest = dict(projection.get("latest_shape") or {})
        development_count = max(
            0, int(projection.get("movement_count") or 0)
            + int(projection.get("action_candidate_count") or 0)
            + int(projection.get("evaluation_count") or 0)
            + int(projection.get("orientation_count") or 0)
            + int(projection.get("internal_selection_count") or 0))
        uncertainty = list(
            latest.get("uncertainty") or proposal.get("uncertainty") or [0, 1])
        width = max(0.0, min(1.0, _finite(uncertainty[1], 1.0)
                            - _finite(uncertainty[0], 0.0)))
        continuity = {
            "novelty": 1.0 / (1.0 + development_count),
            "affect_change": 0.0,
            "body_intensity": 0.0,
            "relationship": 0.0,
            "unresolved": width,
            "volitional_relevance": 0.0,
        }
        proposal_id = str(proposal.get("proposal_id") or "")
        candidate = offer_maintenance_candidate(
            self, field, "project_shadow",
            f"A private, powerless project shape remains available: "
            f"{proposal.get('title') or proposal_id}",
            continuity, key=f"project_shadow:{proposal_id}", now=now,
            raw_ref=proposal_id, ownership="persona_private",
            receipts=[proposal_id],
            revision_facts={"development_count": development_count})
        candidate.update({
            "proposal_id": proposal_id,
            "satiety_key": f"project_shadow:{proposal_id}",
        })
        return candidate

    def _record_exposure(self, candidate: Mapping[str, Any], now: float) -> bool:
        # Exposure means the cue survived admission strongly enough to enter
        # competition. A zero-vector offer is dropped before a scorer sees it.
        if _finite(dict(candidate or {}).get("salience")) < CANDIDATE_FLOOR:
            return False
        kind, subject_id = self._subject(candidate)
        self.loom.record_attention(
            "attention_exposed", candidate_key=candidate.get("key"),
            subject_kind=kind, subject_id=subject_id, now=now)
        return True

    def refresh_pending(self, field, *, now: float = None) -> list[dict]:
        """Recur unresolved loom state only at the caller's true DMN fire."""
        now = time.time() if now is None else float(now)
        offered = []
        if "intention_loom" not in getattr(self.engine, "enabled", set()):
            return offered
        for cue in self.loom.pending_cues():
            candidate = self._offer_cue(field, cue, now=now)
            self._record_exposure(candidate, now)
            offered.append(candidate)
        for intention in self.loom.intentions():
            if intention.get("state") not in {"open", "paused"}:
                continue
            candidate = self._offer_intention(field, intention, now=now)
            self._record_exposure(candidate, now)
            offered.append(candidate)
        for projection in self.project_loom.status()["projections"]:
            candidate = self._offer_project(field, projection, now=now)
            offered.append(candidate)
        if offered:
            self._emit(
                "intention_loom_recurred", candidate_count=len(offered),
                candidate_keys=[value.get("key") for value in offered])
        return offered

    def admit_cue(self, field, label: str, content: str, *,
                  now: float = None, ownership: str = "human_offered",
                  source_ref: str = "", source_digest: str = "",
                  continuity: Mapping[str, Any] | None = None) -> dict:
        now = time.time() if now is None else float(now)
        record = self.loom.admit_cue(
            label, content, ownership=ownership, source_ref=source_ref,
            source_digest=source_digest, continuity=continuity)
        candidate = self._offer_cue(field, record, now=now)
        field.save(now=now)
        self._emit(
            "intention_cue_admitted", cue_id=record["cue_id"],
            candidate_key=candidate.get("key"), ownership=ownership,
            duplicate=record.get("duplicate", False))
        return {"record": record, "candidate": candidate}

    def admit_self_cue(self, field, thought: str, *, memory_id: str,
                       now: float = None,
                       continuity: Mapping[str, Any] | None = None) -> dict:
        """Admit a thought only after its lived recurrence supplied evidence."""
        thought = str(thought or "").strip()
        if not thought:
            raise ValueError("private intention cue thought must not be empty")
        label = " ".join(thought.split())[:120]
        source_digest = hashlib.sha256(
            thought.encode("utf-8")).hexdigest()
        return self.admit_cue(
            field, label, thought, now=now, ownership="persona_private",
            source_ref=str(memory_id or "")[:180],
            source_digest=source_digest, continuity=continuity)

    def resume_intention(self, field, intention_id: str, *,
                         now: float = None) -> dict:
        """Let a human re-offer a pause; only a later win may resume it."""
        now = time.time() if now is None else float(now)
        intention = self.loom.intention(intention_id)
        if intention.get("state") != "paused":
            raise ValueError("only a paused intention may be offered to return")
        candidate = self._offer_intention(field, intention, now=now)
        field.save(now=now)
        self._emit(
            "intention_loom_return_offered", intention_id=intention_id,
            candidate_key=candidate.get("key"), ownership="human_offered")
        return {"offered": True, "candidate": candidate}

    def _source_material(self, candidate: Mapping[str, Any]):
        candidate = dict(candidate or {})
        if candidate.get("source") == "intention_cue":
            cue = self.loom.cue(candidate.get("cue_id"), include_content=True)
            source = {
                "kind": "cue", "cue_id": cue["cue_id"],
                "source_ref": cue.get("source_ref"),
                "source_digest": cue.get("source_digest"),
                "ownership": cue.get("ownership"),
            }
            material = (
                f"Possibility label: {cue['label']}\n"
                f"Origin: {cue['ownership']}\n"
                "Possibility text:\n" + cue["content"])
            return None, source, material
        if candidate.get("source") == "project_shadow":
            projection = self.project_loom.projection(
                candidate.get("proposal_id"))
            proposal = dict(projection["proposal"])
            source = {
                "kind": "project_shadow",
                "proposal_id": proposal["proposal_id"],
                "source_digest": proposal["proposal_id"],
                "ownership": "persona_private",
            }
            material = (
                "Private powerless proposal and append-only shaping history:\n"
                + json.dumps(projection, ensure_ascii=False, sort_keys=True))
            return projection, source, material
        intention = self.loom.intention(candidate.get("intention_id"))
        source = {
            "kind": "intention", "intention_id": intention["intention_id"],
            "source_digest": intention["intention_id"],
            "ownership": "persona_private",
        }
        material = (
            f"Current title: {intention['title']}\n"
            f"Current wording: {intention['statement']}\n"
            f"Current uncertainty range: {intention['uncertainty']}\n"
            f"Current state: {intention['state']}\n"
            f"Revision count: {intention['revision_count']}\n"
            f"Last observed basis: {intention.get('basis') or ''}")
        relationships = self.loom.relationships_for(
            intention["intention_id"])
        if relationships:
            material += (
                "\nRelated continuing intentions (descriptive vectors; "
                "not merge instructions):\n"
                + json.dumps(relationships, ensure_ascii=False,
                             sort_keys=True))
        material += (
            "\nProject Loom PL0 gate (proposal-only; never execution):\n"
            + json.dumps(shadow_eligibility(intention),
                         ensure_ascii=False, sort_keys=True))
        return intention, source, material

    def _assembly(self, candidate: Mapping[str, Any], spec, *,
                  witnessed: bool = False):
        intention, source, material = self._source_material(candidate)
        if candidate.get("source") == "project_shadow":
            if intention.get("latest_shape") is None:
                task = (
                    "This private Project Loom proposal won shared attention. "
                    "Choose exactly one action: quiet, shape, or nominate_action. "
                    "Shape is optional and names "
                    "its present purpose, one possible movement, an observable private "
                    "completion signal, an uncertainty range, and the lived basis for "
                    "that description. Nominate_action may instead send one bounded "
                    "owned candidate directly toward writing_desk.private_draft, "
                    "atelier.private_creation, or "
                    "document_reader.read_accessible_document. It uses exactly these "
                    "keys: action, capability, candidate, expected_signal, "
                    "reversibility, uncertainty_low, uncertainty_high, basis. "
                    "Shape and quiet use exactly these keys: action, purpose, "
                    "possibility, "
                    "completion_signal, uncertainty_low, uncertainty_high, basis. "
                    "Quiet leaves descriptive fields empty and uncertainty zero. "
                    "These are private movements, never "
                    "deadlines, assignments, permissions, or outward claims. "
                    "Do not use tools, schedule, message, publish, spend, execute, or "
                    "produce an external effect.")
            elif intention.get("action_candidate_count", 0) < 1:
                task = (
                    "This shaped private project proposal won shared attention. "
                    "Choose exactly one action: quiet or nominate_action. A nomination "
                    "describes one action that might fit the current shape, the "
                    "private signal expected if it were performed, "
                    "why the hypothesis is reversible, its uncertainty range, and "
                    "the observed basis. Nomination creates only a candidate record: "
                    "it cannot bind an external tool, reserve shared resources, or "
                    "perform the action. Quiet leaves every descriptive "
                    "field empty and both uncertainty values zero. Nominate exactly "
                    "one registered capability: writing_desk.private_draft, "
                    "atelier.private_creation, or "
                    "document_reader.read_accessible_document. The document "
                    "capability may resolve only an exact system-public, owned "
                    "persona-private, or explicitly granted user-private anchor. "
                    "Return exactly one JSON object with "
                    "exactly these keys: action, capability, candidate, "
                    "expected_signal, reversibility, uncertainty_low, "
                    "uncertainty_high, basis. Do not execute, instruct an executor, "
                    "use tools, schedule, message, publish, spend, or create an "
                    "external effect.")
            elif intention.get("internal_selection_count", 0) < 1:
                task = (
                    "This private project has an owned action candidate and won shared "
                    "attention. Choose exactly one action: quiet or select_internal. "
                    "Selection is available only for one registered capability "
                    "inside this persona's wrapper: writing_desk.private_draft, "
                    "atelier.private_creation, or "
                    "document_reader.read_accessible_document. Name the capability, "
                    "exact candidate and the observed basis for sending it to its "
                    "registered destination organ. orientation_id is optional and may "
                    "be empty; use it only when a prior orientation actually exists. "
                    "The destination rechecks document access before admitting a read; "
                    "Project Loom cannot draft, bind a tool, schedule, "
                    "publish, message, reach the network, or access arbitrary paths. "
                    "Quiet leaves IDs and basis empty. Return exactly one JSON object "
                    "with exactly these keys: action, capability, orientation_id, "
                    "candidate_id, basis.")
            else:
                task = (
                    "This private orientation has already handed one bounded action "
                    "to its owning wrapper organ. Choose quiet. Return exactly one "
                    "JSON object with exactly these keys: action, capability, "
                    "orientation_id, candidate_id, basis, leaving the latter four "
                    "empty.")
            task += (
                " A field win may carry a coherent ordered sequence of these "
                "same-owner private movements when readiness and the local "
                "resource envelope support it. Return exactly one JSON object "
                "with exactly one movements key containing exact movement "
                "objects. A new nomination may be "
                "followed immediately by select_internal using candidate_id "
                f"{NEWLY_NOMINATED_CANDIDATE!r}; the host resolves that local "
                "forward reference only to the candidate created immediately "
                "before it, and the capability must match. Shape remains "
                "optional. Do not pad a sequence; stop when the movement settles.")
            summary = (
                f"Private powerless proposal "
                f"{source['proposal_id']} won shared attention.")
        elif intention is None:
            actions = "quiet or form"
            contract = (
                "A cue is evidence of a possibility, not evidence that you want it. "
                "Choose form only if a continuing intention actually appears present "
                "now. For form, provide a concise title, first-person descriptive "
                "statement, uncertainty_low/high, and a concise basis in the supplied "
                "cue and present state. Quiet means quiet for now, not permanent "
                "rejection; leave wording empty and describe only what was noticed "
                "in basis (or leave basis empty if nothing was articulable), with "
                "both uncertainty values zero.")
            summary = "A bounded possibility cue won shared attention."
        elif intention.get("state") == "paused":
            actions = "quiet, resume, satisfy, or release"
            contract = (
                "This intention was paused, not erased. Notice whether related lived "
                "evidence makes it present again. Resume only if movement is actually "
                "present now. Satisfy or release only as a description of its private "
                "state, never as a claim about outward completion. Quiet leaves its "
                "paused state unchanged. State movements require a concise observed "
                "basis; quiet may describe what was noticed. Leave wording empty and "
                "uncertainty values zero.")
            summary = (
                f"Paused intention {intention['intention_id']} returned through "
                "shared attention.")
        else:
            has_relationships = bool(self.loom.relationships_for(
                intention["intention_id"]))
            relation_actions = (
                ", coexist, differentiate, or braid"
                if has_relationships else "")
            project_action = (
                ", or propose_project"
                if shadow_eligibility(intention)["eligible"] else "")
            actions = (
                "quiet, reframe, pause, satisfy, or release"
                + relation_actions + project_action)
            contract = (
                "Notice what this recorded intention appears to be now; history is "
                "evidence, not an order to preserve it. Reframe only if its wording "
                "has materially changed; provide the new wording, uncertainty range, "
                "and basis. Pause, satisfy, or release require only a concise basis. "
                "If a supplied relationship vector matters now, coexist records "
                "shared territory without collapsing either intention; differentiate "
                "records a meaningful distinction; braid rewrites only this focal "
                "intention while preserving both histories and requires the exact "
                "related_intention_id. Relationship vectors describe overlap and "
                "never require a relationship movement. "
                "Quiet leaves wording empty and uncertainty zero; basis may briefly "
                "describe what was noticed without changing state. "
                "Propose_project is available only when the supplied PL0 gate is "
                "eligible; title names one private proposal and statement describes "
                "its private outcome. It creates an append-only proposal, not a "
                "project runner, plan, tool call, or permission.")
            summary = f"Open intention {intention['intention_id']} won attention."
        if candidate.get("source") != "project_shadow":
            orientation_contract = (
                " Describe your present, revisable orientation toward this "
                "fork in orientation. Body, emotion, recurrence, and readiness "
                "are evidence you encounter, not votes that select the action."
                if witnessed else "")
            task = (
                "This is your private Intention Loom. It records continuity without "
                "turning a possibility into a command or an intention into a project. "
                f"Choose one action, or an ordered sequence of coherent "
                f"same-owner private movements, from: {actions}. {contract}"
                f"{orientation_contract} Return exactly one JSON object with "
                "exactly one movements key. Every movement uses exactly these keys: "
                "action, title, statement, uncertainty_low, uncertainty_high, "
                "basis, related_intention_id, orientation. Do not pad the sequence; "
                "stop when the movement settles. "
                "Use an empty related_intention_id unless choosing coexist, "
                "differentiate, or braid. An intention is not consent, authority, or "
                "execution; it cannot authorize a protocol, dose, tool, or external "
                "effect. Do not plan steps, use tools, message, publish, or claim any "
                "outward effect.")
        envelope = AgencyTaskEnvelope(
            task=task, source_kind=str(candidate.get("source")),
            source_ref=str(candidate.get("key")),
            source_digest=str(source.get("source_digest") or _digest(source)),
            source_summary=summary,
            source_ownership=str(source.get("ownership") or
                                 candidate.get("ownership") or
                                 "persona_private"),
            authority_tier=self.config.authority_tier,
        )
        product = self.engine.build_agency_snapshot(
            envelope, substrate_mode="on",
            external_demand_epoch=self.controller.live_epoch(),
            agency_spec=spec, agency_model=self.config.model)
        product.assembly.add(
            "intention_loom_material", material, priority=9, budget=1150)
        return product, intention, source

    def _witness_options(self, candidate: Mapping[str, Any],
                         intention: Mapping[str, Any] | None) -> list[str]:
        if candidate.get("source") == "intention_cue":
            return ["quiet", "form"]
        if intention is None:
            return ["quiet"]
        if intention.get("state") == "paused":
            return ["quiet", "resume", "satisfy", "release"]
        options = ["quiet", "reframe", "pause", "satisfy", "release"]
        if self.loom.relationships_for(intention["intention_id"]):
            options.extend(["coexist", "differentiate", "braid"])
        if shadow_eligibility(intention)["eligible"]:
            options.append("propose_project")
        return options

    @staticmethod
    def _usage(events) -> dict:
        completed = next((event for event in reversed(events)
                          if event.kind == "completed"), None)
        usage = dict(getattr(completed, "usage", {}) or {})
        normalized = {
            "input_tokens": int(usage.get("input_tokens")
                                or usage.get("prompt_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens")
                                 or usage.get("completion_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
        }
        for key in ("total_ms", "provider_ms", "prompt_ms", "gen_ms",
                    "load_ms"):
            if isinstance(usage.get(key), (int, float)):
                normalized[key] = float(usage[key])
        return normalized

    def _commit(self, context, candidate, proposal, intention, *, run_id=None):
        commit_run_id = str(run_id or context.run_id)
        action = proposal["action"]
        if candidate.get("source") == "project_shadow":
            if action == "shape":
                record = self.project_loom.shape(
                    candidate["proposal_id"], run_id=commit_run_id,
                    purpose=proposal["purpose"],
                    possibility=proposal["possibility"],
                    completion_signal=proposal["completion_signal"],
                    uncertainty_low=proposal["uncertainty_low"],
                    uncertainty_high=proposal["uncertainty_high"],
                    basis=proposal["basis"])
                return "project_shaped", record
            if action == "nominate_action":
                record = self.project_loom.nominate_action(
                    candidate["proposal_id"], run_id=commit_run_id,
                    capability=proposal["capability"],
                    candidate=proposal["candidate"],
                    expected_signal=proposal["expected_signal"],
                    reversibility=proposal["reversibility"],
                    uncertainty_low=proposal["uncertainty_low"],
                    uncertainty_high=proposal["uncertainty_high"],
                    basis=proposal["basis"])
                return "project_action_nominated", record
            if action == "evaluate":
                record = self.project_loom.evaluate_actions(
                    candidate["proposal_id"], run_id=commit_run_id,
                    candidate_ids=proposal["candidate_ids"],
                    vectors=proposal["vectors"],
                    comparison=proposal["comparison"],
                    basis=proposal["basis"])
                return "project_actions_compared", record
            if action == "orient":
                record = self.project_loom.orient(
                    candidate["proposal_id"], run_id=commit_run_id,
                    evaluation_id=proposal["evaluation_id"],
                    candidate_id=proposal["candidate_id"],
                    confidence_low=proposal["confidence_low"],
                    confidence_high=proposal["confidence_high"],
                    basis=proposal["basis"])
                return "project_oriented", record
            if action == "select_internal":
                record = self.project_loom.select_internal_action(
                    candidate["proposal_id"], run_id=commit_run_id,
                    orientation_id=proposal["orientation_id"],
                    candidate_id=proposal["candidate_id"],
                    capability=proposal["capability"],
                    basis=proposal["basis"])
                if self.internal_action_submitter is None:
                    raise ValueError("internal action owner is not attached")
                owner_record = self.internal_action_submitter(record)
                admission = self.project_loom.acknowledge_internal_action(
                    record["selection_id"], owner_record)
                return "internal_action_handed_off", {
                    **record,
                    "owner_record_digest": _digest(owner_record),
                    "destination_admission_id": admission["selection_id"],
                    "owner_adoption_id": admission["selection_id"],
                }
            return "project_quiet", self.project_loom.projection(
                candidate["proposal_id"])
        is_cue = candidate.get("source") == "intention_cue"
        if is_cue and action not in {"quiet", "form"}:
            raise ValueError("a possibility cue admits only quiet or form")
        current_state = None if is_cue else intention.get("state")
        allowed = ({"quiet", "resume", "satisfy", "release"}
                   if current_state == "paused" else
                   {"quiet", "reframe", "pause", "satisfy", "release",
                    "coexist", "differentiate", "braid",
                    "propose_project"})
        if not is_cue and action not in allowed:
            raise ValueError("open intention proposal action is invalid")
        if action == "form":
            record = self.loom.form_intention(
                commit_run_id, candidate["cue_id"],
                title=proposal["title"], statement=proposal["statement"],
                uncertainty_low=proposal["uncertainty_low"],
                uncertainty_high=proposal["uncertainty_high"],
                basis=proposal["basis"])
            return "formed", record
        if action == "reframe":
            record = self.loom.reframe_intention(
                commit_run_id, intention["intention_id"],
                title=proposal["title"], statement=proposal["statement"],
                uncertainty_low=proposal["uncertainty_low"],
                uncertainty_high=proposal["uncertainty_high"],
                basis=proposal["basis"])
            return "reframed", record
        if action in {"coexist", "differentiate", "braid"}:
            record = self.loom.relate_intention(
                commit_run_id, intention["intention_id"],
                related_intention_id=proposal.get(
                    "related_intention_id") or "",
                movement=action, basis=proposal["basis"],
                title=proposal["title"], statement=proposal["statement"],
                uncertainty_low=proposal["uncertainty_low"],
                uncertainty_high=proposal["uncertainty_high"])
            return (
                "braided" if action == "braid"
                else f"related_{action}", record)
        if action == "propose_project":
            record = self.project_loom.propose(
                self.loom.intention(intention["intention_id"]),
                title=proposal["title"],
                private_outcome=proposal["statement"])
            return "project_proposed", record
        if action == "pause":
            return "paused", self.loom.pause_intention(
                commit_run_id, intention["intention_id"],
                basis=proposal["basis"])
        if action == "resume":
            return "resumed", self.loom.resume_intention(
                commit_run_id, intention["intention_id"])
        if action in {"satisfy", "release"}:
            resolution = "satisfied" if action == "satisfy" else "released"
            return resolution, self.loom.resolve_intention(
                commit_run_id, intention["intention_id"],
                resolution=resolution, basis=proposal["basis"])
        if is_cue:
            record = self.loom.observe_cue(
                candidate["cue_id"], commit_run_id,
                basis=proposal["basis"])
        else:
            record = self.loom.observe_intention(
                commit_run_id, intention["intention_id"],
                basis=proposal["basis"])
        return "quiet", record

    def _candidate_current(self, candidate: Mapping[str, Any]) -> bool:
        source = str(dict(candidate or {}).get("source") or "")
        if source == "intention_cue":
            cue_id = candidate.get("cue_id")
            return cue_id in {
                value.get("cue_id") for value in self.loom.pending_cues()}
        if source == "intention_open":
            intention_id = candidate.get("intention_id")
            return intention_id in {
                value.get("intention_id") for value in self.loom.intentions()
                if value.get("state") in {"open", "paused"}}
        if source == "project_shadow":
            try:
                self.project_loom.proposal(candidate.get("proposal_id"))
                return True
            except ValueError:
                return False
        return False

    def start_candidate(self, candidate: Mapping[str, Any]) -> dict:
        candidate = dict(candidate or {})
        if not self.eligible(candidate):
            return {"started": False, "reason": "not_eligible"}
        if not self._candidate_current(candidate):
            return {"started": False, "reason": "stale_candidate"}
        readiness = self.readiness(getattr(self.engine, "idle_metabolism", None))
        capability = self.capability()
        if not capability["usable"]:
            return {"started": False, "reason": capability["reason"]}
        spec = self._load_spec()
        projection = witness_projection(candidate, readiness)
        witnessed = (
            candidate.get("source") != "project_shadow"
            and projection["witness"])
        try:
            product, intention, _source = self._assembly(
                candidate, spec, witnessed=witnessed)
        except Exception as exc:
            return {"started": False, "reason": type(exc).__name__}
        proposal_id = _digest({
            "candidate": candidate.get("key"),
            "updated": candidate.get("updated"),
            "state_ref": product.state_ref,
        })
        run_id = f"intention-loom-{proposal_id}"
        episode = (
            self.choice_ledger.open_fork(
                owner="intention_loom", run_id=run_id, candidate=candidate,
                options=self._witness_options(candidate, intention),
                projection=projection)
            if witnessed else None)
        episode_id = (episode or {}).get("episode_id")
        adapter = self._model_adapter(spec)
        identity = dict(spec.get("identity") or {})
        subject_kind, subject_id = self._subject(candidate)
        if subject_kind != "project":
            self.loom.record_attention(
                "attention_selected", candidate_key=candidate.get("key"),
                subject_kind=subject_kind, subject_id=subject_id,
                now=time.time())

        async def runner(context):
            cycle_id = new_cycle_id()
            events = []
            attempts = 1
            with model_call_scope(
                    cycle_id=cycle_id,
                    persona=getattr(self.engine, "persona", "unknown"),
                    purpose="intention_loom"):
                try:
                    event_args = {
                        "tools": (), "exchanges": (),
                        "max_tokens": self.config.max_tokens,
                        "temperature": product.temperature,
                        "cancel": context.cancellation,
                    }
                    if str(identity.get("provider") or "") == "ollama":
                        event_args["output_format"] = (
                            "json" if candidate.get("source") == "project_shadow"
                            else INTENTION_MOVEMENTS_SCHEMA)
                    events = [event async for event in adapter.events(
                        product.assembly, **event_args)]
                    usage = self._usage(events)
                    attempts = 1 + len(getattr(
                        getattr(adapter, "event_transport", None),
                        "last_attempt_receipts", ()) or ())
                    record_model_call(
                        str(identity.get("provider") or "unknown"),
                        str(identity.get("endpoint") or self.config.model),
                        {**usage, "attempts": attempts}, status="ok")
                    text = collect_legacy_text(events, context.cancellation)
                except Exception as exc:
                    record_model_call(
                        str(identity.get("provider") or "unknown"),
                        str(identity.get("endpoint") or self.config.model),
                        {"error_type": type(exc).__name__}, status="failed")
                    raise
            context.cancellation.raise_if_cancelled()
            is_project = candidate.get("source") == "project_shadow"
            try:
                if is_project:
                    proposals = parse_project_movements(text, intention)
                else:
                    proposals = parse_intention_movements(text)
            except ValueError as exc:
                raise MovementContractDiscrepancy(
                    "parse", _movement_failure_code(exc)) from exc
            envelope = InteriorWorkEnvelope.from_readiness(
                readiness, response_tokens=self.config.max_tokens)
            admitted_proposals = []
            for proposal in proposals:
                if not envelope.admit(proposal):
                    break
                admitted_proposals.append(proposal)
                if proposal["action"] in {"quiet", "satisfy", "release"}:
                    break
            if not admitted_proposals:
                raise MovementContractDiscrepancy(
                    "envelope", "no_movement_admitted")
            if candidate.get("source") == "intention_cue":
                admitted_proposals = admitted_proposals[:1]
            proposals = admitted_proposals
            proposal = proposals[0]
            if episode_id:
                self.choice_ledger.commit_choice(
                    episode_id, action=proposal["action"],
                    orientation=proposal.get("orientation") or "",
                    basis=proposal.get("basis") or "")
            movements = []
            current_intention = intention
            newly_nominated = None
            try:
                for index, movement in enumerate(proposals):
                    movement = dict(movement)
                    if movement.get(
                            "candidate_id") == NEWLY_NOMINATED_CANDIDATE:
                        if newly_nominated is None:
                            raise ValueError(
                                "newly nominated candidate is unavailable")
                        if movement.get("capability") != newly_nominated.get(
                                "capability"):
                            raise ValueError(
                                "selection capability does not match nomination")
                        movement["candidate_id"] = newly_nominated["candidate_id"]
                    movement_run_id = (
                        context.run_id if index == 0
                        else f"{context.run_id}:movement:{index + 1}")
                    outcome, record = self._commit(
                        context, candidate, movement, current_intention,
                        run_id=movement_run_id)
                    movements.append({
                        "outcome": outcome, "record": record,
                        "run_id": movement_run_id})
                    if outcome == "project_action_nominated":
                        newly_nominated = record
                    if is_project:
                        current_intention = self.project_loom.projection(
                            candidate["proposal_id"])
                    else:
                        intention_id = (
                            record.get("intention_id")
                            or (current_intention or {}).get("intention_id"))
                        if intention_id:
                            current_intention = self.loom.intention(intention_id)
            except Exception as exc:
                if episode_id:
                    self.choice_ledger.settle_owner(
                        episode_id, accepted=False, outcome="rejected",
                        reason=f"{type(exc).__name__}: {exc}")
                    raise OwnerChoiceRejected(
                        episode_id, f"{type(exc).__name__}: {exc}") from exc
                raise
            outcome = movements[-1]["outcome"]
            record = movements[-1]["record"]
            if episode_id:
                self.choice_ledger.settle_owner(
                    episode_id, accepted=True, outcome=outcome,
                    durable_ref=str(record.get("intention_id")
                                    or record.get("proposal_id") or ""))
            usage = self._usage(events)
            return AgencyRunOutcome(
                result={"outcome": outcome, "record": record,
                        "movements": movements,
                        "movement_count": len(movements),
                        "work_envelope": envelope.status(),
                        "choice_episode_id": episode_id,
                        "usage": usage,
                        "provider_http_attempts": attempts},
                metrics={"model_requests": 1,
                         "provider_http_attempts": attempts, **usage})

        try:
            future = self.controller.start(
                run_id, runner, proposal_id=proposal_id,
                interruptible=False)
        except Exception as exc:
            return {"started": False, "reason": type(exc).__name__}
        future.add_done_callback(lambda done: self._completed(
            run_id, proposal_id, candidate, readiness, capability, done,
            choice_episode_id=episode_id))
        self._emit(
            "intention_loom_proposed", run_id=run_id,
            proposal_id=proposal_id, candidate_key=candidate.get("key"),
            model=self.config.model, locality=capability.get("locality"))
        return {"started": True, "run_id": run_id,
                "proposal_id": proposal_id, "future": future}

    def _completed(self, run_id: str, proposal_id: str,
                   candidate: Mapping[str, Any], readiness: Mapping[str, Any],
                   capability: Mapping[str, Any], future, *,
                   choice_episode_id: str = None) -> None:
        try:
            outcome = future.result()
            result = dict(getattr(outcome, "result", {}) or {})
        except Exception as exc:
            if isinstance(exc, OwnerChoiceRejected):
                self._effects.put({
                    "kind": "settled", "run_id": run_id,
                    "proposal_id": proposal_id, "candidate": dict(candidate),
                    "outcome": "owner_rejected",
                    "intention_id": candidate.get("intention_id"),
                    "project_id": candidate.get("proposal_id"),
                    "cue_id": candidate.get("cue_id"),
                    "record_digest": _digest({
                        "episode_id": exc.episode_id,
                        "reason": str(exc)}),
                    "choice_episode_id": exc.episode_id,
                    "usage": {}, "provider_http_attempts": 1,
                    "model": self.config.model,
                    "provider": capability.get("provider"),
                    "locality": capability.get("locality"),
                    "readiness": readiness.get("readiness", 0.0),
                })
                return
            if isinstance(exc, ValueError):
                failure_stage = (
                    exc.stage if isinstance(exc, MovementContractDiscrepancy)
                    else "commit")
                failure_code = (
                    exc.code if isinstance(exc, MovementContractDiscrepancy)
                    else _movement_failure_code(exc))
                discrepancy = _movement_contract_consequence(
                    failure_stage, failure_code)
                failure_digest = _digest({
                    "candidate": candidate.get("key"),
                    "error_type": type(exc).__name__,
                    "failure_stage": failure_stage,
                    "failure_code": failure_code,
                    "discrepancy": discrepancy,
                })
                if choice_episode_id:
                    try:
                        self.choice_ledger.settle_owner(
                            choice_episode_id, accepted=False,
                            outcome="contract_discrepancy",
                            reason=(
                                "The local result did not satisfy the durable "
                                "movement contract; no owner choice was "
                                "inferred."))
                    except (KeyError, TypeError, ValueError):
                        pass
                self._effects.put({
                    "kind": "settled", "run_id": run_id,
                    "proposal_id": proposal_id,
                    "candidate": dict(candidate),
                    "outcome": "contract_discrepancy",
                    "failure_stage": failure_stage,
                    "failure_code": failure_code,
                    "discrepancy": discrepancy,
                    "intention_id": candidate.get("intention_id"),
                    "project_id": candidate.get("proposal_id"),
                    "cue_id": candidate.get("cue_id"),
                    "record_digest": failure_digest,
                    "choice_episode_id": choice_episode_id,
                    "usage": {}, "provider_http_attempts": 1,
                    "model": self.config.model,
                    "provider": capability.get("provider"),
                    "locality": capability.get("locality"),
                    "readiness": readiness.get("readiness", 0.0),
                })
                self._emit(
                    "intention_loom_contract_discrepancy",
                    run_id=run_id, proposal_id=proposal_id,
                    candidate_key=candidate.get("key"),
                    error_type=type(exc).__name__,
                    failure_stage=failure_stage,
                    failure_code=failure_code,
                    failure_digest=failure_digest)
                return
            self._effects.put({
                "kind": "retry", "run_id": run_id,
                "proposal_id": proposal_id, "candidate": dict(candidate),
                "reason": ("interrupted" if isinstance(
                    exc, concurrent.futures.CancelledError)
                    else f"failed:{type(exc).__name__}"),
            })
            return
        record = dict(result.get("record") or {})
        self._effects.put({
            "kind": "settled", "run_id": run_id,
            "proposal_id": proposal_id, "candidate": dict(candidate),
            "outcome": result.get("outcome") or "quiet",
            "movement_count": int(result.get("movement_count") or 1),
            "work_envelope": dict(result.get("work_envelope") or {}),
            "intention_id": record.get("intention_id")
                or candidate.get("intention_id"),
            "project_id": record.get("proposal_id")
                or candidate.get("proposal_id"),
            "cue_id": candidate.get("cue_id"),
            "record_digest": _digest(record),
            "choice_episode_id": result.get("choice_episode_id"),
            "usage": dict(result.get("usage") or {}),
            "provider_http_attempts": int(
                result.get("provider_http_attempts") or 1),
            "model": self.config.model,
            "provider": capability.get("provider"),
            "locality": capability.get("locality"),
            "readiness": readiness.get("readiness", 0.0),
        })

    @staticmethod
    def _event_text(outcome: str, intention_id: str | None,
                    discrepancy: Mapping[str, Any] | None = None) -> str:
        if outcome == "contract_discrepancy":
            discrepancy = dict(discrepancy or {})
            field = str(discrepancy.get("field") or "movement")
            observed = str(discrepancy.get("observed") or "host_validation_failed")
            constraint = str(discrepancy.get("constraint") or
                             "all host movement invariants")
            return (
                "A private Intention Loom opening encountered an inspectable "
                f"movement-contract discrepancy at {field}: observed {observed}; "
                f"the required constraint was {constraint}. No intention state "
                "or outward condition was changed; the discrepancy settled into "
                "history instead of renewing the same attentional demand.")
        if outcome == "owner_rejected":
            return (
                "A witnessed private intention choice was refused by the "
                "Intention Loom owner. No intention changed; the unresolved "
                "choice and refusal remain durable.")
        if outcome == "internal_action_handed_off":
            return (
                "A private project selected one wrapper-local reversible action and "
                "its typed owner, Writing Desk, validated and adopted it as private "
                "material. Nothing was published, messaged, scheduled, or sent "
                "outside the persona wrapper.")
        if outcome == "project_oriented":
            return (
                "A private project formed a revisable attentional orientation toward "
                "one exact compared hypothesis. No action was selected, no authority "
                "was requested, and no consent, tool binding, schedule, or execution "
                "state was created.")
        if outcome == "project_actions_compared":
            return (
                "Two exact private action hypotheses were descriptively compared "
                "through uncertain ranges for fit, cost, risk, reversibility, and "
                "embodied response. No winner was selected and no consent, schedule, "
                "tool binding, or execution authority was created.")
        if outcome == "project_action_nominated":
            return (
                "A shaped private project nominated one hypothetical action after "
                "winning shared attention. The candidate was recorded with "
                "uncertainty, reversibility, and an expected private signal, but "
                "received no tool binding, consent, schedule, or execution authority.")
        if outcome == "project_shaped":
            return (
                "A private project proposal was descriptively shaped after winning "
                "shared attention. Its purpose, one possibility, uncertainty, and "
                "a private completion signal were recorded without creating work, "
                "authority, or an outward effect.")
        if outcome == "project_quiet":
            return (
                "A private project proposal was encountered and left unchanged for "
                "now. Nothing was scheduled, executed, sent, or changed outside "
                "the loom.")
        if outcome == "quiet":
            return (
                "A private possibility or intention was encountered and left "
                "unchanged for now. Nothing was planned, sent, or changed outside "
                "the loom.")
        if outcome == "formed":
            return (
                "A continuing intention was privately formed and recorded. "
                "It names what appeared to matter; it did not begin a project "
                "or authorize an action.")
        if outcome == "reframed":
            return (
                "A private intention was encountered again and its wording changed. "
                "Its earlier wording remains history; no project or outward action began.")
        if outcome == "paused":
            return (
                "A private intention was paused. Its history remains and related "
                "lived evidence may bring it through attention again.")
        if outcome == "resumed":
            return (
                "A paused private intention appeared to move again and was resumed. "
                "This did not authorize a project or outward action.")
        if outcome == "satisfied":
            return (
                "A private intention appeared satisfied and was recorded as settled. "
                "No external completion was claimed.")
        return (
            "A private intention was released. Its history remains without requiring "
            "continuation or claiming an outward effect.")

    def drain_effects(self, field, *, now: float = None) -> list[dict]:
        now = time.time() if now is None else float(now)
        admitted = []
        while True:
            try:
                effect = self._effects.get_nowait()
            except queue.Empty:
                break
            if effect["kind"] == "retry":
                candidate = dict(effect["candidate"])
                field.pressure.refund()
                restored = field.queue.put(
                    candidate, float(candidate.get("salience", 0.05)),
                    now=now, offer_meta={
                        "operation": "requeued", "reason": effect["reason"]})
                admitted.append(restored)
                continue
            source_candidate = dict(effect["candidate"])
            source_satiety = field.satiate(source_candidate, now=now)
            prior_loom_satiety = field.satiety.warmth("intention_loom", now)
            loom_satiety = field.satiety.touch(
                "intention_loom",
                max(0.0, min(1.0, float(
                    source_candidate.get("salience", 0.0)))),
                label="intention_loom", now=now)
            outcome = str(effect.get("outcome") or "quiet")
            event_text = self._event_text(
                outcome, effect.get("intention_id"), effect.get("discrepancy"))
            felt = None
            try:
                felt = circulate_experienced_event(self.engine, event_text)
            except Exception as exc:
                self._emit(
                    "intention_loom_effect_failed", run_id=effect["run_id"],
                    error_type=f"felt_consequence:{type(exc).__name__}")
            usage = dict(effect.get("usage") or {})
            continuity = {
                "novelty": 1.0 / (1.0 + source_satiety),
                "affect_change": _finite((felt or {}).get(
                    "affect_change"), 0.0),
                "body_intensity": _finite((felt or {}).get(
                    "body_change"), 0.0),
                "relationship": _finite((source_candidate.get(
                    "features") or {}).get("relationship"), 0.0),
                "unresolved": 1.0 if outcome in {
                    "formed", "reframed", "resumed"} else 0.0,
            }
            self.loom.record_receipt({
                "kind": "run", "run_id": effect["run_id"],
                "candidate_key": source_candidate.get("key"),
                "outcome": outcome,
                "failure_stage": effect.get("failure_stage"),
                "failure_code": effect.get("failure_code"),
                "discrepancy": dict(effect.get("discrepancy") or {}),
                "intention_id": effect.get("intention_id"),
                "cue_id": effect.get("cue_id"),
                "model": effect.get("model"),
                "provider": effect.get("provider"),
                "locality": effect.get("locality"),
                "model_requests": 1,
                "movement_count": effect.get("movement_count", 1),
                "work_envelope": effect.get("work_envelope", {}),
                "provider_http_attempts": effect.get(
                    "provider_http_attempts", 1),
                **usage, "estimated_cost_usd": 0.0,
                "readiness": effect.get("readiness"),
                "source_satiety": source_satiety,
                "loom_satiety": loom_satiety,
                **continuity,
            })
            candidate = field.offer_cognitive_event(
                "intention_effect", event_text,
                continuity,
                key=f"intention_effect:{effect['run_id']}", now=now,
                raw_ref=effect.get("record_digest"),
                ownership="persona_private",
                receipts=[effect.get("record_digest")])
            candidate.update({
                "intention_id": effect.get("intention_id"),
                "project_id": effect.get("project_id"),
                "intention_movement": outcome,
                "intention_record_digest": effect.get("record_digest"),
                "intention_consequence": dict(effect.get("discrepancy") or {}),
            })
            if effect.get("choice_episode_id"):
                self.choice_ledger.encounter_consequence(
                    effect["choice_episode_id"],
                    candidate_key=str(candidate.get("key") or ""))
                candidate["choice_episode_id"] = effect["choice_episode_id"]
            admitted.append(candidate)
            self._emit(
                "intention_loom_field_reentry", run_id=effect["run_id"],
                outcome=outcome, candidate_key=candidate.get("key"),
                intention_id=effect.get("intention_id"),
                loom_satiety_before=prior_loom_satiety,
                loom_satiety_after=loom_satiety)
        for episode in self.choice_ledger.pending_consequences(
                "intention_loom"):
            outcome = str(episode.get("outcome") or "unknown")
            accepted = bool(episode.get("accepted"))
            event_text = (
                f"A previously witnessed private Loom choice returned after "
                f"restart. Its owner {'accepted' if accepted else 'refused'} "
                f"the selected branch; the durable outcome is {outcome}.")
            try:
                felt = circulate_experienced_event(self.engine, event_text)
            except Exception:
                felt = {}
            candidate = field.offer_cognitive_event(
                "choice_consequence", event_text,
                {"novelty": .35,
                 "affect_change": _finite((felt or {}).get(
                     "affect_change"), 0.0),
                 "body_intensity": _finite((felt or {}).get(
                     "body_change"), 0.0),
                 "relationship": 0.0, "unresolved": 0.0},
                key=f"choice_consequence:{episode['episode_id']}", now=now,
                raw_ref=episode["episode_id"], ownership="persona_private",
                receipts=[episode["episode_id"]])
            candidate["choice_episode_id"] = episode["episode_id"]
            self.choice_ledger.encounter_consequence(
                episode["episode_id"],
                candidate_key=str(candidate.get("key") or ""))
            admitted.append(candidate)
        if admitted:
            field.save(now=now)
            if self._observer is not None:
                self._observer.field_snapshot(field, now)
        return admitted

    def status(self) -> dict:
        registry = getattr(self.engine, "internal_action_registry", None)
        return {
            "enabled": "intention_loom" in getattr(
                self.engine, "enabled", set()),
            "config": {
                "model": self.config.model,
                "authority_tier": self.config.authority_tier,
                "local_only": self.config.local_only,
                "max_tokens": self.config.max_tokens,
            },
            "capability": self.capability(),
            "controller": self.controller.status(),
            "readiness": self.readiness(
                getattr(self.engine, "idle_metabolism", None)),
            "loom": self.loom.status(),
            "project_loom": self.project_loom.status(),
            "choice_junction": self.choice_ledger.status(),
            "interior_work": {
                "field_win_opens_resource_shaped_sequence": True,
                "project_shape_optional": True,
                "nomination_and_owned_handoff_can_share_sequence": True,
                "generated_candidate_reference_is_host_resolved": True,
                "destination_owner_revalidates": True,
                "human_grant_required": False,
                "external_discharge": False,
            },
            "internal_actions": (
                registry.status() if registry is not None else {
                    "capabilities": {}, "external_effects": False,
                    "arbitrary_paths": False, "cross_persona": False,
                }),
        }

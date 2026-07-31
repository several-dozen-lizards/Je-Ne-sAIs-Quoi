"""Proposal-only Project Loom shadow; no store, scheduler, tools, or execution."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from pathlib import Path
from typing import Any, Mapping


INTENTION_RE = re.compile(r"^intention_[0-9a-f]{16}$")
PROJECT_RE = re.compile(r"^project_[0-9a-f]{16}$")
CANDIDATE_RE = re.compile(r"^candidate_[0-9a-f]{16}$")
EVALUATION_RE = re.compile(r"^evaluation_[0-9a-f]{16}$")
ORIENTATION_RE = re.compile(r"^orientation_[0-9a-f]{16}$")
SHADOW_AUTHORITY = {
    "local_only": True,
    "private_only": True,
    "reversible": True,
    "tools": False,
    "external_effects": False,
    "execution_authority": False,
}
INTERNAL_CAPABILITY_OWNERS = {
    "writing_desk.private_draft": "writing_desk",
    "atelier.private_creation": "atelier",
    "document_reader.read_accessible_document": "document_reader",
}
LEDGER_SCHEMAS = {
    "proposals.jsonl": 1,
    "movements.jsonl": 2,
    "action_candidates.jsonl": 3,
    "evaluations.jsonl": 4,
    "orientations.jsonl": 5,
    "internal_selections.jsonl": 6,
    "owner_adoptions.jsonl": 7,
    "owner_outcomes.jsonl": 8,
}


def _digest(value: Any) -> str:
    rendered = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        default=str)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def shadow_eligibility(intention: Mapping[str, Any]) -> dict:
    """Project future eligibility without creating or offering a project."""
    intention = dict(intention or {})
    relationship = dict(intention.get("last_relationship") or {})
    movement = str(relationship.get("movement") or "")
    related_id = str(relationship.get("related_intention_id") or "")
    vector = dict(relationship.get("vector") or {})
    gates = {
        "continuing_intention": intention.get("state") == "open",
        "append_only_convergence": movement in {
            "coexist", "differentiate", "braid"},
        "exact_related_intention": bool(
            INTENTION_RE.fullmatch(related_id)),
        "private_provenance": bool(
            dict(intention.get("source") or {}).get("cue_id")),
        "bounded_uncertainty": (
            isinstance(intention.get("uncertainty"), list)
            and len(intention["uncertainty"]) == 2
            and all(isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and math.isfinite(float(value))
                    and 0.0 <= float(value) <= 1.0
                    for value in intention["uncertainty"])
            and intention["uncertainty"][0] <= intention["uncertainty"][1]),
    }
    eligible = all(gates.values())
    convergence = {
        "movement": movement,
        "related_intention_id": related_id,
        "vector": vector,
    }
    return {
        "mode": "shadow",
        "eligible": eligible,
        "held_reasons": [key for key, passed in gates.items() if not passed],
        "gates": gates,
        "convergence_digest": _digest(convergence) if eligible else "",
        "proposal_created": False,
        "store_created": False,
        "authority": dict(SHADOW_AUTHORITY),
    }


def validate_shadow_proposal(value: Mapping[str, Any]) -> dict:
    """Validate a future proposal record without persisting or executing it."""
    value = dict(value or {})
    required = {
        "schema", "state", "intention_id", "title", "private_outcome",
        "uncertainty", "convergence_digest", "authority",
    }
    if set(value) != required:
        raise ValueError("project shadow proposal fields are not exact")
    if value.get("schema") != 1 or value.get("state") != "shadow":
        raise ValueError("project proposal must remain schema-1 shadow state")
    if not INTENTION_RE.fullmatch(str(value.get("intention_id") or "")):
        raise ValueError("project proposal intention id is invalid")
    for key in ("title", "private_outcome", "convergence_digest"):
        if not str(value.get(key) or "").strip():
            raise ValueError(f"project proposal {key} must not be empty")
    uncertainty = value.get("uncertainty")
    if not isinstance(uncertainty, list) or len(uncertainty) != 2:
        raise ValueError("project proposal uncertainty must be a range")
    low, high = uncertainty
    if any(isinstance(item, bool) or not isinstance(item, (int, float))
           or not math.isfinite(float(item)) for item in uncertainty) \
            or not 0.0 <= float(low) <= float(high) <= 1.0:
        raise ValueError("project proposal uncertainty range is invalid")
    if dict(value.get("authority") or {}) != SHADOW_AUTHORITY:
        raise ValueError("project proposal cannot expand shadow authority")
    return {
        **value,
        "title": str(value["title"]).strip(),
        "private_outcome": str(value["private_outcome"]).strip(),
        "convergence_digest": str(value["convergence_digest"]).strip(),
        "uncertainty": [float(low), float(high)],
        "authority": dict(SHADOW_AUTHORITY),
    }


def authority_bridge_shadow(projection: Mapping[str, Any]) -> dict:
    """Expose missing authority contracts without creating a request."""
    projection = dict(projection or {})
    orientations = list(projection.get("orientations") or [])
    latest = orientations[-1] if orientations else {}
    gates = {
        "private_orientation_exists": bool(latest),
        "exact_candidate_provenance": bool(
            CANDIDATE_RE.fullmatch(str(
                latest.get("orientation_candidate_id") or ""))),
        "typed_action_owner": False,
        "owner_request_contract": False,
        "fresh_owner_pre_execution_recheck": False,
        "consumable_owner_grant": False,
    }
    return {
        "mode": "held_shadow",
        "eligible": all(gates.values()),
        "gates": gates,
        "held_reasons": [key for key, passed in gates.items() if not passed],
        "authority_request_created": False,
        "consent_grant_created": False,
        "execution_authority": False,
    }


class ProjectLoom:
    """Append-only private proposals; deliberately owns no execution path."""

    def __init__(self, persona_dir, *, now_fn=time.time):
        self.root = Path(persona_dir).resolve() / "body" / "project_loom"
        self.index = self.root / "proposals.jsonl"
        self.movement_index = self.root / "movements.jsonl"
        self.candidate_index = self.root / "action_candidates.jsonl"
        self.evaluation_index = self.root / "evaluations.jsonl"
        self.orientation_index = self.root / "orientations.jsonl"
        self.selection_index = self.root / "internal_selections.jsonl"
        self.adoption_index = self.root / "owner_adoptions.jsonl"
        self.outcome_index = self.root / "owner_outcomes.jsonl"
        self.now_fn = now_fn

    @staticmethod
    def _records(path: Path, expected_schema: int) -> list[dict]:
        if not path.is_file():
            return []
        values = []
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    value = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if (isinstance(value, dict)
                        and value.get("schema") == expected_schema):
                    values.append(value)
        return values

    def proposals(self) -> list[dict]:
        return self._records(self.index, 1)

    def movements(self, proposal_id: str = "") -> list[dict]:
        values = self._records(self.movement_index, 2)
        if proposal_id:
            values = [
                value for value in values
                if value.get("proposal_id") == proposal_id]
        return values

    def proposal(self, proposal_id: str) -> dict:
        proposal_id = str(proposal_id or "").strip()
        for value in self.proposals():
            if value.get("proposal_id") == proposal_id:
                return value
        raise ValueError("project proposal does not exist")

    def action_candidates(self, proposal_id: str = "") -> list[dict]:
        values = self._records(self.candidate_index, 3)
        if proposal_id:
            values = [
                value for value in values
                if value.get("proposal_id") == proposal_id]
        return values

    def evaluations(self, proposal_id: str = "") -> list[dict]:
        values = self._records(self.evaluation_index, 4)
        if proposal_id:
            values = [
                value for value in values
                if value.get("proposal_id") == proposal_id]
        return values

    def orientations(self, proposal_id: str = "") -> list[dict]:
        values = self._records(self.orientation_index, 5)
        if proposal_id:
            values = [
                value for value in values
                if value.get("proposal_id") == proposal_id]
        return values

    def internal_selections(self, proposal_id: str = "") -> list[dict]:
        values = self._records(self.selection_index, 6)
        if proposal_id:
            values = [
                value for value in values
                if value.get("proposal_id") == proposal_id]
        return values

    def owner_adoptions(self, proposal_id: str = "") -> list[dict]:
        values = self._records(self.adoption_index, 7)
        if proposal_id:
            values = [
                value for value in values
                if value.get("proposal_id") == proposal_id]
        return values

    def owner_outcomes(self, proposal_id: str = "") -> list[dict]:
        values = self._records(self.outcome_index, 8)
        if proposal_id:
            values = [
                value for value in values
                if value.get("proposal_id") == proposal_id]
        return values

    def ledger_diagnostics(self) -> dict:
        """Describe ignored ledger lines without exposing their contents."""
        ledgers = {}
        for path in (
                self.index, self.movement_index, self.candidate_index,
                self.evaluation_index, self.orientation_index,
                self.selection_index, self.adoption_index,
                self.outcome_index):
            expected = LEDGER_SCHEMAS[path.name]
            counts = {
                "expected_schema": expected,
                "accepted": 0,
                "malformed": 0,
                "unsupported_schema": 0,
            }
            if path.is_file():
                with path.open(encoding="utf-8") as handle:
                    for line in handle:
                        try:
                            value = json.loads(line)
                        except (TypeError, ValueError):
                            counts["malformed"] += 1
                            continue
                        if not isinstance(value, dict):
                            counts["malformed"] += 1
                        elif value.get("schema") != expected:
                            counts["unsupported_schema"] += 1
                        else:
                            counts["accepted"] += 1
            ledgers[path.name] = counts
        return {
            "mode": "content_free",
            "ledgers": ledgers,
            "malformed": sum(v["malformed"] for v in ledgers.values()),
            "unsupported_schema": sum(
                v["unsupported_schema"] for v in ledgers.values()),
        }

    def pending_internal_selections(self) -> list[dict]:
        adopted = {
            value.get("selection_id") for value in self.owner_adoptions()}
        return [
            value for value in self.internal_selections()
            if value.get("selection_id") not in adopted]

    def propose(self, intention: Mapping[str, Any], *, title: str,
                private_outcome: str) -> dict:
        eligibility = shadow_eligibility(intention)
        if not eligibility["eligible"]:
            raise ValueError(
                "project proposal is held: "
                + ",".join(eligibility["held_reasons"]))
        intention_id = str(intention.get("intention_id") or "")
        if any(record.get("intention_id") == intention_id
               for record in self.proposals()):
            raise ValueError(
                "this intention already formed a private project proposal")
        value = validate_shadow_proposal({
            "schema": 1, "state": "shadow", "intention_id": intention_id,
            "title": title, "private_outcome": private_outcome,
            "uncertainty": list(intention.get("uncertainty") or []),
            "convergence_digest": eligibility["convergence_digest"],
            "authority": dict(SHADOW_AUTHORITY),
        })
        created_at = float(self.now_fn())
        record = {
            **value,
            "proposal_id": "project_" + _digest({
                "intention_id": intention_id,
                "convergence_digest": value["convergence_digest"],
                "created_at": created_at,
            })[:16],
            "created_at": created_at,
            "ownership": "persona_private",
        }
        self.root.mkdir(parents=True, exist_ok=True)
        with self.index.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(
                record, ensure_ascii=False, sort_keys=True) + "\n")
        return record

    def shape(self, proposal_id: str, *, run_id: str, purpose: str,
              possibility: str, completion_signal: str,
              uncertainty_low: float, uncertainty_high: float,
              basis: str) -> dict:
        """Append one descriptive project shape; never create executable work."""
        proposal_id = str(proposal_id or "").strip()
        run_id = str(run_id or "").strip()
        if not PROJECT_RE.fullmatch(proposal_id):
            raise ValueError("project shape proposal id is invalid")
        proposal = self.proposal(proposal_id)
        if proposal.get("state") != "shadow" \
                or dict(proposal.get("authority") or {}) != SHADOW_AUTHORITY:
            raise ValueError("project shape authority boundary is invalid")
        if not run_id:
            raise ValueError("project shape requires an originating run")
        if any(value.get("run_id") == run_id for value in self.movements()):
            raise ValueError("one project shape movement is allowed per run")
        fields = {
            "purpose": str(purpose or "").strip(),
            "possibility": str(possibility or "").strip(),
            "completion_signal": str(completion_signal or "").strip(),
            "basis": str(basis or "").strip(),
        }
        if any(not value for value in fields.values()):
            raise ValueError("project shape descriptive fields must not be empty")
        uncertainty = [uncertainty_low, uncertainty_high]
        if any(isinstance(item, bool) or not isinstance(item, (int, float))
               or not math.isfinite(float(item)) for item in uncertainty) \
                or not 0.0 <= float(uncertainty_low) \
                <= float(uncertainty_high) <= 1.0:
            raise ValueError("project shape uncertainty range is invalid")
        created_at = float(self.now_fn())
        record = {
            "schema": 2, "movement": "shape",
            "movement_id": "movement_" + _digest({
                "proposal_id": proposal_id, "run_id": run_id,
                "created_at": created_at,
            })[:16],
            "proposal_id": proposal_id, "run_id": run_id,
            **fields,
            "uncertainty": [
                float(uncertainty_low), float(uncertainty_high)],
            "created_at": created_at,
            "ownership": "persona_private",
            "authority": dict(SHADOW_AUTHORITY),
        }
        self.root.mkdir(parents=True, exist_ok=True)
        with self.movement_index.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(
                record, ensure_ascii=False, sort_keys=True) + "\n")
        return record

    def nominate_action(self, proposal_id: str, *, run_id: str,
                        capability: str, candidate: str, expected_signal: str,
                        reversibility: str, uncertainty_low: float,
                        uncertainty_high: float, basis: str) -> dict:
        """Append one hypothetical action candidate with exactly zero authority."""
        proposal_id = str(proposal_id or "").strip()
        run_id = str(run_id or "").strip()
        if not PROJECT_RE.fullmatch(proposal_id):
            raise ValueError("action candidate proposal id is invalid")
        projection = self.projection(proposal_id)
        if dict(projection.get("authority") or {}) != SHADOW_AUTHORITY:
            raise ValueError("action candidate authority boundary is invalid")
        if not run_id:
            raise ValueError("action candidate requires an originating run")
        capability = str(capability or "").strip()
        if capability not in INTERNAL_CAPABILITY_OWNERS:
            raise ValueError("action candidate capability is not registered")
        prior_runs = self.movements() + self.action_candidates()
        if any(value.get("run_id") == run_id for value in prior_runs):
            raise ValueError("one project movement is allowed per run")
        fields = {
            "candidate": str(candidate or "").strip(),
            "expected_signal": str(expected_signal or "").strip(),
            "reversibility": str(reversibility or "").strip(),
            "basis": str(basis or "").strip(),
        }
        if any(not value for value in fields.values()):
            raise ValueError("action candidate descriptive fields must not be empty")
        uncertainty = [uncertainty_low, uncertainty_high]
        if any(isinstance(item, bool) or not isinstance(item, (int, float))
               or not math.isfinite(float(item)) for item in uncertainty) \
                or not 0.0 <= float(uncertainty_low) \
                <= float(uncertainty_high) <= 1.0:
            raise ValueError("action candidate uncertainty range is invalid")
        created_at = float(self.now_fn())
        record = {
            "schema": 3, "state": "candidate_only",
            "candidate_id": "candidate_" + _digest({
                "proposal_id": proposal_id, "run_id": run_id,
                "created_at": created_at,
            })[:16],
            "proposal_id": proposal_id, "run_id": run_id,
            "capability": capability,
            "owner": INTERNAL_CAPABILITY_OWNERS[capability],
            **fields,
            "uncertainty": [
                float(uncertainty_low), float(uncertainty_high)],
            "created_at": created_at,
            "ownership": "persona_private",
            "shape_optional": projection["latest_shape"] is None,
            "authority": dict(SHADOW_AUTHORITY),
            "tool_binding": None, "consent_grant": None,
            "scheduler_slot": None, "execution_state": "unavailable",
        }
        self.root.mkdir(parents=True, exist_ok=True)
        with self.candidate_index.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(
                record, ensure_ascii=False, sort_keys=True) + "\n")
        return record

    @staticmethod
    def _evaluation_vector(value: Mapping[str, Any],
                           candidate_id: str) -> dict:
        value = dict(value or {})
        dimensions = {
            "fit", "cost", "risk", "reversibility", "embodied_response"}
        if set(value) != {"candidate_id", *dimensions} \
                or str(value.get("candidate_id") or "") != candidate_id:
            raise ValueError("evaluation vector fields or candidate id are invalid")
        result = {"candidate_id": candidate_id}
        for dimension in dimensions:
            interval = value.get(dimension)
            if not isinstance(interval, list) or len(interval) != 2:
                raise ValueError("evaluation dimensions must be ranges")
            low, high = interval
            if any(isinstance(item, bool) or not isinstance(item, (int, float))
                   or not math.isfinite(float(item)) for item in interval) \
                    or not 0.0 <= float(low) <= float(high) <= 1.0:
                raise ValueError("evaluation dimension range is invalid")
            result[dimension] = [float(low), float(high)]
        return result

    def evaluate_actions(self, proposal_id: str, *, run_id: str,
                         candidate_ids: list[str], vectors: list[Mapping[str, Any]],
                         comparison: str, basis: str) -> dict:
        """Compare exactly two hypotheses without selecting either one."""
        proposal_id = str(proposal_id or "").strip()
        run_id = str(run_id or "").strip()
        if not PROJECT_RE.fullmatch(proposal_id):
            raise ValueError("evaluation proposal id is invalid")
        projection = self.projection(proposal_id)
        if dict(projection.get("authority") or {}) != SHADOW_AUTHORITY:
            raise ValueError("evaluation authority boundary is invalid")
        if not run_id:
            raise ValueError("evaluation requires an originating run")
        prior_runs = (
            self.movements() + self.action_candidates() + self.evaluations())
        if any(value.get("run_id") == run_id for value in prior_runs):
            raise ValueError("one project movement is allowed per run")
        if not isinstance(candidate_ids, list) or len(candidate_ids) != 2 \
                or len(set(candidate_ids)) != 2 \
                or any(not CANDIDATE_RE.fullmatch(str(value or ""))
                       for value in candidate_ids):
            raise ValueError("evaluation requires two exact candidate ids")
        available = {
            value["candidate_id"]
            for value in self.action_candidates(proposal_id)}
        if any(candidate_id not in available for candidate_id in candidate_ids):
            raise ValueError("evaluation candidate does not belong to project")
        if not isinstance(vectors, list) or len(vectors) != 2:
            raise ValueError("evaluation requires two candidate vectors")
        by_id = {
            str(dict(value or {}).get("candidate_id") or ""): value
            for value in vectors}
        if set(by_id) != set(candidate_ids):
            raise ValueError("evaluation vectors must match candidate ids")
        normalized = [
            self._evaluation_vector(by_id[candidate_id], candidate_id)
            for candidate_id in candidate_ids]
        comparison = str(comparison or "").strip()
        basis = str(basis or "").strip()
        if not comparison or not basis:
            raise ValueError("evaluation comparison and basis must not be empty")
        created_at = float(self.now_fn())
        record = {
            "schema": 4, "state": "comparison_only",
            "evaluation_id": "evaluation_" + _digest({
                "proposal_id": proposal_id, "run_id": run_id,
                "candidate_ids": candidate_ids, "created_at": created_at,
            })[:16],
            "proposal_id": proposal_id, "run_id": run_id,
            "candidate_ids": list(candidate_ids), "vectors": normalized,
            "comparison": comparison, "basis": basis,
            "selection": None, "created_at": created_at,
            "ownership": "persona_private",
            "authority": dict(SHADOW_AUTHORITY),
            "tool_binding": None, "consent_grant": None,
            "scheduler_slot": None, "execution_state": "unavailable",
        }
        self.root.mkdir(parents=True, exist_ok=True)
        with self.evaluation_index.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(
                record, ensure_ascii=False, sort_keys=True) + "\n")
        return record

    def orient(self, proposal_id: str, *, run_id: str, evaluation_id: str,
               candidate_id: str, confidence_low: float,
               confidence_high: float, basis: str) -> dict:
        """Record revisable private orientation; do not select an action."""
        proposal_id = str(proposal_id or "").strip()
        run_id = str(run_id or "").strip()
        evaluation_id = str(evaluation_id or "").strip()
        candidate_id = str(candidate_id or "").strip()
        if not PROJECT_RE.fullmatch(proposal_id):
            raise ValueError("orientation proposal id is invalid")
        if not EVALUATION_RE.fullmatch(evaluation_id):
            raise ValueError("orientation evaluation id is invalid")
        if not CANDIDATE_RE.fullmatch(candidate_id):
            raise ValueError("orientation candidate id is invalid")
        evaluations = {
            value["evaluation_id"]: value
            for value in self.evaluations(proposal_id)}
        evaluation = evaluations.get(evaluation_id)
        if evaluation is None or candidate_id not in evaluation["candidate_ids"]:
            raise ValueError(
                "orientation must use a candidate from the exact evaluation")
        if not run_id:
            raise ValueError("orientation requires an originating run")
        prior_runs = (
            self.movements() + self.action_candidates()
            + self.evaluations() + self.orientations())
        if any(value.get("run_id") == run_id for value in prior_runs):
            raise ValueError("one project movement is allowed per run")
        confidence = [confidence_low, confidence_high]
        if any(isinstance(item, bool) or not isinstance(item, (int, float))
               or not math.isfinite(float(item)) for item in confidence) \
                or not 0.0 <= float(confidence_low) \
                <= float(confidence_high) <= 1.0:
            raise ValueError("orientation confidence range is invalid")
        basis = str(basis or "").strip()
        if not basis:
            raise ValueError("orientation basis must not be empty")
        created_at = float(self.now_fn())
        record = {
            "schema": 5, "state": "private_orientation_only",
            "orientation_id": "orientation_" + _digest({
                "proposal_id": proposal_id, "run_id": run_id,
                "evaluation_id": evaluation_id,
                "candidate_id": candidate_id, "created_at": created_at,
            })[:16],
            "proposal_id": proposal_id, "run_id": run_id,
            "evaluation_id": evaluation_id,
            "orientation_candidate_id": candidate_id,
            "confidence": [
                float(confidence_low), float(confidence_high)],
            "basis": basis, "revisable": True,
            "selection_scope": "private_attention_only",
            "action_selected": False, "authority_request": None,
            "consent_grant": None, "tool_binding": None,
            "scheduler_slot": None, "execution_state": "unavailable",
            "created_at": created_at, "ownership": "persona_private",
            "authority": dict(SHADOW_AUTHORITY),
        }
        self.root.mkdir(parents=True, exist_ok=True)
        with self.orientation_index.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(
                record, ensure_ascii=False, sort_keys=True) + "\n")
        return record

    def select_internal_action(self, proposal_id: str, *, run_id: str,
                               orientation_id: str = "", candidate_id: str,
                               capability: str, basis: str) -> dict:
        """Select one same-owner private handoff, with optional deliberation."""
        proposal_id = str(proposal_id or "").strip()
        run_id = str(run_id or "").strip()
        orientation_id = str(orientation_id or "").strip()
        candidate_id = str(candidate_id or "").strip()
        capability = str(capability or "").strip()
        if not PROJECT_RE.fullmatch(proposal_id) \
                or not CANDIDATE_RE.fullmatch(candidate_id):
            raise ValueError("internal selection provenance is invalid")
        if orientation_id:
            if not ORIENTATION_RE.fullmatch(orientation_id):
                raise ValueError("internal selection orientation is invalid")
            orientations = self.orientations(proposal_id)
            orientation = next((
                value for value in orientations
                if value.get("orientation_id") == orientation_id), None)
            if orientation is None or orientation.get(
                    "orientation_candidate_id") != candidate_id:
                raise ValueError(
                    "internal selection must match the exact private orientation")
        candidate = next((
            value for value in self.action_candidates(proposal_id)
            if value.get("candidate_id") == candidate_id), None)
        if candidate is None:
            raise ValueError("internal selection candidate does not exist")
        owner = INTERNAL_CAPABILITY_OWNERS.get(capability)
        if owner is None:
            raise ValueError("internal selection capability is not registered")
        if candidate.get("capability") != capability \
                or candidate.get("owner") != owner:
            raise ValueError(
                "internal selection cannot reinterpret candidate capability")
        if any(
                (orientation_id and value.get("orientation_id") == orientation_id)
                or value.get("candidate_id") == candidate_id
                for value in self.internal_selections(proposal_id)):
            raise ValueError("this candidate already selected an internal action")
        if not run_id:
            raise ValueError("internal selection requires an originating run")
        prior_runs = (
            self.movements() + self.action_candidates() + self.evaluations()
            + self.orientations() + self.internal_selections())
        if any(value.get("run_id") == run_id for value in prior_runs):
            raise ValueError("one project movement is allowed per run")
        basis = str(basis or "").strip()
        if not basis:
            raise ValueError("internal selection basis must not be empty")
        created_at = float(self.now_fn())
        record = {
            "schema": 6, "state": "owner_handoff",
            "selection_id": "selection_" + _digest({
                "proposal_id": proposal_id, "orientation_id": orientation_id,
                "candidate_id": candidate_id,
            })[:16],
            "proposal_id": proposal_id, "run_id": run_id,
            "orientation_id": orientation_id or None,
            "selection_mode": (
                "deliberated_orientation" if orientation_id
                else "direct_owned_candidate"),
            "candidate_id": candidate_id,
            "capability": capability,
            "owner": owner,
            "payload": {
                "label": str(candidate.get("candidate") or "")[:160],
                "content": str(candidate.get("candidate") or ""),
                "expected_signal": candidate.get("expected_signal"),
                "project_loom_provenance": {
                    "proposal_id": proposal_id,
                    "candidate_id": candidate_id,
                    "selection_mode": (
                        "deliberated_orientation" if orientation_id
                        else "direct_owned_candidate"),
                    **({"orientation_id": orientation_id}
                       if orientation_id else {}),
                },
            },
            "basis": basis, "action_selected": True,
            "authority_scope": "wrapper_local_private_reversible",
            "human_grant_required": False,
            "destination_validation_required": True,
            "owner_validation_required": True,  # schema-6 compatibility
            "tool_binding": None, "scheduler_slot": None,
            "external_effects": False, "created_at": created_at,
            "ownership": "persona_private",
        }
        self.root.mkdir(parents=True, exist_ok=True)
        with self.selection_index.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(
                record, ensure_ascii=False, sort_keys=True) + "\n")
        return record

    def acknowledge_internal_action(
            self, selection_id: str, owner_record: Mapping[str, Any]) -> dict:
        """Record durable destination admission for one private handoff."""
        selection_id = str(selection_id or "").strip()
        selection = next((
            value for value in self.internal_selections()
            if value.get("selection_id") == selection_id), None)
        if selection is None:
            raise ValueError("internal selection does not exist")
        prior = next((
            value for value in self.owner_adoptions()
            if value.get("selection_id") == selection_id), None)
        if prior is not None:
            return {**prior, "duplicate": True}
        owner_record = dict(owner_record or {})
        owner_ref = str(
            owner_record.get("seed_id")
            or owner_record.get("interest_id")
            or owner_record.get("artifact_id")
            or "").strip()
        if not owner_ref:
            raise ValueError("owner adoption record has no durable reference")
        created_at = float(self.now_fn())
        record = {
            "schema": 7, "state": "owner_adopted",
            "selection_id": selection_id,
            "proposal_id": selection["proposal_id"],
            "capability": selection["capability"],
            "owner": selection["owner"],
            "owner_ref": owner_ref,
            "owner_record_digest": _digest(owner_record),
            "adopted_at": created_at,
            "ownership": "persona_private",
            "external_effects": False,
        }
        self.root.mkdir(parents=True, exist_ok=True)
        with self.adoption_index.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(
                record, ensure_ascii=False, sort_keys=True) + "\n")
        return {
            **record, "duplicate": False,
            "semantic_state": "destination_admitted",
        }

    def record_owner_outcome(self, owner_ref: str, *, run_id: str,
                             outcome: str, durable_ref: str = "",
                             usage: Mapping[str, Any] | None = None) -> dict:
        """Return an owner's settled consequence to its exact selection."""
        owner_ref = str(owner_ref or "").strip()
        adoption = next((
            value for value in self.owner_adoptions()
            if value.get("owner_ref") == owner_ref), None)
        if adoption is None:
            raise ValueError("owner outcome has no Project Loom adoption")
        prior = next((
            value for value in self.owner_outcomes()
            if value.get("selection_id") == adoption["selection_id"]), None)
        if prior is not None:
            return {**prior, "duplicate": True}
        outcome = str(outcome or "").strip()
        run_id = str(run_id or "").strip()
        if not outcome or not run_id:
            raise ValueError("owner outcome requires outcome and run id")
        usage = dict(usage or {})
        safe_usage = {
            key: usage.get(key) for key in (
                "input_tokens", "output_tokens", "total_tokens",
                "total_ms", "estimated_cost_usd")
            if isinstance(usage.get(key), (int, float))
            and not isinstance(usage.get(key), bool)}
        record = {
            "schema": 8, "state": "owner_settled",
            "selection_id": adoption["selection_id"],
            "proposal_id": adoption["proposal_id"],
            "capability": adoption["capability"],
            "owner": adoption["owner"], "owner_ref": owner_ref,
            "owner_run_id": run_id, "outcome": outcome,
            "durable_ref": str(durable_ref or "").strip() or None,
            "usage": safe_usage,
            "settled_at": float(self.now_fn()),
            "ownership": "persona_private",
            "external_effects": False,
        }
        self.root.mkdir(parents=True, exist_ok=True)
        with self.outcome_index.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(
                record, ensure_ascii=False, sort_keys=True) + "\n")
        return {**record, "duplicate": False}

    def projection(self, proposal_id: str) -> dict:
        proposal = self.proposal(proposal_id)
        movements = self.movements(proposal_id)
        latest = movements[-1] if movements else None
        candidates = self.action_candidates(proposal_id)
        evaluations = self.evaluations(proposal_id)
        orientations = self.orientations(proposal_id)
        selections = self.internal_selections(proposal_id)
        adoptions = self.owner_adoptions(proposal_id)
        outcomes = self.owner_outcomes(proposal_id)
        stage = "proposed"
        if movements:
            stage = "shaped"
        if candidates:
            stage = "candidates_nominated"
        if evaluations:
            stage = "deliberated"
        if orientations:
            stage = "oriented"
        if selections:
            stage = "selected"
        if adoptions:
            stage = "owner_adopted"
        if outcomes:
            stage = "owner_settled"
        projection = {
            "proposal": proposal,
            "latest_shape": latest,
            "movement_count": len(movements),
            "action_candidates": candidates,
            "action_candidate_count": len(candidates),
            "evaluations": evaluations,
            "evaluation_count": len(evaluations),
            "orientations": orientations,
            "orientation_count": len(orientations),
            "internal_selections": selections,
            "internal_selection_count": len(selections),
            "owner_adoptions": adoptions,
            "owner_adoption_count": len(adoptions),
            "pending_owner_adoption_count": max(
                0, len(selections) - len(adoptions)),
            "owner_outcomes": outcomes,
            "owner_outcome_count": len(outcomes),
            "authority": dict(SHADOW_AUTHORITY),
            "execution": False,
            "lifecycle": {
                "stage": stage,
                "latest_outcome": (
                    outcomes[-1].get("outcome") if outcomes else None),
                "recoverable_owner_handoffs": max(
                    0, len(selections) - len(adoptions)),
                "append_only": True,
            },
        }
        projection["authority_bridge_shadow"] = authority_bridge_shadow(
            projection)
        return projection

    def status(self) -> dict:
        values = self.proposals()
        return {
            "mode": "wrapper_internal_action",
            "root": "body/project_loom",
            "proposals": values,
            "proposal_count": len(values),
            "movement_count": len(self.movements()),
            "action_candidate_count": len(self.action_candidates()),
            "evaluation_count": len(self.evaluations()),
            "orientation_count": len(self.orientations()),
            "internal_selection_count": len(self.internal_selections()),
            "owner_adoption_count": len(self.owner_adoptions()),
            "pending_owner_adoption_count": len(
                self.pending_internal_selections()),
            "owner_outcome_count": len(self.owner_outcomes()),
            "ledger_diagnostics": self.ledger_diagnostics(),
            "projections": [
                self.projection(value["proposal_id"]) for value in values],
            "authority": dict(SHADOW_AUTHORITY),
            "scheduler": False, "model": False, "tools": False,
            "execution": False,
        }

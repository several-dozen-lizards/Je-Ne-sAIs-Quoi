"""Transactional R1 maintenance for missing derived memory-vector rows.

Canonical ``memories.json`` is never written.  Plans may contain private ids
and source text in process memory, but every public result is content-free.
Actual commits retain exact pre-commit sidecar artifacts for explicit rollback;
bypass and sham never replace an authoritative sidecar file.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Callable, Mapping


OPERATOR_ID = "memory_vector_missing_row_repair_v1"
MODEL_ID = "all-MiniLM-L6-v2"
ARMS = frozenset({"actual", "bypass", "sham"})
SAFE_TRANSACTION = re.compile(r"^[a-zA-Z0-9_-]{8,120}$")


def _sha256(path: str | Path) -> str | None:
    path = Path(path)
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _digest(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False).encode("ascii")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    payload = json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False).encode("ascii")
    with temporary.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _write_json_list(path: Path, value: list[str]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    payload = json.dumps(
        list(value), separators=(",", ":"), ensure_ascii=True,
        allow_nan=False).encode("ascii")
    with temporary.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _copy_fsync(source: Path, target: Path) -> None:
    temporary = target.with_name(target.name + ".tmp")
    shutil.copyfile(source, temporary)
    with temporary.open("rb+") as handle:
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)


class VectorRepairOperator:
    """One owner-local deterministic derived-index maintenance operator."""

    def __init__(self, organ, *, embedder: Callable | None = None):
        self.organ = organ
        self.vectors = organ.vectors
        self.embedder = embedder or self.vectors._embed
        self.root = Path(organ.dir) / "derived_maintenance" / OPERATOR_ID

    def _state(self) -> dict[str, Any]:
        memories = list(self.organ.memories)
        canonical_ids = [str(row.get("id") or "") for row in memories]
        if not all(canonical_ids) or len(set(canonical_ids)) != len(canonical_ids):
            raise RuntimeError("canonical memory ids are missing or duplicated")
        sidecar_ids = [str(value) for value in self.vectors.ids]
        if len(set(sidecar_ids)) != len(sidecar_ids):
            raise RuntimeError("vector sidecar ids are duplicated")
        matrix = self.vectors.matrix
        matrix_rows = int(matrix.shape[0]) if matrix is not None else 0
        if matrix_rows != len(sidecar_ids):
            raise RuntimeError("vector matrix/id row alignment is invalid")
        canonical_set = set(canonical_ids)
        extra = [value for value in sidecar_ids if value not in canonical_set]
        if extra:
            raise RuntimeError("vector sidecar contains noncanonical rows")
        missing = [row for row in memories
                   if str(row.get("id") or "") not in self.vectors.row]
        covered = [row for row in memories
                   if str(row.get("id") or "") in self.vectors.row]
        canonical_hash = _sha256(self.organ.store_path)
        if canonical_hash is None:
            raise RuntimeError("canonical memory receipt is unavailable")
        vector_exists = Path(self.vectors.vec_path).is_file()
        ids_exists = Path(self.vectors.ids_path).is_file()
        if vector_exists != ids_exists:
            raise RuntimeError("vector sidecar receipt is structurally partial")
        return {
            "memories": memories,
            "canonical_ids": canonical_ids,
            "sidecar_ids": sidecar_ids,
            "missing": missing,
            "covered": covered,
            "matrix_rows": matrix_rows,
            "canonical_hash": canonical_hash,
            "vectors_hash": _sha256(self.vectors.vec_path),
            "ids_hash": _sha256(self.vectors.ids_path),
            "memory_revision": int(
                getattr(self.organ, "_memory_revision", 0) or 0),
            "persisted_revision": int(
                getattr(self.organ, "_persisted_revision", 0) or 0),
        }

    def status(self) -> dict[str, Any]:
        """Return owner truth without ids, text, vectors, or file paths."""
        try:
            state = self._state()
        except Exception as exc:
            return {
                "schema_version": 1, "operator_id": OPERATOR_ID,
                "status": "unavailable", "reason": type(exc).__name__,
                "content_free": True, "read_only": True,
            }
        return {
            "schema_version": 1,
            "operator_id": OPERATOR_ID,
            "status": "supported",
            "canonical_records": len(state["canonical_ids"]),
            "vector_rows": state["matrix_rows"],
            "vector_covered": (
                len(state["canonical_ids"]) - len(state["missing"])),
            "vector_gap": len(state["missing"]),
            "reversible": True,
            "canonical_mutation_authorized": False,
            "model_locality": "local_cpu",
            "model_id": MODEL_ID,
            "content_free": True,
            "read_only": True,
        }

    def plan(self, arm: str) -> dict[str, Any]:
        """Capture one private in-memory plan under the resident state lease."""
        arm = str(arm or "")
        if arm not in ARMS:
            raise ValueError("unknown vector maintenance arm")
        state = self._state()
        if not state["missing"]:
            raise RuntimeError("no missing vector row exists")
        if state["memory_revision"] != state["persisted_revision"]:
            raise RuntimeError("canonical memory revision is not persisted")
        if getattr(self.vectors, "_pending", None):
            raise RuntimeError("vector pending tail is not empty")
        if getattr(self.vectors, "_embedder_healthy", None) is not True:
            raise RuntimeError("local vector model health is not proved")
        targets = (state["missing"] if arm in {"actual", "bypass"}
                   else state["covered"][:1])
        if arm == "sham" and not targets:
            raise RuntimeError("sham requires one already-covered row")
        private_targets = [{
            "id": str(row["id"]),
            "text": str(row.get("text") or row.get("content") or "")[:600],
        } for row in targets]
        if any(not row["text"] for row in private_targets):
            raise RuntimeError("vector target has no embeddable canonical text")
        basis = {
            "operator_id": OPERATOR_ID,
            "arm": arm,
            "canonical_hash": state["canonical_hash"],
            "vectors_hash": state["vectors_hash"],
            "ids_hash": state["ids_hash"],
            "canonical_records": len(state["canonical_ids"]),
            "sidecar_rows": state["matrix_rows"],
            "target_digests": [hashlib.sha256(
                row["id"].encode("utf-8")).hexdigest()
                for row in private_targets],
        }
        return {
            "operator_id": OPERATOR_ID,
            "arm": arm,
            "plan_revision": _digest(basis),
            "before": state,
            "targets": private_targets,
            "projection": {
                "schema_version": 1,
                "operator_id": OPERATOR_ID,
                "arm": arm,
                "plan_revision": _digest(basis),
                "canonical_records": len(state["canonical_ids"]),
                "vector_rows": state["matrix_rows"],
                "vector_gap": len(state["missing"]),
                "target_count": len(private_targets),
                "canonical_hash": state["canonical_hash"],
                "vectors_hash": state["vectors_hash"],
                "ids_hash": state["ids_hash"],
                "private_target_material_exposed": False,
                "content_free": True,
                "read_only": True,
            },
        }

    def compute(self, plan: Mapping[str, Any]) -> dict[str, Any]:
        """Perform local embedding only; no authoritative file is touched."""
        plan = dict(plan)
        arm = str(plan.get("arm") or "")
        if arm == "bypass":
            return {
                "arm": arm, "matrix": None, "local_model_calls": 0,
                "computed_rows": 0, "elapsed_ms": 0.0,
                "content_free": True,
            }
        targets = list(plan.get("targets") or ())
        started = time.monotonic()
        matrix = self.embedder([row["text"] for row in targets])
        elapsed_ms = max(0.0, (time.monotonic() - started) * 1000.0)
        if matrix is None:
            raise RuntimeError("local vector embedder unavailable")
        import numpy as np
        matrix = np.asarray(matrix, dtype="float32")
        if matrix.ndim != 2 or matrix.shape[0] != len(targets):
            raise RuntimeError("local vector result has an invalid shape")
        current = self.vectors.matrix
        if current is not None and matrix.shape[1] != current.shape[1]:
            raise RuntimeError("local vector dimensions differ from sidecar")
        if not np.isfinite(matrix).all():
            raise RuntimeError("local vector result is nonfinite")
        return {
            "arm": arm,
            "matrix": matrix,
            "local_model_calls": 1,
            "computed_rows": int(matrix.shape[0]),
            "elapsed_ms": round(elapsed_ms, 3),
            "content_free": True,
        }

    def _verify_plan_current(self, plan: Mapping[str, Any]) -> dict[str, Any]:
        current = self._state()
        before = dict(plan.get("before") or {})
        for key in (
                "canonical_hash", "vectors_hash", "ids_hash",
                "memory_revision", "persisted_revision", "matrix_rows"):
            if current.get(key) != before.get(key):
                raise RuntimeError("vector repair plan became stale: " + key)
        if current["canonical_ids"] != before.get("canonical_ids"):
            raise RuntimeError("vector repair canonical ordering changed")
        if current["sidecar_ids"] != before.get("sidecar_ids"):
            raise RuntimeError("vector repair sidecar ordering changed")
        return current

    def commit(self, plan: Mapping[str, Any], computed: Mapping[str, Any], *,
               transaction_id: str) -> dict[str, Any]:
        """Commit actual or measure bypass/sham under the state lease."""
        transaction_id = str(transaction_id or "")
        if not SAFE_TRANSACTION.fullmatch(transaction_id):
            raise ValueError("invalid vector repair transaction id")
        plan = dict(plan)
        computed = dict(computed)
        arm = str(plan.get("arm") or "")
        if computed.get("arm") != arm or arm not in ARMS:
            raise ValueError("vector repair plan/compute arm mismatch")
        before = self._verify_plan_current(plan)
        canonical_hash_before = before["canonical_hash"]
        common = {
            "schema_version": 1,
            "kind": "memory_vector_missing_row_repair",
            "operator_id": OPERATOR_ID,
            "arm": arm,
            "transaction_id": transaction_id,
            "plan_revision": plan.get("plan_revision"),
            "before": {
                "canonical_records": len(before["canonical_ids"]),
                "vector_rows": before["matrix_rows"],
                "vector_gap": len(before["missing"]),
                "canonical_hash": canonical_hash_before,
                "vectors_hash": before["vectors_hash"],
                "ids_hash": before["ids_hash"],
            },
            "local_model_calls": int(computed.get("local_model_calls") or 0),
            "local_model_id": MODEL_ID,
            "model_locality": "local_cpu",
            "provider_http_attempts": 0,
            "provider_cost_usd": 0.0,
            "elapsed_ms": float(computed.get("elapsed_ms") or 0.0),
            "computed_rows": int(computed.get("computed_rows") or 0),
            "canonical_memory_writes": 0,
            "memory_admissions": 0,
            "actions_created": 0,
            "speech_created": 0,
            "external_effects": False,
            "rest_field_writes": 0,
            "oscillator_writes": 0,
            "quiet_transition_writes": 0,
            "dream_workspace_writes": 0,
            "hardware_evidence": "unavailable_no_authoritative_monitor",
            "content_free": True,
        }
        if arm in {"bypass", "sham"}:
            after = self._state()
            return {
                **common,
                "status": "measured_no_commit",
                "committed": False,
                "authoritative_sidecar_writes": 0,
                "after": {
                    "canonical_records": len(after["canonical_ids"]),
                    "vector_rows": after["matrix_rows"],
                    "vector_gap": len(after["missing"]),
                    "canonical_hash": after["canonical_hash"],
                    "vectors_hash": after["vectors_hash"],
                    "ids_hash": after["ids_hash"],
                },
            }

        import numpy as np
        target_ids = [str(row["id"]) for row in plan["targets"]]
        new_rows = np.asarray(computed.get("matrix"), dtype="float32")
        if (new_rows.ndim != 2
                or new_rows.shape[0] != len(target_ids)
                or not np.isfinite(new_rows).all()):
            raise RuntimeError("computed vector rows do not match the plan")
        current_matrix = self.vectors.matrix
        new_matrix = (new_rows if current_matrix is None
                      else np.vstack([current_matrix, new_rows]))
        new_ids = list(self.vectors.ids) + target_ids
        if new_matrix.shape[0] != len(new_ids):
            raise RuntimeError("prepared vector sidecar is misaligned")

        tx = self.root / transaction_id
        if tx.exists():
            raise RuntimeError("vector repair transaction already exists")
        tx.mkdir(parents=True)
        live_vec = Path(self.vectors.vec_path)
        live_ids = Path(self.vectors.ids_path)
        before_vec = tx / "before_vectors.npy"
        before_ids = tx / "before_vectors_ids.json"
        prepared_vec = tx / "prepared_vectors.npy"
        prepared_ids = tx / "prepared_vectors_ids.json"
        journal = tx / "transaction.json"
        if live_vec.is_file():
            _copy_fsync(live_vec, before_vec)
        if live_ids.is_file():
            _copy_fsync(live_ids, before_ids)
        np.save(prepared_vec, new_matrix)
        with prepared_vec.open("rb+") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        _write_json_list(prepared_ids, new_ids)
        transaction = {
            **common,
            "state": "prepared",
            "live_vectors_existed": live_vec.is_file(),
            "live_ids_existed": live_ids.is_file(),
            "prepared_vector_rows": len(new_ids),
            "target_count": len(target_ids),
        }
        _write_json(journal, transaction)
        transaction["state"] = "committing"
        _write_json(journal, transaction)
        try:
            os.replace(prepared_vec, live_vec)
            os.replace(prepared_ids, live_ids)
            self.vectors.matrix = new_matrix
            self.vectors.ids = new_ids
            self.vectors.row = {value: index
                                for index, value in enumerate(new_ids)}
            after = self._state()
            if len(after["missing"]) >= len(before["missing"]):
                raise RuntimeError("vector gap did not decrease")
            if after["canonical_hash"] != canonical_hash_before:
                raise RuntimeError("canonical memory changed during repair")
        except Exception:
            if before_vec.is_file():
                _copy_fsync(before_vec, live_vec)
            elif live_vec.exists():
                live_vec.unlink()
            if before_ids.is_file():
                _copy_fsync(before_ids, live_ids)
            elif live_ids.exists():
                live_ids.unlink()
            self.vectors.matrix = (
                np.load(live_vec) if live_vec.is_file() else None)
            self.vectors.ids = (
                json.loads(live_ids.read_text(encoding="utf-8"))
                if live_ids.is_file() else [])
            self.vectors.row = {value: index for index, value
                                in enumerate(self.vectors.ids)}
            transaction["state"] = "rolled_back_after_error"
            _write_json(journal, transaction)
            raise
        transaction.update({
            "state": "committed",
            "after_vectors_hash": after["vectors_hash"],
            "after_ids_hash": after["ids_hash"],
            "after_vector_rows": after["matrix_rows"],
        })
        _write_json(journal, transaction)
        return {
            **common,
            "status": "committed",
            "committed": True,
            "authoritative_sidecar_writes": 2,
            "rollback_artifacts_retained": True,
            "after": {
                "canonical_records": len(after["canonical_ids"]),
                "vector_rows": after["matrix_rows"],
                "vector_gap": len(after["missing"]),
                "canonical_hash": after["canonical_hash"],
                "vectors_hash": after["vectors_hash"],
                "ids_hash": after["ids_hash"],
            },
        }

    def rollback(self, transaction_id: str) -> dict[str, Any]:
        """Explicitly restore the exact retained pre-commit sidecar."""
        transaction_id = str(transaction_id or "")
        if not SAFE_TRANSACTION.fullmatch(transaction_id):
            raise ValueError("invalid vector repair transaction id")
        tx = self.root / transaction_id
        journal = tx / "transaction.json"
        if not journal.is_file():
            raise FileNotFoundError("vector repair transaction not found")
        value = json.loads(journal.read_text(encoding="ascii"))
        if value.get("state") != "committed":
            raise RuntimeError("only a committed vector repair can roll back")
        if _sha256(self.organ.store_path) != dict(
                value.get("before") or {}).get("canonical_hash"):
            raise RuntimeError("canonical memory changed after transaction")
        if _sha256(self.vectors.vec_path) != value.get("after_vectors_hash") \
                or _sha256(self.vectors.ids_path) != value.get("after_ids_hash"):
            raise RuntimeError("sidecar changed after transaction")
        before_vec = tx / "before_vectors.npy"
        before_ids = tx / "before_vectors_ids.json"
        live_vec = Path(self.vectors.vec_path)
        live_ids = Path(self.vectors.ids_path)
        if value.get("live_vectors_existed"):
            if not before_vec.is_file():
                raise RuntimeError("rollback vector artifact is incomplete")
            _copy_fsync(before_vec, live_vec)
        elif live_vec.exists():
            live_vec.unlink()
        if value.get("live_ids_existed"):
            if not before_ids.is_file():
                raise RuntimeError("rollback id artifact is incomplete")
            _copy_fsync(before_ids, live_ids)
        elif live_ids.exists():
            live_ids.unlink()
        import numpy as np
        self.vectors.matrix = (
            np.load(live_vec) if live_vec.is_file() else None)
        self.vectors.ids = (
            json.loads(live_ids.read_text(encoding="utf-8"))
            if live_ids.is_file() else [])
        self.vectors.row = {row: index for index, row
                            in enumerate(self.vectors.ids)}
        value["state"] = "rolled_back_explicitly"
        _write_json(journal, value)
        return {
            "schema_version": 1,
            "operator_id": OPERATOR_ID,
            "transaction_id": transaction_id,
            "status": "rolled_back",
            "canonical_memory_writes": 0,
            "authoritative_sidecar_writes": 2,
            "content_free": True,
        }


__all__ = ["ARMS", "MODEL_ID", "OPERATOR_ID", "VectorRepairOperator"]

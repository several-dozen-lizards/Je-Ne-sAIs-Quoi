"""Read-only, content-free R1 vector-repair baseline collector."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


OPERATOR_ID = "memory_vector_missing_row_repair_v1"


def _hash(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _file_evidence(path: Path) -> dict[str, Any]:
    return {
        "present": path.is_file(),
        "bytes": path.stat().st_size if path.is_file() else None,
        "mtime_ns": path.stat().st_mtime_ns if path.is_file() else None,
        "sha256": _hash(path),
    }


def _safe_list(path: Path) -> list[Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError(path.name + " must contain a JSON list")
    return value


def collect_vector_repair_baseline(
        persona_dir: str | Path, *, observed_at: float) -> dict[str, Any]:
    """Inspect canonical/derived owner files without loading a model or organ."""
    persona_dir = Path(persona_dir).resolve()
    memory_dir = (persona_dir / "body" / "memory_emotion").resolve()
    if persona_dir not in memory_dir.parents:
        raise ValueError("memory owner escaped persona directory")
    memories_path = memory_dir / "memories.json"
    vectors_path = memory_dir / "vectors.npy"
    ids_path = memory_dir / "vectors_ids.json"
    meta_path = memory_dir / "vectors_meta.json"
    history_path = persona_dir / "history" / \
        "rest_quiet_assimilation.jsonl"

    evidence = {
        "canonical_memory": _file_evidence(memories_path),
        "vector_matrix": _file_evidence(vectors_path),
        "vector_ids": _file_evidence(ids_path),
        "vector_metadata": _file_evidence(meta_path),
        "assimilation_history": _file_evidence(history_path),
    }
    try:
        memories = _safe_list(memories_path)
        sidecar_ids = [str(value) for value in _safe_list(ids_path)]
        import numpy as np
        matrix = np.load(vectors_path, mmap_mode="r", allow_pickle=False)
        canonical_ids = [
            str(row.get("id") or "") for row in memories
            if isinstance(row, dict)]
        canonical_valid = bool(
            len(canonical_ids) == len(memories)
            and all(canonical_ids)
            and len(set(canonical_ids)) == len(canonical_ids))
        sidecar_valid = bool(
            matrix.ndim == 2
            and int(matrix.shape[0]) == len(sidecar_ids)
            and len(set(sidecar_ids)) == len(sidecar_ids))
        canonical_set = set(canonical_ids)
        sidecar_set = set(sidecar_ids)
        covered = sum(1 for value in canonical_ids if value in sidecar_set)
        gap = len(canonical_ids) - covered
        extra = sum(1 for value in sidecar_ids if value not in canonical_set)
        status = ("supported" if canonical_valid and sidecar_valid and not extra
                  else "partial")
        dimensions = list(matrix.shape)
    except Exception as exc:
        canonical_ids, sidecar_ids = [], []
        canonical_valid = sidecar_valid = False
        covered = gap = extra = None
        dimensions = None
        status = "unavailable"
        structural_absence = type(exc).__name__
    else:
        structural_absence = None

    metadata = {}
    if meta_path.is_file():
        try:
            raw_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            raw_meta = {}
        if isinstance(raw_meta, dict):
            metadata = {
                key: raw_meta.get(key) for key in (
                    "schema", "generated_at", "generator", "model",
                    "device", "normalized_embeddings", "dtype",
                    "record_count", "ordering", "source_memories_sha256")
                if raw_meta.get(key) is not None
            }

    measurements = {
        "actual": {"observed_runs": 0, "committed_runs": 0,
                   "local_model_calls": 0, "sidecar_writes": 0},
        "bypass": {"observed_runs": 0, "committed_runs": 0,
                   "local_model_calls": 0, "sidecar_writes": 0},
        "sham": {"observed_runs": 0, "committed_runs": 0,
                 "local_model_calls": 0, "sidecar_writes": 0},
    }
    invalid_history_rows = 0
    projection_rows = 0
    if history_path.is_file():
        with history_path.open(encoding="ascii") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except (TypeError, ValueError):
                    invalid_history_rows += 1
                    continue
                if not isinstance(row, dict) or row.get("content_free") is not True:
                    invalid_history_rows += 1
                    continue
                if row.get("kind") == "quiet_assimilation_reachability":
                    projection_rows += 1
                    continue
                if row.get("kind") != "quiet_assimilation_operator":
                    continue
                arm = str(row.get("arm") or "")
                if arm not in measurements:
                    invalid_history_rows += 1
                    continue
                target = measurements[arm]
                target["observed_runs"] += 1
                target["committed_runs"] += int(row.get("committed") is True)
                target["local_model_calls"] += int(
                    row.get("local_model_calls") or 0)
                target["sidecar_writes"] += int(
                    row.get("authoritative_sidecar_writes") or 0)

    return {
        "schema_version": 1,
        "stage": "R1",
        "persona": persona_dir.name,
        "operator_id": OPERATOR_ID,
        "observed_at": float(observed_at),
        "resource": {
            "resource_id": "memory_derived_indexes",
            "owner": "MemoryEmotionOrgan/VectorStore",
            "truth": status,
            "absence": structural_absence,
            "canonical_records": len(canonical_ids)
            if status != "unavailable" else None,
            "vector_rows": len(sidecar_ids)
            if status != "unavailable" else None,
            "vector_covered": covered,
            "vector_gap": gap,
            "noncanonical_vector_rows": extra,
            "canonical_ids_valid": canonical_valid,
            "sidecar_alignment_valid": sidecar_valid,
            "matrix_shape": dimensions,
            "metadata": metadata,
            "runtime_embedder_health": "unavailable_offline_no_model_load",
            "context_index_completeness": "unavailable_offline_derived_at_boot",
        },
        "reachability_history": {
            "projection_rows": projection_rows,
            "invalid_or_non_content_free_rows": invalid_history_rows,
        },
        "operator_measurements": measurements,
        "evidence": evidence,
        "mode": "read_only_offline",
        "state_writes": 0,
        "model_calls": 0,
        "actions_created": 0,
        "behavior_authority": False,
        "content_free": True,
    }


__all__ = ["collect_vector_repair_baseline"]

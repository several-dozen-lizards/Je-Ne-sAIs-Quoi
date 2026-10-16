"""Local-only quarantine for body candidates.

Candidates are staged separately from ``godot-room/assets/avatars``.  Nothing
in this module can assign a body or make the renderer discover one.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from typing import Iterable, List

from core.body_packages import BodyPackageError, inspect_glb


MAX_CANDIDATE_BYTES = 256 * 1024 * 1024
RECORD_NAME = "candidate.json"
ADAPTER_FORMAT = "jnsq-body-adapter/0.1"


def _safe_display_name(name: str) -> str:
    leaf = os.path.basename(str(name or "").replace("\\", "/"))
    leaf = re.sub(r"[^A-Za-z0-9._ -]", "_", leaf).strip(" .")
    if not leaf:
        leaf = "candidate.glb"
    if not leaf.casefold().endswith(".glb"):
        raise BodyPackageError("candidate must be a .glb file")
    return leaf[:160]


class CandidateStager:
    """Write one bounded candidate, then atomically publish its report."""

    def __init__(self, root: str, original_name: str, pilot_target: str,
                 max_bytes: int = MAX_CANDIDATE_BYTES):
        self.root = os.path.realpath(root)
        self.original_name = _safe_display_name(original_name)
        self.pilot_target = str(pilot_target)
        self.max_bytes = int(max_bytes)
        self.candidate_id = uuid.uuid4().hex
        self.directory = os.path.join(self.root, self.candidate_id)
        self.partial_path = os.path.join(self.directory, "body.glb.partial")
        self.body_path = os.path.join(self.directory, "body.glb")
        self.bytes_written = 0
        self._closed = False
        os.makedirs(self.directory, exist_ok=False)
        self._handle = open(self.partial_path, "xb")

    def write(self, chunk: bytes) -> None:
        if self._closed:
            raise BodyPackageError("candidate staging is already closed")
        if not isinstance(chunk, (bytes, bytearray)):
            raise BodyPackageError("candidate stream yielded non-binary data")
        if self.bytes_written + len(chunk) > self.max_bytes:
            raise BodyPackageError(
                f"candidate exceeds {self.max_bytes // (1024 * 1024)} MiB limit")
        if chunk:
            self._handle.write(chunk)
            self.bytes_written += len(chunk)

    def finalize(self) -> dict:
        if self._closed:
            raise BodyPackageError("candidate staging is already closed")
        self._handle.flush()
        os.fsync(self._handle.fileno())
        self._handle.close()
        self._closed = True
        if self.bytes_written == 0:
            self.abort()
            raise BodyPackageError("candidate file is empty")
        os.replace(self.partial_path, self.body_path)
        try:
            compatibility = inspect_glb(self.body_path)
            record = {
                "candidate_id": self.candidate_id,
                "state": "inspected",
                "pilot_target": self.pilot_target,
                "original_name": self.original_name,
                "stored_name": "body.glb",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "install_enabled": False,
                "compatibility": compatibility,
            }
            record_path = os.path.join(self.directory, RECORD_NAME)
            temporary_record = record_path + ".partial"
            with open(temporary_record, "x", encoding="utf-8") as handle:
                json.dump(record, handle, indent=2, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_record, record_path)
            return record
        except Exception:
            self.abort()
            raise

    def abort(self) -> None:
        if not self._closed:
            self._handle.close()
            self._closed = True
        if (os.path.commonpath((self.root, os.path.realpath(self.directory)))
                == self.root and os.path.basename(self.directory) == self.candidate_id):
            shutil.rmtree(self.directory, ignore_errors=True)


def list_candidates(root: str, pilot_target: str) -> List[dict]:
    """List settled candidate records for the current pilot only."""
    try:
        ids = sorted(os.listdir(root))
    except OSError:
        return []
    records = []
    for candidate_id in ids:
        if not re.fullmatch(r"[0-9a-f]{32}", candidate_id):
            continue
        path = os.path.join(root, candidate_id, RECORD_NAME)
        try:
            with open(path, encoding="utf-8") as handle:
                record = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        if (isinstance(record, dict)
                and record.get("pilot_target") == pilot_target
                and record.get("state") == "inspected"):
            report = record.get("compatibility", {})
            records.append({
                "candidate_id": record.get("candidate_id"),
                "state": "inspected",
                "pilot_target": pilot_target,
                "original_name": record.get("original_name"),
                "created_at": record.get("created_at"),
                "install_enabled": False,
                "asset": report.get("asset", {}),
                "structure": report.get("structure", {}),
                "capabilities": report.get("capabilities", {}),
                "limitations": report.get("limitations", []),
            })
    return sorted(records, key=lambda item: item.get("created_at") or "",
                  reverse=True)


def _candidate_directory(root: str, candidate_id: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{32}", str(candidate_id)):
        raise BodyPackageError("invalid candidate id")
    real_root = os.path.realpath(root)
    directory = os.path.realpath(os.path.join(real_root, candidate_id))
    if os.path.commonpath((real_root, directory)) != real_root:
        raise BodyPackageError("candidate resolves outside quarantine")
    return directory


def load_candidate(root: str, candidate_id: str, pilot_target: str) -> dict:
    directory = _candidate_directory(root, candidate_id)
    try:
        with open(os.path.join(directory, RECORD_NAME), encoding="utf-8") as handle:
            record = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise BodyPackageError("candidate is missing or unsettled") from exc
    if (not isinstance(record, dict)
            or record.get("candidate_id") != candidate_id
            or record.get("pilot_target") != pilot_target
            or record.get("state") != "inspected"):
        raise BodyPackageError("candidate does not belong to the active pilot lane")
    adapter_path = os.path.join(directory, "adapter.json")
    try:
        with open(adapter_path, encoding="utf-8") as handle:
            adapter = json.load(handle)
    except (OSError, json.JSONDecodeError):
        adapter = None
    latest_receipt = None
    receipt_path = os.path.join(directory, "preview_receipts.jsonl")
    try:
        with open(receipt_path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    value = json.loads(line)
                    if isinstance(value, dict):
                        latest_receipt = value
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return {"candidate": record, "adapter": adapter,
            "preview_receipt": latest_receipt, "install_enabled": False}


def candidate_model_path(root: str, candidate_id: str,
                         pilot_target: str) -> str:
    """Resolve a settled candidate model without exposing arbitrary paths."""
    load_candidate(root, candidate_id, pilot_target)
    path = os.path.join(_candidate_directory(root, candidate_id), "body.glb")
    if not os.path.isfile(path):
        raise BodyPackageError("candidate model is missing")
    return path


def _mapping_name_map(value, label: str, available: set) -> dict:
    if not isinstance(value, dict):
        raise BodyPackageError(f"{label} must be an object")
    result = {}
    for role, source in value.items():
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", str(role)):
            raise BodyPackageError(f"invalid semantic role {role!r}")
        if source in (None, ""):
            continue
        if not isinstance(source, str) or source not in available:
            raise BodyPackageError(
                f"{label} role {role!r} names an unavailable source")
        result[str(role)] = source
    return result


def _axis_vector(value, label: str, allow_empty: bool = True):
    if value in (None, []):
        if allow_empty:
            return None
        raise BodyPackageError(f"{label} is required")
    if (not isinstance(value, list) or len(value) != 3
            or any(isinstance(component, bool) or
                   not isinstance(component, (int, float)) or
                   not math.isfinite(float(component))
                   for component in value)):
        raise BodyPackageError(f"{label} must contain three finite numbers")
    vector = [float(component) for component in value]
    length = math.sqrt(sum(component * component for component in vector))
    if not 0.999 <= length <= 1.001:
        raise BodyPackageError(f"{label} must be a unit vector")
    return [component / length for component in vector]


def save_candidate_mapping(root: str, candidate_id: str,
                           pilot_target: str, mapping: dict) -> dict:
    """Save a reversible semantic adapter; never publish it to the renderer."""
    loaded = load_candidate(root, candidate_id, pilot_target)
    record = loaded["candidate"]
    report = record.get("compatibility", {})
    options = report.get("mapping_options", {})
    nodes = set(options.get("nodes", []))
    morph_targets = set(options.get("morph_targets", []))
    roles = _mapping_name_map(mapping.get("roles", {}), "roles", nodes)
    expressions = _mapping_name_map(
        mapping.get("expressions", {}), "expressions", morph_targets)
    optical = mapping.get("optical_origin", {})
    if not isinstance(optical, dict):
        raise BodyPackageError("optical_origin must be an object")
    optical_node = optical.get("node")
    if optical_node in (None, ""):
        optical_node = None
    elif not isinstance(optical_node, str) or optical_node not in nodes:
        raise BodyPackageError("optical origin names an unavailable node")
    offset = optical.get("offset_m", [0.0, 0.0, 0.0])
    if (not isinstance(offset, list) or len(offset) != 3
            or any(isinstance(value, bool) or
                   not isinstance(value, (int, float)) or
                   not -10.0 <= float(value) <= 10.0 for value in offset)):
        raise BodyPackageError(
            "optical origin offset_m must contain three values from -10 to 10")
    forward = _axis_vector(
        optical.get("forward_axis_local"), "forward_axis_local")
    up = _axis_vector(optical.get("up_axis_local"), "up_axis_local")
    if forward is not None and up is None:
        raise BodyPackageError(
            "up_axis_local is required when forward_axis_local is mapped")
    if forward is not None and up is not None:
        dot = sum(a * b for a, b in zip(forward, up))
        if abs(dot) > 0.001:
            raise BodyPackageError(
                "forward_axis_local and up_axis_local must be perpendicular")
    now = datetime.now(timezone.utc).isoformat()
    revision_id = uuid.uuid4().hex
    adapter = {
        "format": ADAPTER_FORMAT,
        "revision_id": revision_id,
        "candidate_id": candidate_id,
        "pilot_target": pilot_target,
        "source_sha256": report.get("asset", {}).get("sha256"),
        "mapping_state": ("reviewed" if optical_node and roles.get("head")
                          else "draft"),
        "roles": roles,
        "expressions": expressions,
        "optical_origin": {"node": optical_node,
                           "offset_m": [float(value) for value in offset],
                           "forward_axis_local": forward,
                           "up_axis_local": up},
        "pov_ready": bool(optical_node and forward and up),
        "saved_at": now,
        "install_enabled": False,
    }
    directory = _candidate_directory(root, candidate_id)
    history = os.path.join(directory, "adapter_history")
    os.makedirs(history, exist_ok=True)
    revision_path = os.path.join(history, revision_id + ".json")
    with open(revision_path, "x", encoding="utf-8") as handle:
        json.dump(adapter, handle, indent=2, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
    current_path = os.path.join(directory, "adapter.json")
    temporary = current_path + ".partial"
    try:
        with open(temporary, "x", encoding="utf-8") as handle:
            json.dump(adapter, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, current_path)
    except Exception:
        try:
            os.remove(temporary)
        except OSError:
            pass
        raise
    return adapter


def append_preview_receipt(root: str, candidate_id: str,
                           pilot_target: str, receipt: dict) -> dict:
    """Record an isolated Godot render only for the active adapter revision."""
    loaded = load_candidate(root, candidate_id, pilot_target)
    adapter = loaded.get("adapter")
    if not isinstance(adapter, dict):
        raise BodyPackageError("candidate has no saved adapter")
    if receipt.get("revision_id") != adapter.get("revision_id"):
        raise BodyPackageError("preview receipt does not match active adapter")
    if receipt.get("renderer") != "godot":
        raise BodyPackageError("preview receipt renderer must be godot")
    if receipt.get("outcome") != "rendered":
        raise BodyPackageError("preview receipt outcome must be rendered")
    if receipt.get("room_connected") is not False:
        raise BodyPackageError("sealed preview must report no room connection")
    frame_data_url = receipt.get("frame_data_url")
    prefix = "data:image/png;base64,"
    if not isinstance(frame_data_url, str) or not frame_data_url.startswith(prefix):
        raise BodyPackageError("preview receipt requires a PNG frame")
    try:
        frame = base64.b64decode(frame_data_url[len(prefix):], validate=True)
    except (ValueError, TypeError) as exc:
        raise BodyPackageError("preview frame is invalid base64") from exc
    if len(frame) > 4 * 1024 * 1024 or len(frame) < 24:
        raise BodyPackageError("preview frame size is invalid")
    if frame[:8] != b"\x89PNG\r\n\x1a\n" or frame[12:16] != b"IHDR":
        raise BodyPackageError("preview frame is not PNG")
    width = int.from_bytes(frame[16:20], "big")
    height = int.from_bytes(frame[20:24], "big")
    if not 1 <= width <= 4096 or not 1 <= height <= 4096:
        raise BodyPackageError("preview frame dimensions are invalid")
    pov_ready = bool(receipt.get("pov_ready", False))
    pov_frame = None
    pov_width = 0
    pov_height = 0
    pov_sha256 = None
    if pov_ready:
        pov_data_url = receipt.get("pov_frame_data_url")
        if (not isinstance(pov_data_url, str)
                or not pov_data_url.startswith(prefix)):
            raise BodyPackageError("POV-ready receipt requires a PNG POV frame")
        try:
            pov_frame = base64.b64decode(
                pov_data_url[len(prefix):], validate=True)
        except (ValueError, TypeError) as exc:
            raise BodyPackageError("POV frame is invalid base64") from exc
        if len(pov_frame) > 4 * 1024 * 1024 or len(pov_frame) < 24:
            raise BodyPackageError("POV frame size is invalid")
        if (pov_frame[:8] != b"\x89PNG\r\n\x1a\n"
                or pov_frame[12:16] != b"IHDR"):
            raise BodyPackageError("POV frame is not PNG")
        pov_width = int.from_bytes(pov_frame[16:20], "big")
        pov_height = int.from_bytes(pov_frame[20:24], "big")
        if not 1 <= pov_width <= 4096 or not 1 <= pov_height <= 4096:
            raise BodyPackageError("POV frame dimensions are invalid")
        pov_sha256 = hashlib.sha256(pov_frame).hexdigest()
    position = receipt.get("optical_position_m")
    if (not isinstance(position, list) or len(position) != 3
            or any(isinstance(value, bool) or
                   not isinstance(value, (int, float)) or
                   not math.isfinite(float(value)) or
                   not -100.0 <= float(value) <= 100.0 for value in position)):
        raise BodyPackageError("preview optical position is invalid")
    settled = {
        "schema": "jnsq-body-preview-receipt/0.1",
        "candidate_id": candidate_id,
        "pilot_target": pilot_target,
        "revision_id": adapter["revision_id"],
        "source_sha256": adapter.get("source_sha256"),
        "renderer": "godot",
        "outcome": "rendered",
        "room_connected": False,
        "head_role": str(receipt.get("head_role") or ""),
        "head_resolved": bool(receipt.get("head_resolved", False)),
        "optical_node": str(receipt.get("optical_node") or ""),
        "optical_resolved": bool(receipt.get("optical_resolved", False)),
        "optical_position_m": [float(value) for value in position],
        "pov_ready": pov_ready,
        "rendered_at": datetime.now(timezone.utc).isoformat(),
        "frame_sha256": hashlib.sha256(frame).hexdigest(),
        "frame_width": width,
        "frame_height": height,
        "pov_frame_sha256": pov_sha256,
        "pov_frame_width": pov_width,
        "pov_frame_height": pov_height,
        "install_enabled": False,
    }
    directory = _candidate_directory(root, candidate_id)
    image_path = os.path.join(directory, "preview.png")
    image_temporary = image_path + ".partial"
    with open(image_temporary, "xb") as handle:
        handle.write(frame)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(image_temporary, image_path)
    if pov_frame is not None:
        pov_path = os.path.join(directory, "preview_pov.png")
        pov_temporary = pov_path + ".partial"
        with open(pov_temporary, "xb") as handle:
            handle.write(pov_frame)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(pov_temporary, pov_path)
    path = os.path.join(directory, "preview_receipts.jsonl")
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(settled, ensure_ascii=False,
                                separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return settled

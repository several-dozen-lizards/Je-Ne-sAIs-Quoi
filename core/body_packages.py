"""Read-only inspection and manifest validation for JNSQ 3D bodies.

The inspector deliberately describes what an asset exposes.  It does not
rewrite rigs, install models, or claim capabilities that cannot be observed in
the glTF metadata.  Generated bodies and imported bodies can therefore meet at
the same versioned semantic contract without making one skeleton canonical.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import struct
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple


BODY_FORMAT = "jnsq-body/0.1"
GLB_MAGIC = b"glTF"
GLB_JSON_CHUNK = 0x4E4F534A
MAX_MANIFEST_BYTES = 256 * 1024
MAX_GLB_JSON_BYTES = 16 * 1024 * 1024


class BodyPackageError(ValueError):
    """A body asset cannot be safely described by this contract."""


ROLE_ALIASES: Dict[str, Tuple[str, ...]] = {
    "hips": ("hips", "pelvis", "root"),
    "chest": ("chest", "upperchest", "spine2", "spine02"),
    "neck": ("neck", "neck1", "neck01"),
    "head": ("head", "skull"),
    "left_eye": ("lefteye", "eyeleft", "eye_l", "eyel"),
    "right_eye": ("righteye", "eyeright", "eye_r", "eyer"),
    "jaw": ("jaw", "mandible"),
    "left_hand": ("lefthand", "handleft", "hand_l", "handl"),
    "right_hand": ("righthand", "handright", "hand_r", "handr"),
    "left_foot": ("leftfoot", "footleft", "foot_l", "footl"),
    "right_foot": ("rightfoot", "footright", "foot_r", "footr"),
}

EXPRESSION_ALIASES: Dict[str, Tuple[str, ...]] = {
    "blink_left": ("blinkleft", "blink_l", "eyeclosedleft"),
    "blink_right": ("blinkright", "blink_r", "eyeclosedright"),
    "blink": ("blink", "eyesclosed"),
    "mouth_open": ("jawopen", "mouthopen", "aa", "visemeaa"),
    "smile": ("smile", "happy", "joy"),
    "frown": ("frown", "sad", "mouthdepression"),
    "pucker": ("pucker", "pursing"),
    "mouth_wide": ("mouthwide", "mouthretraction"),
}


def _normalized(name: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name or "").casefold())


def _match_candidates(names: Iterable[str], aliases: Mapping[str, Tuple[str, ...]]) -> Dict[str, List[dict]]:
    matches: Dict[str, List[dict]] = {}
    for role, choices in aliases.items():
        candidates = []
        for name in names:
            norm = _normalized(name)
            confidence = 0.0
            reason = ""
            for alias in choices:
                target = _normalized(alias)
                if norm == target:
                    confidence, reason = 0.98, "exact normalized name"
                    break
                if norm.endswith(target) or norm.startswith(target):
                    confidence, reason = max(confidence, 0.82), "name boundary approximation"
                elif target in norm:
                    confidence, reason = max(confidence, 0.66), "name contains alias"
            if confidence:
                candidates.append({"name": name, "confidence": confidence,
                                   "reason": reason})
        if candidates:
            matches[role] = sorted(candidates,
                                   key=lambda item: (-item["confidence"], item["name"]))[:5]
    return matches


def _read_glb_json(path: str) -> Tuple[dict, int, str]:
    size = os.path.getsize(path)
    if size < 20:
        raise BodyPackageError("GLB is too short to contain a header and JSON chunk")
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        header = handle.read(12)
        digest.update(header)
        magic, version, declared_length = struct.unpack("<4sII", header)
        if magic != GLB_MAGIC:
            raise BodyPackageError("asset is not a binary glTF file")
        if version != 2:
            raise BodyPackageError(f"unsupported GLB version {version}; expected 2")
        if declared_length != size:
            raise BodyPackageError(
                f"GLB length mismatch: header says {declared_length}, file is {size}")
        chunk_header = handle.read(8)
        digest.update(chunk_header)
        chunk_length, chunk_type = struct.unpack("<II", chunk_header)
        if chunk_type != GLB_JSON_CHUNK:
            raise BodyPackageError("first GLB chunk is not JSON")
        if chunk_length > MAX_GLB_JSON_BYTES:
            raise BodyPackageError("GLB JSON metadata exceeds inspection limit")
        raw_json = handle.read(chunk_length)
        digest.update(raw_json)
        if len(raw_json) != chunk_length:
            raise BodyPackageError("GLB JSON chunk is truncated")
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    try:
        document = json.loads(raw_json.rstrip(b" \t\r\n\x00").decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BodyPackageError(f"GLB JSON metadata is invalid: {exc}") from exc
    if not isinstance(document, dict):
        raise BodyPackageError("GLB JSON root must be an object")
    return document, size, digest.hexdigest()


def inspect_glb(path: str) -> dict:
    """Return observed structure and bounded semantic suggestions for one GLB."""
    document, size, sha256 = _read_glb_json(path)
    nodes = document.get("nodes") if isinstance(document.get("nodes"), list) else []
    meshes = document.get("meshes") if isinstance(document.get("meshes"), list) else []
    skins = document.get("skins") if isinstance(document.get("skins"), list) else []
    animations = document.get("animations") if isinstance(document.get("animations"), list) else []
    materials = document.get("materials") if isinstance(document.get("materials"), list) else []
    images = document.get("images") if isinstance(document.get("images"), list) else []
    extensions = document.get("extensions") if isinstance(document.get("extensions"), dict) else {}

    node_names = [str(node.get("name")) for node in nodes
                  if isinstance(node, dict) and node.get("name")]
    fitted_assets = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        extras = node.get("extras") if isinstance(node.get("extras"), dict) else {}
        category = extras.get("jnsq_fit_category")
        name = extras.get("jnsq_fit_asset_name")
        source_sha256 = extras.get("jnsq_fit_source_sha256")
        morph_targets = extras.get("jnsq_fit_morph_targets")
        if not isinstance(category, str) or not isinstance(name, str):
            continue
        if (not isinstance(source_sha256, str) or
                len(source_sha256) != 64):
            continue
        fitted_assets.append({
            "node": str(node.get("name") or name),
            "category": category,
            "name": name,
            "source_sha256": source_sha256,
            "morph_targets": (
                int(morph_targets)
                if isinstance(morph_targets, (int, float)) else 0),
            "rigged": bool(extras.get("jnsq_fit_rigged", False)),
        })
    morph_names: List[str] = []
    primitive_count = 0
    morph_target_count = 0
    for mesh in meshes:
        if not isinstance(mesh, dict):
            continue
        extras = mesh.get("extras") if isinstance(mesh.get("extras"), dict) else {}
        morph_names.extend(str(name) for name in extras.get("targetNames", [])
                           if isinstance(name, str))
        primitives = mesh.get("primitives") if isinstance(mesh.get("primitives"), list) else []
        primitive_count += len(primitives)
        for primitive in primitives:
            if isinstance(primitive, dict) and isinstance(primitive.get("targets"), list):
                morph_target_count += len(primitive["targets"])

    roles = _match_candidates(node_names, ROLE_ALIASES)
    expressions = _match_candidates(morph_names, EXPRESSION_ALIASES)
    vrm = "VRMC_vrm" in extensions or "VRM" in extensions
    has_head = "head" in roles
    has_eyes = "left_eye" in roles and "right_eye" in roles
    has_blink = ("blink" in expressions or
                 ("blink_left" in expressions and "blink_right" in expressions))
    has_mouth = "mouth_open" in expressions or "jaw" in roles

    capabilities = {
        "body_motion": "candidate" if skins else "unavailable",
        "gaze": ("candidate_eyes" if has_eyes else
                 "candidate_head" if has_head else "needs_mapping"),
        "first_person": "declared" if vrm else ("candidate" if has_head else "needs_mapping"),
        "blink": "candidate" if has_blink else "unavailable",
        "speech_mouth": "candidate" if has_mouth else "unavailable",
        "wardrobe_rigging": (
            "fitted_candidate" if skins and fitted_assets else
            "candidate" if skins else "rigid_attachments_only"),
        "fitted_assets": (
            "observed" if fitted_assets else "none_observed"),
    }
    limitations = []
    if not skins:
        limitations.append("No skin was declared; skeletal animation and rigged garments are unavailable.")
    if not has_head:
        limitations.append("No head role was inferred; optical origin needs explicit mapping.")
    if not morph_names:
        limitations.append("No named morph targets were observed; facial expression cannot be inferred.")

    asset = document.get("asset") if isinstance(document.get("asset"), dict) else {}
    return {
        "inspection": "read_only",
        "asset": {"filename": os.path.basename(path), "bytes": size,
                  "sha256": sha256, "gltf_version": asset.get("version"),
                  "generator": asset.get("generator")},
        "structure": {"nodes": len(nodes), "meshes": len(meshes),
                      "primitives": primitive_count, "skins": len(skins),
                      "animations": len(animations), "materials": len(materials),
                      "images": len(images), "morph_targets": morph_target_count,
                      "named_morph_targets": sorted(set(morph_names))},
        "mapping_options": {"nodes": sorted(set(node_names)),
                            "morph_targets": sorted(set(morph_names))},
        "fitted_assets": fitted_assets,
        "standards": {"vrm": vrm,
                      "extensions_used": document.get("extensionsUsed", [])},
        "role_candidates": roles,
        "expression_candidates": expressions,
        "capabilities": capabilities,
        "limitations": limitations,
    }


def validate_manifest(data: Mapping[str, Any]) -> dict:
    """Validate the minimal jnsq-body/0.1 manifest without touching assets."""
    if not isinstance(data, Mapping):
        raise BodyPackageError("body manifest must be an object")
    unknown_format = data.get("format")
    if unknown_format != BODY_FORMAT:
        raise BodyPackageError(f"unsupported body format {unknown_format!r}")
    model = data.get("model")
    if not isinstance(model, str) or not model.strip():
        raise BodyPackageError("body manifest requires a model filename")
    if os.path.isabs(model) or ".." in model.replace("\\", "/").split("/"):
        raise BodyPackageError("body model must remain inside its package")
    if not model.casefold().endswith(".glb"):
        raise BodyPackageError("jnsq-body/0.1 requires a GLB model")
    roles = data.get("roles", {})
    expressions = data.get("expressions", {})
    attachment_points = data.get("attachment_points", {})
    capabilities = data.get("capabilities", {})
    for label, value in (("roles", roles), ("expressions", expressions),
                         ("attachment_points", attachment_points),
                         ("capabilities", capabilities)):
        if not isinstance(value, Mapping):
            raise BodyPackageError(f"{label} must be an object")
    height = data.get("height_m")
    if height is not None and (isinstance(height, bool) or
                               not isinstance(height, (int, float)) or
                               not 0.05 <= float(height) <= 20.0):
        raise BodyPackageError("height_m must be between 0.05 and 20 metres")
    return {
        "format": BODY_FORMAT,
        "model": model.replace("\\", "/"),
        "height_m": float(height) if height is not None else None,
        "roles": dict(roles),
        "expressions": dict(expressions),
        "attachment_points": dict(attachment_points),
        "capabilities": dict(capabilities),
    }


def inspect_body_package(package_dir: str) -> dict:
    """Validate body.json and inspect its GLB without installing either."""
    manifest_path = os.path.join(package_dir, "body.json")
    if not os.path.isfile(manifest_path):
        raise BodyPackageError("body package has no body.json manifest")
    if os.path.getsize(manifest_path) > MAX_MANIFEST_BYTES:
        raise BodyPackageError("body manifest exceeds inspection limit")
    with open(manifest_path, encoding="utf-8") as handle:
        try:
            manifest = validate_manifest(json.load(handle))
        except json.JSONDecodeError as exc:
            raise BodyPackageError(f"body manifest is invalid JSON: {exc}") from exc
    root = os.path.realpath(package_dir)
    model_path = os.path.realpath(os.path.join(root, manifest["model"]))
    if os.path.commonpath((root, model_path)) != root:
        raise BodyPackageError("body model resolves outside its package")
    if not os.path.isfile(model_path):
        raise BodyPackageError(f"body model {manifest['model']!r} does not exist")
    report = inspect_glb(model_path)
    report["manifest"] = manifest
    return report

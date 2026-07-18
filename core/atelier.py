"""Persona-private, append-only creative artifacts.

The atelier owns durable creative history, not model inference.  Renderers may
propose an artifact, but this boundary validates the medium, stores immutable
bytes under a content address, and records what actually happened.  Nothing
is published, messaged, installed, or promoted into autobiographical memory.

AT1 begins with a deliberately small SVG vocabulary.  SVG is executable XML
in a browser, so accepting a syntactically valid document is not enough: the
host rejects active content, remote references, CSS, animation, and unknown
elements/attributes before the artifact can be displayed.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
from xml.etree import ElementTree as ET


SVG_NS = "http://www.w3.org/2000/svg"
MAX_BRIEF_CHARS = 6000
MAX_LABEL_CHARS = 260
MAX_SVG_CHARS = 120_000
MAX_ELEMENTS = 1200
MAX_TEXT_CHARS = 4000
MAX_ATTRIBUTE_CHARS = 40_000
ARTIFACT_RE = re.compile(r"^svg_[0-9a-f]{16}$")
SAFE_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,79}$")
NUMBER_RE = re.compile(r"^[+]?(?:\d+(?:\.\d*)?|\.\d+)(?:px)?$")
LOCAL_URL_RE = re.compile(r"^url\(#[A-Za-z][A-Za-z0-9_.:-]{0,79}\)$")

SAFE_TAGS = frozenset({
    "svg", "g", "defs", "path", "rect", "circle", "ellipse", "line",
    "polyline", "polygon", "text", "tspan", "linearGradient",
    "radialGradient", "stop", "clipPath",
})
SAFE_ATTRIBUTES = frozenset({
    "id", "viewBox", "width", "height", "x", "y", "x1", "y1", "x2",
    "y2", "cx", "cy", "r", "rx", "ry", "d", "points", "fill",
    "fill-opacity", "stroke", "stroke-width", "stroke-opacity",
    "stroke-linecap", "stroke-linejoin", "stroke-dasharray", "opacity",
    "transform", "gradientUnits", "gradientTransform", "offset",
    "stop-color", "stop-opacity", "clip-path", "preserveAspectRatio",
    "font-family", "font-size", "font-weight", "text-anchor",
    "dominant-baseline", "dx", "dy",
})
URI_ATTRIBUTES = frozenset({"fill", "stroke", "clip-path"})
TEXT_TAGS = frozenset({"text", "tspan"})


def _sha(value: str | bytes) -> str:
    raw = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _digest(value: Any) -> str:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True,
                          default=str, separators=(",", ":"))
    return _sha(rendered)[:16]


def _bounded(value: Any, *, name: str, maximum: int,
             allow_empty: bool = False) -> str:
    text = str(value or "").strip()
    if not text and not allow_empty:
        raise ValueError(f"{name} must not be empty")
    if len(text) > maximum:
        raise ValueError(f"{name} exceeds the {maximum}-character boundary")
    return text


def _local_name(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("SVG contains an unsupported XML node")
    if value.startswith("{"):
        namespace, _, local = value[1:].partition("}")
        if namespace != SVG_NS:
            raise ValueError("SVG contains a foreign XML namespace")
        return local
    return value


def _finite_number(value: str, *, name: str) -> float:
    raw = str(value or "").strip()
    if not NUMBER_RE.fullmatch(raw):
        raise ValueError(f"SVG {name} must be a finite number or px value")
    number = float(raw[:-2] if raw.endswith("px") else raw)
    if not math.isfinite(number):
        raise ValueError(f"SVG {name} must be finite")
    return number


def _reject_active_value(name: str, value: str) -> None:
    folded = value.casefold().replace(" ", "")
    if any(marker in folded for marker in (
            "javascript:", "data:", "vbscript:", "@import", "http://",
            "https://", "//")):
        raise ValueError(f"SVG attribute {name} contains an external or active value")
    if "url(" in folded:
        if name not in URI_ATTRIBUTES or not LOCAL_URL_RE.fullmatch(value.strip()):
            raise ValueError(f"SVG attribute {name} contains a non-local URL")


def sanitize_svg(svg: str) -> dict:
    """Return a canonical inert SVG and a content-free validation receipt."""
    source = _bounded(svg, name="SVG artifact", maximum=MAX_SVG_CHARS)
    lowered = source.casefold()
    if any(marker in lowered for marker in (
            "<!doctype", "<!entity", "<?xml-stylesheet", "<script",
            "<foreignobject", "<iframe", "<object", "<embed")):
        raise ValueError("SVG contains an active or unsupported XML construct")
    try:
        root = ET.fromstring(source, parser=ET.XMLParser())
    except ET.ParseError as exc:
        raise ValueError(f"SVG is not well-formed XML: {exc}") from exc
    if _local_name(root.tag) != "svg":
        raise ValueError("SVG document root must be <svg>")

    elements = list(root.iter())
    if len(elements) > MAX_ELEMENTS:
        raise ValueError(f"SVG exceeds the {MAX_ELEMENTS}-element boundary")
    ids = set()
    local_references = []
    text_chars = 0
    for element in elements:
        tag = _local_name(element.tag)
        if tag not in SAFE_TAGS:
            raise ValueError(f"SVG element <{tag}> is not admitted")
        if element.text:
            if tag not in TEXT_TAGS and element.text.strip():
                raise ValueError(f"SVG element <{tag}> contains stray text")
            text_chars += len(element.text)
        if element.tail:
            text_chars += len(element.tail)
        if text_chars > MAX_TEXT_CHARS:
            raise ValueError(
                f"SVG text exceeds the {MAX_TEXT_CHARS}-character boundary")
        for raw_name, raw_value in element.attrib.items():
            name = _local_name(raw_name)
            value = str(raw_value or "").strip()
            if name not in SAFE_ATTRIBUTES:
                raise ValueError(f"SVG attribute {name!r} is not admitted")
            if len(value) > MAX_ATTRIBUTE_CHARS:
                raise ValueError(f"SVG attribute {name!r} is too large")
            _reject_active_value(name, value)
            if name == "id":
                if not SAFE_ID_RE.fullmatch(value) or value in ids:
                    raise ValueError("SVG ids must be unique safe identifiers")
                ids.add(value)
            if "url(" in value.casefold():
                local_references.append(value.strip()[5:-1])
        # Canonical standalone SVG always carries the SVG namespace, even if
        # a model omitted xmlns on otherwise safe input.
        element.tag = f"{{{SVG_NS}}}{tag}"

    missing = sorted(set(local_references) - ids)
    if missing:
        raise ValueError(f"SVG references missing local ids: {missing}")
    view_box = str(root.attrib.get("viewBox") or "").split()
    if len(view_box) != 4:
        raise ValueError("SVG root requires a four-number viewBox")
    try:
        view_values = [float(value) for value in view_box]
    except ValueError as exc:
        raise ValueError("SVG viewBox must contain four finite numbers") from exc
    if not all(math.isfinite(value) for value in view_values) \
            or view_values[2] <= 0 or view_values[3] <= 0:
        raise ValueError("SVG viewBox dimensions must be finite and positive")

    width = (_finite_number(root.attrib["width"], name="width")
             if "width" in root.attrib else view_values[2])
    height = (_finite_number(root.attrib["height"], name="height")
              if "height" in root.attrib else view_values[3])
    if not 16 <= width <= 4096 or not 16 <= height <= 4096:
        raise ValueError("SVG canvas dimensions must be between 16 and 4096")
    root.set("width", f"{width:g}")
    root.set("height", f"{height:g}")
    ET.register_namespace("", SVG_NS)
    canonical = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    if not canonical.endswith("\n"):
        canonical += "\n"
    encoded = canonical.encode("utf-8")
    return {
        "svg": canonical,
        "sha256": _sha(encoded),
        "bytes": len(encoded),
        "elements": len(elements),
        "width": width,
        "height": height,
    }


class Atelier:
    """One persona's admitted prompts, immutable artifacts, and receipts."""

    def __init__(self, persona_dir: str | os.PathLike[str], *, now_fn=time.time):
        self.root = Path(persona_dir).resolve() / "body" / "atelier"
        self.seeds = self.root / "seeds"
        self.artifacts = self.root / "artifacts"
        self.index = self.root / "index.jsonl"
        self.receipts = self.root / "receipts.jsonl"
        self.now_fn = now_fn
        self._lock = threading.RLock()

    def _ensure(self) -> None:
        self.seeds.mkdir(parents=True, exist_ok=True)
        self.artifacts.mkdir(parents=True, exist_ok=True)

    def _append(self, path: Path, value: Mapping[str, Any]) -> dict:
        self._ensure()
        record = dict(value)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False,
                                    sort_keys=True) + "\n")
        return record

    @staticmethod
    def _read_records(path: Path, limit: int = 2000) -> list[dict]:
        if not path.is_file():
            return []
        found = []
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    value = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if isinstance(value, dict):
                    found.append(value)
        return [dict(value) for value in found[-max(1, min(int(limit), 4000)):]]

    def records(self, *, kind: str | None = None, limit: int = 500) -> list[dict]:
        with self._lock:
            values = self._read_records(self.index)
        if kind is not None:
            values = [value for value in values if value.get("kind") == kind]
        return values[-max(1, min(int(limit), 1000)):]

    def receipt_records(self, limit: int = 50) -> list[dict]:
        with self._lock:
            return self._read_records(self.receipts, limit=limit)

    def _action_for_run(self, run_id: str) -> dict | None:
        return next((record for record in reversed(self.records(limit=1000))
                     if record.get("run_id") == run_id), None)

    def admit_seed(self, label: str, brief: str) -> dict:
        label = _bounded(label, name="atelier seed label", maximum=MAX_LABEL_CHARS)
        brief = _bounded(brief, name="atelier seed brief", maximum=MAX_BRIEF_CHARS)
        source_digest = _digest({"label": label.casefold(), "brief": brief})
        seed_id = f"seed_{source_digest}"
        with self._lock:
            existing = next((record for record in self.records(
                kind="seed_admitted", limit=1000)
                if record.get("seed_id") == seed_id), None)
            if existing:
                return {**existing, "duplicate": True}
            self._ensure()
            path = self.seeds / f"{seed_id}.txt"
            path.write_bytes(brief.encode("utf-8"))
            record = self._append(self.index, {
                "kind": "seed_admitted", "seed_id": seed_id,
                "label": label, "ref": f"seeds/{path.name}",
                "chars": len(brief), "sha256": _sha(brief),
                "source_digest": source_digest,
                "ownership": "human_admitted",
                "created_at": float(self.now_fn()),
            })
            return {**record, "duplicate": False}

    def _safe_ref(self, ref: str, collection: str) -> Path:
        pure = PurePosixPath(str(ref or "").replace("\\", "/"))
        if pure.is_absolute() or ".." in pure.parts or len(pure.parts) != 2 \
                or pure.parts[0] != collection:
            raise ValueError("atelier reference escaped its boundary")
        folder = self.root / collection
        path = (folder / pure.parts[1]).resolve()
        if path.parent != folder.resolve():
            raise ValueError("atelier reference escaped its collection")
        return path

    def seed(self, seed_id: str, *, include_brief: bool = False) -> dict:
        record = next((record for record in self.records(
            kind="seed_admitted", limit=1000)
            if record.get("seed_id") == str(seed_id)), None)
        if record is None:
            raise ValueError("atelier seed does not exist")
        value = dict(record)
        if include_brief:
            value["brief"] = self._safe_ref(
                value["ref"], "seeds").read_text(encoding="utf-8")
        return value

    def pending_seeds(self) -> list[dict]:
        resolved = {record.get("seed_id") for record in self.records(
            kind="seed_resolved", limit=1000)}
        return [record for record in self.records(
            kind="seed_admitted", limit=1000)
            if record.get("seed_id") not in resolved]

    def resolve_seed(self, seed_id: str, run_id: str, outcome: str, *,
                     artifact_id: str | None = None) -> dict:
        self.seed(seed_id)
        run_id = _bounded(run_id, name="atelier run id", maximum=160)
        outcome = _bounded(outcome, name="atelier seed outcome", maximum=80)
        with self._lock:
            existing = next((record for record in self.records(
                kind="seed_resolved", limit=1000)
                if record.get("seed_id") == seed_id), None)
            if existing:
                return existing
            return self._append(self.index, {
                "kind": "seed_resolved", "seed_id": seed_id,
                "run_id": run_id, "outcome": outcome,
                "artifact_id": artifact_id,
                "ownership": "persona_private",
                "resolved_at": float(self.now_fn()),
            })

    def create_svg(self, run_id: str, title: str, svg: str, *,
                   source: Mapping[str, Any], expression_vector=None) -> dict:
        run_id = _bounded(run_id, name="atelier run id", maximum=160)
        title = _bounded(title, name="atelier artifact title",
                         maximum=MAX_LABEL_CHARS)
        source = dict(source or {})
        source_digest = _bounded(
            source.get("source_digest") or _digest(source),
            name="atelier source digest", maximum=80)
        source["source_digest"] = source_digest
        validated = sanitize_svg(svg)
        artifact_id = f"svg_{validated['sha256'][:16]}"
        vector = {
            str(key)[:80]: round(max(0.0, min(1.0, float(value))), 6)
            for key, value in dict(expression_vector or {}).items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value))
        }
        with self._lock:
            if self._action_for_run(run_id):
                raise ValueError("this atelier run already committed an action")
            prior = next((record for record in self.records(limit=2000)
                          if record.get("artifact_id") == artifact_id
                          and record.get("kind") in {
                              "artifact_created", "artifact_reused"}), None)
            if prior:
                return {**self._append(self.index, {
                    "kind": "artifact_reused", "artifact_id": artifact_id,
                    "run_id": run_id, "title": title, "medium": "svg",
                    "ref": prior["ref"], "sha256": validated["sha256"],
                    "bytes": prior.get("bytes", validated["bytes"]),
                    "elements": prior.get("elements", validated["elements"]),
                    "width": prior.get("width", validated["width"]),
                    "height": prior.get("height", validated["height"]),
                    "source": source, "expression_vector": vector,
                    "ownership": "persona_private",
                    "created_at": float(self.now_fn()),
                }), "duplicate": True}
            self._ensure()
            path = self.artifacts / f"{artifact_id}.svg"
            # Write the canonical bytes directly.  Text-mode newline
            # translation on Windows would otherwise make the durable file
            # disagree with the content hash computed by the validator.
            path.write_bytes(validated["svg"].encode("utf-8"))
            record = self._append(self.index, {
                "kind": "artifact_created", "artifact_id": artifact_id,
                "run_id": run_id, "title": title, "medium": "svg",
                "ref": f"artifacts/{path.name}",
                "sha256": validated["sha256"],
                "bytes": validated["bytes"],
                "elements": validated["elements"],
                "width": validated["width"], "height": validated["height"],
                "source": source, "expression_vector": vector,
                "ownership": "persona_private",
                "created_at": float(self.now_fn()),
            })
            return {**record, "duplicate": False}

    def artifacts_status(self) -> list[dict]:
        latest = {}
        for record in self.records(limit=2000):
            if record.get("kind") in {"artifact_created", "artifact_reused"}:
                latest[record.get("artifact_id")] = record
        return sorted((dict(value) for value in latest.values()), key=lambda value: (
            -float(value.get("created_at") or 0.0), value["artifact_id"]))

    def artifact(self, artifact_id: str, *, include_svg: bool = False) -> dict:
        if not ARTIFACT_RE.fullmatch(str(artifact_id or "")):
            raise ValueError("atelier artifact id is invalid")
        value = next((item for item in self.artifacts_status()
                      if item.get("artifact_id") == artifact_id), None)
        if value is None:
            raise ValueError("atelier artifact does not exist")
        result = dict(value)
        path = self._safe_ref(result["ref"], "artifacts")
        if not path.is_file() or _sha(path.read_bytes()) != result["sha256"]:
            raise ValueError("atelier artifact failed its integrity check")
        if include_svg:
            result["svg"] = path.read_text(encoding="utf-8")
        return result

    def artifact_path(self, artifact_id: str) -> Path:
        artifact = self.artifact(artifact_id)
        return self._safe_ref(artifact["ref"], "artifacts")

    def record_receipt(self, record: Mapping[str, Any]) -> dict:
        allowed = {
            "kind", "run_id", "candidate_key", "outcome", "reason",
            "artifact_id", "seed_id", "medium", "model", "provider",
            "locality", "model_requests", "provider_http_attempts",
            "input_tokens", "output_tokens", "total_tokens",
            "estimated_cost_usd", "readiness", "source_satiety",
            "atelier_satiety", "created_at",
        }
        value = {key: item for key, item in dict(record or {}).items()
                 if key in allowed and item is not None}
        value.setdefault("kind", "atelier_run")
        value.setdefault("created_at", float(self.now_fn()))
        with self._lock:
            return self._append(self.receipts, value)

    def status(self) -> dict:
        return {
            "root": "body/atelier",
            "pending_seeds": self.pending_seeds(),
            "artifacts": self.artifacts_status(),
            "receipts": self.receipt_records(limit=30),
            "media": ["svg"],
            "policy": {
                "create": "one validated private artifact per field win",
                "active_svg": False,
                "remote_references": False,
                "overwrite": False,
                "delete": False,
                "publish": False,
                "message": False,
                "external_effects": False,
            },
        }

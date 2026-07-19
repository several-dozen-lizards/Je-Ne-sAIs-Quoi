"""Persona-private, append-only creative artifacts.

The atelier owns durable creative history, not model inference.  Renderers may
propose an artifact, but this boundary validates the medium, stores immutable
bytes under a content address, and records what actually happened.  Nothing
is published, messaged, installed, or promoted into autobiographical memory.

AT1 begins with a deliberately small SVG vocabulary. SVG is executable XML
in a browser, so accepting a syntactically valid document is not enough: the
host rejects active content, remote references, CSS, animation, and unknown
elements/attributes before the artifact can be displayed.

AT3 preserves that static wall, then lets the host—not the model—compile a
small normalized motion graph into bounded, closed SMIL cycles.

AT4 admits a data-only Canvas scene graph. The durable artifact contains
validated geometry and host-derived cyclic parameters; trusted cockpit code
owns every Canvas API call and animation frame.

AT5 admits a data-only procedural score. The model can describe bounded
musical relationships, while the host compiles body-coupled pitch, timing,
dynamics, and recurrence. Trusted cockpit code owns every Web Audio node.

AT6 admits a data-only 3D scene graph. The model chooses bounded primitives,
transforms, materials, lights, and camera relationships; the host owns mesh
generation, matrices, shaders, WebGL calls, and cyclic motion.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import struct
import threading
import time
import zlib
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
MAX_MOTIONS = 12
MAX_CANVAS_NODES = 80
MAX_CANVAS_POINTS = 48
MAX_CANVAS_PARTICLES = 240
MAX_CANVAS_TOTAL_PARTICLES = 600
MAX_CANVAS_TEXT_CHARS = 180
MAX_CANVAS_BYTES = 160_000
MAX_AUDIO_VOICES = 6
MAX_AUDIO_EVENTS = 96
MAX_AUDIO_BYTES = 160_000
MAX_3D_OBJECTS = 24
MAX_3D_LIGHTS = 3
MAX_3D_BYTES = 180_000
MAX_RASTER_BYTES = 32 * 1024 * 1024
MAX_RASTER_PIXELS = 4096 * 4096
ARTIFACT_RE = re.compile(r"^(?:svg|canvas|audio|scene3d|png|webp)_[0-9a-f]{16}$")
SAFE_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,79}$")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
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
MOTION_TARGET_TAGS = frozenset({
    "g", "path", "rect", "circle", "ellipse", "line", "polyline",
    "polygon", "text", "tspan",
})
MOTION_CHANNELS = frozenset({"translate", "rotate", "opacity"})
MOTION_FIELDS = frozenset({
    "target", "channel", "intensity", "rate", "phase", "x", "y",
})
HOST_MOTION_TAGS = frozenset({"animate", "animateTransform"})
HOST_MOTION_ATTRIBUTES = frozenset({
    "attributeName", "type", "values", "dur", "repeatCount", "additive",
    "calcMode", "keyTimes",
})
MOTION_KEY_TIMES = "0;0.125;0.25;0.375;0.5;0.625;0.75;0.875;1"
CANVAS_SCENE_FIELDS = frozenset({"aspect", "background", "nodes"})
CANVAS_NODE_FIELDS = {
    "circle": frozenset({
        "id", "kind", "x", "y", "radius", "fill", "stroke",
        "line_width", "opacity",
    }),
    "rect": frozenset({
        "id", "kind", "x", "y", "width", "height", "corner", "fill",
        "stroke", "line_width", "opacity", "rotation",
    }),
    "path": frozenset({
        "id", "kind", "points", "closed", "fill", "stroke",
        "line_width", "opacity",
    }),
    "text": frozenset({
        "id", "kind", "x", "y", "text", "fill", "font_size", "align",
        "opacity", "rotation",
    }),
    "particles": frozenset({
        "id", "kind", "x", "y", "width", "height", "count", "radius",
        "fill", "opacity", "seed",
    }),
}
CANVAS_MOTION_CHANNELS = frozenset({
    "translate", "rotate", "scale", "opacity", "orbit",
})
AUDIO_SCORE_FIELDS = frozenset({
    "tempo", "beats", "tonic", "scale", "seed", "voices", "events",
})
AUDIO_VOICE_FIELDS = frozenset({
    "id", "wave", "gain", "attack", "release", "pan", "filter",
})
AUDIO_EVENT_FIELDS = frozenset({
    "voice", "beat", "duration", "degree", "octave", "velocity",
    "probability",
})
AUDIO_WAVES = frozenset({"sine", "triangle", "sawtooth", "square"})
AUDIO_SCALES = {
    "major_pentatonic": (0, 2, 4, 7, 9),
    "minor_pentatonic": (0, 3, 5, 7, 10),
    "dorian": (0, 2, 3, 5, 7, 9, 10),
    "mixolydian": (0, 2, 4, 5, 7, 9, 10),
    "harmonic_minor": (0, 2, 3, 5, 7, 8, 11),
    "whole_tone": (0, 2, 4, 6, 8, 10),
}
SCENE3D_FIELDS = frozenset({
    "background", "camera", "ambient", "lights", "objects",
})
SCENE3D_CAMERA_FIELDS = frozenset({
    "x", "y", "z", "target_x", "target_y", "target_z", "fov",
})
SCENE3D_LIGHT_FIELDS = frozenset({
    "x", "y", "z", "color", "intensity",
})
SCENE3D_OBJECT_FIELDS = frozenset({
    "id", "kind", "x", "y", "z", "scale_x", "scale_y", "scale_z",
    "rotation_x", "rotation_y", "rotation_z", "color", "roughness",
    "metallic", "opacity",
})
SCENE3D_KINDS = frozenset({"sphere", "box", "torus", "plane"})
SCENE3D_MOTION_CHANNELS = frozenset({
    "translate", "rotate", "scale", "opacity", "orbit",
})
SCENE3D_TRIANGLES = {
    "sphere": 432, "box": 12, "torus": 576, "plane": 2,
}


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


def _sanitize_svg(svg: str, *, host_motion: bool = False) -> dict:
    """Canonicalize inert SVG, optionally admitting host-compiled SMIL."""
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
    motion_count = 0
    for element in elements:
        tag = _local_name(element.tag)
        if tag not in SAFE_TAGS and not (host_motion and tag in HOST_MOTION_TAGS):
            raise ValueError(f"SVG element <{tag}> is not admitted")
        if tag in HOST_MOTION_TAGS:
            motion_count += 1
            if motion_count > MAX_MOTIONS:
                raise ValueError(f"SVG exceeds the {MAX_MOTIONS}-motion boundary")
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
            if name not in SAFE_ATTRIBUTES and not (
                    host_motion and tag in HOST_MOTION_TAGS
                    and name in HOST_MOTION_ATTRIBUTES):
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
        if tag in HOST_MOTION_TAGS:
            attrs = {_local_name(name): str(value) for name, value
                     in element.attrib.items()}
            common = {
                "values", "dur", "repeatCount", "calcMode", "keyTimes",
                "attributeName",
            }
            expected = (common | {"type", "additive"}
                        if tag == "animateTransform" else common)
            if set(attrs) != expected:
                raise ValueError("host SVG motion has an invalid attribute shape")
            if attrs["repeatCount"] != "indefinite" \
                    or attrs["calcMode"] != "linear" \
                    or attrs["keyTimes"] != MOTION_KEY_TIMES \
                    or not re.fullmatch(r"(?:\d+(?:\.\d+)?|\.\d+)s", attrs["dur"]):
                raise ValueError("host SVG motion is not a bounded cyclic motion")
            if tag == "animateTransform":
                if attrs["attributeName"] != "transform" \
                        or attrs["type"] not in {"translate", "rotate"} \
                        or attrs["additive"] != "sum":
                    raise ValueError("host SVG transform motion is invalid")
            elif attrs["attributeName"] != "opacity":
                raise ValueError("host SVG scalar motion is invalid")
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


def sanitize_svg(svg: str) -> dict:
    """Return canonical inert SVG; model-authored animation is never admitted."""
    return _sanitize_svg(svg, host_motion=False)


def _unit(value: Any, *, name: str, signed: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"kinetic SVG {name} must be numeric")
    number = float(value)
    low = -1.0 if signed else 0.0
    if not math.isfinite(number) or not low <= number <= 1.0:
        boundary = "-1 through 1" if signed else "0 through 1"
        raise ValueError(f"kinetic SVG {name} must be {boundary}")
    return number


def _motion_samples(phase: float) -> list[float]:
    """Nine points around a closed sine cycle, rotated by normalized phase."""
    return [math.sin((phase + index / 8.0) * math.tau)
            for index in range(9)]


def _numbers(values) -> str:
    return ";".join("0" if abs(value) < 0.0005 else f"{value:.3f}".rstrip("0").rstrip(".")
                    for value in values)


def compose_kinetic_svg(svg: str, motions, expression_vector=None) -> dict:
    """Compile normalized motion descriptors into a bounded cyclic SVG.

    The untrusted SVG is first forced through the static sanitizer. Only then
    does the host add its own tiny SMIL vocabulary. This keeps JavaScript,
    model-authored animation, timing expressions, and external references out
    of the artifact boundary.
    """
    base = sanitize_svg(svg)
    if not isinstance(motions, list) or not 1 <= len(motions) <= MAX_MOTIONS:
        raise ValueError(f"kinetic SVG requires 1 through {MAX_MOTIONS} motions")
    root = ET.fromstring(base["svg"], parser=ET.XMLParser())
    by_id = {}
    for element in root.iter():
        element_id = element.attrib.get("id")
        if element_id:
            by_id[element_id] = element
    view_box = [float(value) for value in root.attrib["viewBox"].split()]
    center_x = view_box[0] + view_box[2] / 2.0
    center_y = view_box[1] + view_box[3] / 2.0
    vector = {str(key): max(0.0, min(1.0, float(value)))
              for key, value in dict(expression_vector or {}).items()
              if isinstance(value, (int, float)) and not isinstance(value, bool)
              and math.isfinite(float(value))}
    coherence = vector.get("band.coherence", .5)
    gamma = vector.get("band.gamma", .5)
    curiosity = vector.get("cocktail.curiosity", .5)
    drive = .42 * gamma + .33 * curiosity + .25 * (1.0 - coherence)
    base_period = 3.0 + 7.0 * (1.0 - drive)
    body_scale = .55 + .75 * (
        .5 * gamma + .3 * curiosity + .2 * coherence)
    span = min(view_box[2], view_box[3])
    seen = set()
    periods = []
    normalized = []
    for index, raw in enumerate(motions):
        if not isinstance(raw, dict) or set(raw) != MOTION_FIELDS:
            raise ValueError("kinetic SVG motion must contain the exact motion shape")
        target_id = str(raw.get("target") or "").strip()
        channel = str(raw.get("channel") or "").strip().casefold()
        target = by_id.get(target_id)
        target_tag = _local_name(target.tag) if target is not None else ""
        if not SAFE_ID_RE.fullmatch(target_id) or target_tag not in MOTION_TARGET_TAGS:
            raise ValueError(f"kinetic SVG target {target_id!r} is not an admitted visible id")
        if channel not in MOTION_CHANNELS:
            raise ValueError(f"kinetic SVG channel {channel!r} is not admitted")
        if (target_id, channel) in seen:
            raise ValueError("kinetic SVG target/channel pairs must be unique")
        seen.add((target_id, channel))
        intensity = _unit(raw["intensity"], name=f"motion {index} intensity")
        rate = _unit(raw["rate"], name=f"motion {index} rate")
        phase = _unit(raw["phase"], name=f"motion {index} phase")
        x = _unit(raw["x"], name=f"motion {index} x", signed=True)
        y = _unit(raw["y"], name=f"motion {index} y", signed=True)
        period = base_period / (.65 + .85 * rate)
        periods.append(period)
        samples = _motion_samples(phase)
        common = {
            "dur": f"{period:.3f}s", "repeatCount": "indefinite",
            "calcMode": "linear", "keyTimes": MOTION_KEY_TIMES,
        }
        if channel == "translate":
            amplitude = .055 * span * body_scale * intensity
            values = ";".join(
                f"{x * amplitude * sample:.3f} {y * amplitude * sample:.3f}"
                for sample in samples)
            ET.SubElement(target, f"{{{SVG_NS}}}animateTransform", {
                "attributeName": "transform", "type": "translate",
                "values": values, "additive": "sum", **common,
            })
        elif channel == "rotate":
            direction = x if abs(x) >= .05 else 1.0
            amplitude = 18.0 * body_scale * intensity * direction
            values = ";".join(
                f"{amplitude * sample:.3f} {center_x:.3f} {center_y:.3f}"
                for sample in samples)
            ET.SubElement(target, f"{{{SVG_NS}}}animateTransform", {
                "attributeName": "transform", "type": "rotate",
                "values": values, "additive": "sum", **common,
            })
        else:
            depth = min(.78, .58 * body_scale * intensity)
            values = _numbers(1.0 - depth * abs(sample) for sample in samples)
            ET.SubElement(target, f"{{{SVG_NS}}}animate", {
                "attributeName": "opacity", "values": values, **common,
            })
        normalized.append({
            "target": target_id, "channel": channel,
            "intensity": round(intensity, 6), "rate": round(rate, 6),
            "phase": round(phase, 6), "x": round(x, 6), "y": round(y, 6),
        })
    compiled = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    validated = _sanitize_svg(compiled, host_motion=True)
    validated.update({
        "variant": "kinetic", "motion_count": len(normalized),
        "motion_digest": _digest(normalized),
        "base_period_seconds": round(base_period, 6),
        "period_seconds": [round(min(periods), 6), round(max(periods), 6)],
    })
    return validated


def _canvas_unit(value: Any, *, name: str, signed: bool = False,
                 positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Canvas {name} must be numeric")
    number = float(value)
    low = -1.0 if signed else 0.0
    if not math.isfinite(number) or not low <= number <= 1.0 \
            or (positive and number <= 0.0):
        boundary = "-1 through 1" if signed else "0 through 1"
        if positive:
            boundary = "greater than 0 through 1"
        raise ValueError(f"Canvas {name} must be {boundary}")
    return round(number, 6)


def _canvas_color(value: Any, *, name: str, empty: bool = False) -> str:
    color = str(value or "").strip()
    if empty and not color:
        return ""
    if not COLOR_RE.fullmatch(color):
        raise ValueError(f"Canvas {name} must be a six-digit hex color")
    return color.casefold()


def _canvas_vector(expression_vector) -> tuple[dict, float, float]:
    vector = {str(key): max(0.0, min(1.0, float(value)))
              for key, value in dict(expression_vector or {}).items()
              if isinstance(value, (int, float)) and not isinstance(value, bool)
              and math.isfinite(float(value))}
    coherence = vector.get("band.coherence", .5)
    gamma = vector.get("band.gamma", .5)
    curiosity = vector.get("cocktail.curiosity", .5)
    drive = .42 * gamma + .33 * curiosity + .25 * (1.0 - coherence)
    base_period = 3.0 + 7.0 * (1.0 - drive)
    body_scale = .55 + .75 * (
        .5 * gamma + .3 * curiosity + .2 * coherence)
    return vector, base_period, body_scale


def _validate_canvas_node(raw: Any, index: int) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"Canvas node {index} must be an object")
    kind = str(raw.get("kind") or "").strip().casefold()
    expected = CANVAS_NODE_FIELDS.get(kind)
    if expected is None or set(raw) != expected:
        raise ValueError(f"Canvas node {index} has an invalid exact shape")
    node_id = str(raw.get("id") or "").strip()
    if not SAFE_ID_RE.fullmatch(node_id):
        raise ValueError(f"Canvas node {index} id is not safe")
    node = {"id": node_id, "kind": kind}
    if kind == "circle":
        node.update({
            "x": _canvas_unit(raw["x"], name=f"node {index} x"),
            "y": _canvas_unit(raw["y"], name=f"node {index} y"),
            "radius": _canvas_unit(
                raw["radius"], name=f"node {index} radius", positive=True),
            "fill": _canvas_color(raw["fill"], name=f"node {index} fill",
                                  empty=True),
            "stroke": _canvas_color(
                raw["stroke"], name=f"node {index} stroke", empty=True),
            "line_width": _canvas_unit(
                raw["line_width"], name=f"node {index} line width"),
            "opacity": _canvas_unit(
                raw["opacity"], name=f"node {index} opacity"),
        })
    elif kind == "rect":
        node.update({
            "x": _canvas_unit(raw["x"], name=f"node {index} x"),
            "y": _canvas_unit(raw["y"], name=f"node {index} y"),
            "width": _canvas_unit(
                raw["width"], name=f"node {index} width", positive=True),
            "height": _canvas_unit(
                raw["height"], name=f"node {index} height", positive=True),
            "corner": _canvas_unit(raw["corner"], name=f"node {index} corner"),
            "fill": _canvas_color(raw["fill"], name=f"node {index} fill",
                                  empty=True),
            "stroke": _canvas_color(
                raw["stroke"], name=f"node {index} stroke", empty=True),
            "line_width": _canvas_unit(
                raw["line_width"], name=f"node {index} line width"),
            "opacity": _canvas_unit(
                raw["opacity"], name=f"node {index} opacity"),
            "rotation": _canvas_unit(
                raw["rotation"], name=f"node {index} rotation", signed=True),
        })
    elif kind == "path":
        points = raw.get("points")
        if not isinstance(points, list) or not 2 <= len(points) <= MAX_CANVAS_POINTS:
            raise ValueError(
                f"Canvas path {node_id!r} requires 2 through {MAX_CANVAS_POINTS} points")
        normalized_points = []
        for point_index, point in enumerate(points):
            if not isinstance(point, list) or len(point) != 2:
                raise ValueError("Canvas path points must be x/y pairs")
            normalized_points.append([
                _canvas_unit(point[0], name=f"node {index} point {point_index} x"),
                _canvas_unit(point[1], name=f"node {index} point {point_index} y"),
            ])
        if type(raw["closed"]) is not bool:
            raise ValueError("Canvas path closed must be a bool")
        node.update({
            "points": normalized_points, "closed": raw["closed"],
            "fill": _canvas_color(raw["fill"], name=f"node {index} fill",
                                  empty=True),
            "stroke": _canvas_color(
                raw["stroke"], name=f"node {index} stroke", empty=True),
            "line_width": _canvas_unit(
                raw["line_width"], name=f"node {index} line width"),
            "opacity": _canvas_unit(
                raw["opacity"], name=f"node {index} opacity"),
        })
    elif kind == "text":
        text = str(raw.get("text") or "")
        if not text.strip() or len(text) > MAX_CANVAS_TEXT_CHARS:
            raise ValueError(
                f"Canvas text must be 1 through {MAX_CANVAS_TEXT_CHARS} characters")
        align = str(raw.get("align") or "").strip().casefold()
        if align not in {"left", "center", "right"}:
            raise ValueError("Canvas text align must be left, center, or right")
        node.update({
            "x": _canvas_unit(raw["x"], name=f"node {index} x"),
            "y": _canvas_unit(raw["y"], name=f"node {index} y"),
            "text": text,
            "fill": _canvas_color(raw["fill"], name=f"node {index} fill"),
            "font_size": _canvas_unit(
                raw["font_size"], name=f"node {index} font size", positive=True),
            "align": align,
            "opacity": _canvas_unit(
                raw["opacity"], name=f"node {index} opacity"),
            "rotation": _canvas_unit(
                raw["rotation"], name=f"node {index} rotation", signed=True),
        })
    else:
        count = raw.get("count")
        if isinstance(count, bool) or not isinstance(count, int) \
                or not 1 <= count <= MAX_CANVAS_PARTICLES:
            raise ValueError(
                f"Canvas particles count must be 1 through {MAX_CANVAS_PARTICLES}")
        node.update({
            "x": _canvas_unit(raw["x"], name=f"node {index} x"),
            "y": _canvas_unit(raw["y"], name=f"node {index} y"),
            "width": _canvas_unit(
                raw["width"], name=f"node {index} width", positive=True),
            "height": _canvas_unit(
                raw["height"], name=f"node {index} height", positive=True),
            "count": count,
            "radius": _canvas_unit(
                raw["radius"], name=f"node {index} radius", positive=True),
            "fill": _canvas_color(raw["fill"], name=f"node {index} fill"),
            "opacity": _canvas_unit(
                raw["opacity"], name=f"node {index} opacity"),
            "seed": _canvas_unit(raw["seed"], name=f"node {index} seed"),
        })
    if not node.get("fill") and not node.get("stroke"):
        raise ValueError(f"Canvas node {node_id!r} must have visible fill or stroke")
    return node


def compile_canvas_scene(scene, motions, expression_vector=None) -> dict:
    """Validate a data-only scene and compile body-coupled cyclic parameters."""
    if not isinstance(scene, dict) or set(scene) != CANVAS_SCENE_FIELDS:
        raise ValueError("Canvas scene must contain exactly aspect, background, and nodes")
    aspect = scene.get("aspect")
    if isinstance(aspect, bool) or not isinstance(aspect, (int, float)) \
            or not math.isfinite(float(aspect)) or not .625 <= float(aspect) <= 1.6:
        raise ValueError("Canvas aspect must be between 0.625 and 1.6")
    aspect = round(float(aspect), 6)
    background = _canvas_color(scene.get("background"), name="background")
    raw_nodes = scene.get("nodes")
    if not isinstance(raw_nodes, list) \
            or not 1 <= len(raw_nodes) <= MAX_CANVAS_NODES:
        raise ValueError(
            f"Canvas scene requires 1 through {MAX_CANVAS_NODES} nodes")
    nodes = [_validate_canvas_node(raw, index)
             for index, raw in enumerate(raw_nodes)]
    particle_total = sum(
        node.get("count", 0) for node in nodes if node["kind"] == "particles")
    if particle_total > MAX_CANVAS_TOTAL_PARTICLES:
        raise ValueError(
            f"Canvas scene exceeds the {MAX_CANVAS_TOTAL_PARTICLES}-particle total boundary")
    node_ids = [node["id"] for node in nodes]
    if len(node_ids) != len(set(node_ids)):
        raise ValueError("Canvas node ids must be unique")
    if not isinstance(motions, list) or len(motions) > MAX_MOTIONS:
        raise ValueError(f"Canvas admits at most {MAX_MOTIONS} motions")
    _vector, base_period, body_scale = _canvas_vector(expression_vector)
    compiled_motions = []
    periods = []
    seen = set()
    for index, raw in enumerate(motions):
        if not isinstance(raw, dict) or set(raw) != MOTION_FIELDS:
            raise ValueError("Canvas motion must contain the exact motion shape")
        target = str(raw.get("target") or "").strip()
        channel = str(raw.get("channel") or "").strip().casefold()
        if target not in node_ids:
            raise ValueError(f"Canvas motion target {target!r} does not exist")
        if channel not in CANVAS_MOTION_CHANNELS:
            raise ValueError(f"Canvas motion channel {channel!r} is not admitted")
        if (target, channel) in seen:
            raise ValueError("Canvas target/channel pairs must be unique")
        seen.add((target, channel))
        intensity = _canvas_unit(raw["intensity"], name=f"motion {index} intensity")
        rate = _canvas_unit(raw["rate"], name=f"motion {index} rate")
        phase = _canvas_unit(raw["phase"], name=f"motion {index} phase")
        x = _canvas_unit(raw["x"], name=f"motion {index} x", signed=True)
        y = _canvas_unit(raw["y"], name=f"motion {index} y", signed=True)
        period = base_period / (.65 + .85 * rate)
        scales = {"translate": .055, "orbit": .075, "rotate": .48,
                  "scale": .22, "opacity": .62}
        amplitude = scales[channel] * body_scale * intensity
        periods.append(period)
        compiled_motions.append({
            "target": target, "channel": channel,
            "period_seconds": round(period, 6),
            "amplitude": round(amplitude, 6), "phase": phase,
            "x": x, "y": y,
        })
    if aspect >= 1.0:
        width, height = 960, round(960 / aspect)
    else:
        width, height = round(960 * aspect), 960
    compiled = {
        "format": "jnsq.canvas.v1", "width": width, "height": height,
        "background": background, "nodes": nodes,
        "motions": compiled_motions,
    }
    canonical = json.dumps(
        compiled, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")) + "\n"
    encoded = canonical.encode("utf-8")
    if len(encoded) > MAX_CANVAS_BYTES:
        raise ValueError(
            f"Canvas artifact exceeds the {MAX_CANVAS_BYTES}-byte boundary")
    return {
        "data": encoded, "json": canonical, "sha256": _sha(encoded),
        "bytes": len(encoded), "width": width, "height": height,
        "medium": "canvas", "media_type": "application/json",
        "variant": "canvas", "scene_format": compiled["format"],
        "node_count": len(nodes), "motion_count": len(compiled_motions),
        "motion_digest": _digest(compiled_motions),
        "base_period_seconds": round(base_period, 6),
        "period_seconds": ([round(min(periods), 6), round(max(periods), 6)]
                           if periods else [0.0, 0.0]),
    }


def _audio_number(value: Any, *, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Audio {name} must be numeric")
    number = float(value)
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f"Audio {name} must be {low:g} through {high:g}")
    return round(number, 6)


def _audio_integer(value: Any, *, name: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) \
            or not low <= value <= high:
        raise ValueError(f"Audio {name} must be an integer from {low} through {high}")
    return int(value)


def _audio_vector(expression_vector) -> tuple[dict, dict]:
    vector = {str(key): max(0.0, min(1.0, float(value)))
              for key, value in dict(expression_vector or {}).items()
              if isinstance(value, (int, float)) and not isinstance(value, bool)
              and math.isfinite(float(value))}
    gamma = vector.get("band.gamma", .5)
    coherence = vector.get("band.coherence", .5)
    play = vector.get("body.play", vector.get("cocktail.play", .5))
    prediction = vector.get("body.prediction_violation", .5)
    vagal = vector.get("body.vagal_tone", .5)
    drive = .34 * gamma + .26 * play + .22 * prediction + .18 * (1.0 - coherence)
    settling = .55 * coherence + .45 * vagal
    return vector, {
        "drive": drive,
        "settling": settling,
        "brightness": .35 + .45 * gamma + .20 * play,
        "swing": .02 + .12 * (1.0 - coherence) + .06 * play,
        "gain_scale": .62 + .20 * settling + .18 * drive,
        "tempo_scale": .82 + .34 * drive - .08 * settling,
        "return_cycles": 2 + round(4 * (.55 * coherence + .45 * vagal)),
    }


def compile_audio_score(score, expression_vector=None) -> dict:
    """Validate musical relationships and compile a closed host-owned score."""
    if not isinstance(score, dict) or set(score) != AUDIO_SCORE_FIELDS:
        raise ValueError(
            "Audio score must contain exactly tempo, beats, tonic, scale, seed, voices, and events")
    tempo = _audio_number(score["tempo"], name="tempo", low=48, high=168)
    beats = _audio_integer(score["beats"], name="beats", low=4, high=16)
    tonic = _audio_integer(score["tonic"], name="tonic", low=36, high=84)
    scale_name = str(score.get("scale") or "").strip().casefold()
    intervals = AUDIO_SCALES.get(scale_name)
    if intervals is None:
        raise ValueError("Audio scale is not admitted")
    seed = _audio_number(score["seed"], name="seed", low=0, high=1)
    raw_voices = score.get("voices")
    if not isinstance(raw_voices, list) \
            or not 1 <= len(raw_voices) <= MAX_AUDIO_VOICES:
        raise ValueError(
            f"Audio score requires 1 through {MAX_AUDIO_VOICES} voices")
    _vector, body = _audio_vector(expression_vector)
    compiled_tempo = max(42.0, min(192.0, tempo * body["tempo_scale"]))
    seconds_per_beat = 60.0 / compiled_tempo
    loop_seconds = beats * seconds_per_beat
    master_gain = min(.72, .38 * body["gain_scale"])
    voices = []
    voice_ids = []
    for index, raw in enumerate(raw_voices):
        if not isinstance(raw, dict) or set(raw) != AUDIO_VOICE_FIELDS:
            raise ValueError(f"Audio voice {index} has an invalid exact shape")
        voice_id = str(raw.get("id") or "").strip()
        if not SAFE_ID_RE.fullmatch(voice_id):
            raise ValueError(f"Audio voice {index} id is not safe")
        wave = str(raw.get("wave") or "").strip().casefold()
        if wave not in AUDIO_WAVES:
            raise ValueError(f"Audio voice {voice_id!r} wave is not admitted")
        gain = _audio_number(raw["gain"], name=f"voice {index} gain", low=.05, high=1)
        attack = _audio_number(raw["attack"], name=f"voice {index} attack", low=0, high=1)
        release = _audio_number(raw["release"], name=f"voice {index} release", low=0, high=1)
        pan = _audio_number(raw["pan"], name=f"voice {index} pan", low=-1, high=1)
        filter_value = _audio_number(raw["filter"], name=f"voice {index} filter", low=0, high=1)
        voices.append({
            "id": voice_id, "wave": wave,
            "gain": round(min(.62, gain * body["gain_scale"]), 6),
            "attack_seconds": round(.005 + .18 * attack * attack, 6),
            "release_seconds": round(.02 + .65 * release * release, 6),
            "pan": pan,
            "filter_hz": round(280 + filter_value * filter_value *
                               (4000 + 8000 * body["brightness"]), 3),
        })
        voice_ids.append(voice_id)
    if len(voice_ids) != len(set(voice_ids)):
        raise ValueError("Audio voice ids must be unique")
    raw_events = score.get("events")
    if not isinstance(raw_events, list) \
            or not 1 <= len(raw_events) <= MAX_AUDIO_EVENTS:
        raise ValueError(
            f"Audio score requires 1 through {MAX_AUDIO_EVENTS} events")
    events = []
    for index, raw in enumerate(raw_events):
        if not isinstance(raw, dict) or set(raw) != AUDIO_EVENT_FIELDS:
            raise ValueError(f"Audio event {index} has an invalid exact shape")
        voice = str(raw.get("voice") or "").strip()
        if voice not in voice_ids:
            raise ValueError(f"Audio event voice {voice!r} does not exist")
        beat = _audio_number(raw["beat"], name=f"event {index} beat", low=0, high=beats)
        duration = _audio_number(
            raw["duration"], name=f"event {index} duration", low=.125, high=beats)
        if beat >= beats or beat + duration > beats:
            raise ValueError(f"Audio event {index} must close within the score cycle")
        degree = _audio_integer(raw["degree"], name=f"event {index} degree", low=0, high=20)
        octave = _audio_integer(raw["octave"], name=f"event {index} octave", low=-2, high=2)
        velocity = _audio_number(raw["velocity"], name=f"event {index} velocity", low=.05, high=1)
        probability = _audio_number(
            raw["probability"], name=f"event {index} probability", low=.05, high=1)
        midi = tonic + intervals[degree % len(intervals)] \
            + 12 * (degree // len(intervals) + octave)
        if not 24 <= midi <= 108:
            raise ValueError(f"Audio event {index} pitch is outside the admitted range")
        shifted_beat = beat
        if int(round(beat * 2)) % 2 == 1:
            shifted_beat = min(beats - duration, beat + body["swing"])
        events.append({
            "voice": voice, "beat": beat,
            "start_seconds": round(shifted_beat * seconds_per_beat, 6),
            "duration_seconds": round(duration * seconds_per_beat, 6),
            "midi": midi,
            "frequency_hz": round(440.0 * (2.0 ** ((midi - 69) / 12.0)), 6),
            "velocity": round(min(1.0, velocity * body["gain_scale"]), 6),
            "probability": probability,
        })
    compiled = {
        "format": "jnsq.score.v1", "sample_rate": 24000,
        "tempo_bpm": round(compiled_tempo, 6), "beats": beats,
        "seconds_per_beat": round(seconds_per_beat, 6),
        "loop_seconds": round(loop_seconds, 6),
        "return_cycles": int(body["return_cycles"]),
        "return_seconds": round(loop_seconds * body["return_cycles"], 6),
        "seed": seed, "swing": round(body["swing"], 6),
        "master_gain": round(master_gain, 6),
        "scale": {"name": scale_name, "tonic_midi": tonic,
                  "intervals": list(intervals)},
        "voices": voices, "events": events,
    }
    canonical = json.dumps(
        compiled, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")) + "\n"
    encoded = canonical.encode("utf-8")
    if len(encoded) > MAX_AUDIO_BYTES:
        raise ValueError(
            f"Audio artifact exceeds the {MAX_AUDIO_BYTES}-byte boundary")
    return {
        "data": encoded, "json": canonical, "sha256": _sha(encoded),
        "bytes": len(encoded), "medium": "audio",
        "media_type": "application/vnd.jnsq.score+json",
        "variant": "procedural_audio", "score_format": compiled["format"],
        "voice_count": len(voices), "event_count": len(events),
        "score_digest": _digest({"voices": voices, "events": events}),
        "tempo_bpm": compiled["tempo_bpm"],
        "loop_seconds": compiled["loop_seconds"],
        "return_cycles": compiled["return_cycles"],
        "return_seconds": compiled["return_seconds"],
    }


def _scene3d_number(value: Any, *, name: str,
                    low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"3D {name} must be numeric")
    number = float(value)
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f"3D {name} must be {low:g} through {high:g}")
    return round(number, 6)


def _scene3d_color(value: Any, *, name: str) -> str:
    color = str(value or "").strip()
    if not COLOR_RE.fullmatch(color):
        raise ValueError(f"3D {name} must be a six-digit hex color")
    return color.casefold()


def _scene3d_vector(expression_vector) -> tuple[dict, dict]:
    vector = {str(key): max(0.0, min(1.0, float(value)))
              for key, value in dict(expression_vector or {}).items()
              if isinstance(value, (int, float)) and not isinstance(value, bool)
              and math.isfinite(float(value))}
    gamma = vector.get("band.gamma", .5)
    coherence = vector.get("band.coherence", .5)
    play = vector.get("body.play", vector.get("cocktail.curiosity", .5))
    prediction = vector.get("body.prediction_violation", .5)
    vagal = vector.get("body.vagal_tone", .5)
    drive = .34 * gamma + .25 * play + .23 * prediction + .18 * (1 - coherence)
    settling = .56 * coherence + .44 * vagal
    return vector, {
        "drive": drive, "settling": settling,
        "brightness": .34 + .44 * gamma + .22 * play,
        "body_scale": .56 + .72 * (.42 * gamma + .31 * play + .27 * coherence),
        "base_period": 3.0 + 7.0 * (1.0 - drive),
    }


def compile_scene3d(scene, motions, expression_vector=None) -> dict:
    """Validate spatial relationships and compile host-owned cyclic motion."""
    if not isinstance(scene, dict) or set(scene) != SCENE3D_FIELDS:
        raise ValueError(
            "3D scene must contain exactly background, camera, ambient, lights, and objects")
    background = _scene3d_color(scene.get("background"), name="background")
    ambient = _scene3d_number(
        scene.get("ambient"), name="ambient", low=.02, high=1)
    raw_camera = scene.get("camera")
    if not isinstance(raw_camera, dict) \
            or set(raw_camera) != SCENE3D_CAMERA_FIELDS:
        raise ValueError("3D camera has an invalid exact shape")
    camera = {
        "x": _scene3d_number(raw_camera["x"], name="camera x", low=-4, high=4),
        "y": _scene3d_number(raw_camera["y"], name="camera y", low=-4, high=4),
        "z": _scene3d_number(raw_camera["z"], name="camera z", low=1, high=6),
        "target_x": _scene3d_number(
            raw_camera["target_x"], name="camera target x", low=-2, high=2),
        "target_y": _scene3d_number(
            raw_camera["target_y"], name="camera target y", low=-2, high=2),
        "target_z": _scene3d_number(
            raw_camera["target_z"], name="camera target z", low=-2, high=2),
        "fov": _scene3d_number(raw_camera["fov"], name="camera fov", low=30, high=80),
    }
    if math.dist((camera["x"], camera["y"], camera["z"]),
                 (camera["target_x"], camera["target_y"], camera["target_z"])) < .5:
        raise ValueError("3D camera must remain outside its target")
    raw_lights = scene.get("lights")
    if not isinstance(raw_lights, list) \
            or not 1 <= len(raw_lights) <= MAX_3D_LIGHTS:
        raise ValueError(f"3D scene requires 1 through {MAX_3D_LIGHTS} lights")
    _vector, body = _scene3d_vector(expression_vector)
    lights = []
    for index, raw in enumerate(raw_lights):
        if not isinstance(raw, dict) or set(raw) != SCENE3D_LIGHT_FIELDS:
            raise ValueError(f"3D light {index} has an invalid exact shape")
        lights.append({
            "x": _scene3d_number(raw["x"], name=f"light {index} x", low=-4, high=4),
            "y": _scene3d_number(raw["y"], name=f"light {index} y", low=-4, high=4),
            "z": _scene3d_number(raw["z"], name=f"light {index} z", low=-4, high=4),
            "color": _scene3d_color(raw["color"], name=f"light {index} color"),
            "intensity": round(min(2.4, _scene3d_number(
                raw["intensity"], name=f"light {index} intensity", low=.05, high=2)
                * (.7 + .48 * body["brightness"])), 6),
        })
    raw_objects = scene.get("objects")
    if not isinstance(raw_objects, list) \
            or not 1 <= len(raw_objects) <= MAX_3D_OBJECTS:
        raise ValueError(
            f"3D scene requires 1 through {MAX_3D_OBJECTS} objects")
    objects = []
    object_ids = []
    for index, raw in enumerate(raw_objects):
        if not isinstance(raw, dict) or set(raw) != SCENE3D_OBJECT_FIELDS:
            raise ValueError(f"3D object {index} has an invalid exact shape")
        object_id = str(raw.get("id") or "").strip()
        if not SAFE_ID_RE.fullmatch(object_id):
            raise ValueError(f"3D object {index} id is not safe")
        kind = str(raw.get("kind") or "").strip().casefold()
        if kind not in SCENE3D_KINDS:
            raise ValueError(f"3D object {object_id!r} kind is not admitted")
        roughness = _scene3d_number(
            raw["roughness"], name=f"object {index} roughness", low=0, high=1)
        metallic = _scene3d_number(
            raw["metallic"], name=f"object {index} metallic", low=0, high=1)
        objects.append({
            "id": object_id, "kind": kind,
            "x": _scene3d_number(raw["x"], name=f"object {index} x", low=-2, high=2),
            "y": _scene3d_number(raw["y"], name=f"object {index} y", low=-2, high=2),
            "z": _scene3d_number(raw["z"], name=f"object {index} z", low=-2, high=2),
            "scale_x": _scene3d_number(raw["scale_x"], name=f"object {index} scale x", low=.05, high=2),
            "scale_y": _scene3d_number(raw["scale_y"], name=f"object {index} scale y", low=.05, high=2),
            "scale_z": _scene3d_number(raw["scale_z"], name=f"object {index} scale z", low=.05, high=2),
            "rotation_x": _scene3d_number(raw["rotation_x"], name=f"object {index} rotation x", low=-1, high=1),
            "rotation_y": _scene3d_number(raw["rotation_y"], name=f"object {index} rotation y", low=-1, high=1),
            "rotation_z": _scene3d_number(raw["rotation_z"], name=f"object {index} rotation z", low=-1, high=1),
            "color": _scene3d_color(raw["color"], name=f"object {index} color"),
            "roughness": round(min(1.0, roughness * (.74 + .32 * body["settling"])), 6),
            "metallic": round(min(1.0, metallic * (.66 + .38 * body["brightness"])), 6),
            "opacity": _scene3d_number(raw["opacity"], name=f"object {index} opacity", low=.15, high=1),
        })
        object_ids.append(object_id)
    if len(object_ids) != len(set(object_ids)):
        raise ValueError("3D object ids must be unique")
    if not isinstance(motions, list) or len(motions) > MAX_MOTIONS:
        raise ValueError(f"3D scene admits at most {MAX_MOTIONS} motions")
    compiled_motions = []
    periods = []
    seen = set()
    for index, raw in enumerate(motions):
        if not isinstance(raw, dict) or set(raw) != MOTION_FIELDS:
            raise ValueError("3D motion must contain the exact motion shape")
        target = str(raw.get("target") or "").strip()
        channel = str(raw.get("channel") or "").strip().casefold()
        if target not in object_ids:
            raise ValueError(f"3D motion target {target!r} does not exist")
        if channel not in SCENE3D_MOTION_CHANNELS:
            raise ValueError(f"3D motion channel {channel!r} is not admitted")
        if (target, channel) in seen:
            raise ValueError("3D target/channel pairs must be unique")
        seen.add((target, channel))
        intensity = _canvas_unit(raw["intensity"], name=f"3D motion {index} intensity")
        rate = _canvas_unit(raw["rate"], name=f"3D motion {index} rate")
        phase = _canvas_unit(raw["phase"], name=f"3D motion {index} phase")
        x = _canvas_unit(raw["x"], name=f"3D motion {index} x", signed=True)
        y = _canvas_unit(raw["y"], name=f"3D motion {index} y", signed=True)
        planar = math.hypot(x, y)
        if planar > 1:
            x, y = x / planar, y / planar
            axis_z = 0.0
        else:
            axis_z = math.sqrt(max(0.0, 1.0 - x * x - y * y))
            if phase >= .5:
                axis_z *= -1.0
        period = body["base_period"] / (.65 + .85 * rate)
        scales = {"translate": .42, "orbit": .62, "rotate": 1.05,
                  "scale": .28, "opacity": .62}
        amplitude = scales[channel] * body["body_scale"] * intensity
        periods.append(period)
        compiled_motions.append({
            "target": target, "channel": channel,
            "period_seconds": round(period, 6),
            "amplitude": round(amplitude, 6), "phase": phase,
            "axis_x": round(x, 6), "axis_y": round(y, 6),
            "axis_z": round(axis_z, 6),
        })
    compiled = {
        "format": "jnsq.scene3d.v1", "width": 960, "height": 720,
        "background": background,
        "camera": {**camera, "fov": round(max(28, min(
            82, camera["fov"] + 5 * (body["drive"] - body["settling"]))), 6)},
        "ambient": round(min(1.0, ambient * (.72 + .42 * body["settling"])), 6),
        "lights": lights, "objects": objects, "motions": compiled_motions,
    }
    canonical = json.dumps(
        compiled, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")) + "\n"
    encoded = canonical.encode("utf-8")
    if len(encoded) > MAX_3D_BYTES:
        raise ValueError(f"3D artifact exceeds the {MAX_3D_BYTES}-byte boundary")
    triangles = sum(SCENE3D_TRIANGLES[value["kind"]] for value in objects)
    return {
        "data": encoded, "json": canonical, "sha256": _sha(encoded),
        "bytes": len(encoded), "medium": "scene3d",
        "media_type": "application/vnd.jnsq.scene3d+json",
        "variant": "trusted_3d", "scene_format": compiled["format"],
        "width": compiled["width"], "height": compiled["height"],
        "object_count": len(objects), "light_count": len(lights),
        "triangle_count": triangles, "motion_count": len(compiled_motions),
        "motion_digest": _digest(compiled_motions),
        "base_period_seconds": round(body["base_period"], 6),
        "period_seconds": ([round(min(periods), 6), round(max(periods), 6)]
                           if periods else [0.0, 0.0]),
    }


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (struct.pack(">I", len(payload)) + kind + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))


def sanitize_png(raw: bytes) -> dict:
    """Validate a static PNG and remove prompt/EXIF/text metadata.

    ComfyUI normally embeds its workflow in ancillary PNG chunks.  That is
    useful inside ComfyUI and wrong at this privacy boundary: the artifact
    index already carries content-free provenance, while the admitted prompt
    remains in the private seed.  Canonical Atelier PNGs retain only rendering
    chunks and cannot carry the workflow back out through an image download.
    """
    data = bytes(raw or b"")
    if not 33 <= len(data) <= MAX_RASTER_BYTES:
        raise ValueError("PNG artifact size is outside the admitted boundary")
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("PNG artifact has an invalid signature")
    offset = 8
    chunks = []
    seen_ihdr = seen_idat = seen_iend = False
    width = height = 0
    while offset < len(data):
        if offset + 12 > len(data):
            raise ValueError("PNG artifact has a truncated chunk")
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        if length > MAX_RASTER_BYTES or offset + 12 + length > len(data):
            raise ValueError("PNG artifact has an invalid chunk length")
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        expected = struct.unpack(
            ">I", data[offset + 8 + length:offset + 12 + length])[0]
        if zlib.crc32(kind + payload) & 0xFFFFFFFF != expected:
            raise ValueError("PNG artifact failed its chunk integrity check")
        offset += 12 + length
        if not seen_ihdr:
            if kind != b"IHDR" or length != 13:
                raise ValueError("PNG artifact must begin with IHDR")
            width, height, depth, color, compression, filtering, interlace = \
                struct.unpack(">IIBBBBB", payload)
            if depth not in {1, 2, 4, 8, 16} or color not in {0, 2, 3, 4, 6}:
                raise ValueError("PNG artifact uses an unsupported pixel format")
            if compression != 0 or filtering != 0 or interlace not in {0, 1}:
                raise ValueError("PNG artifact uses an unsupported encoding")
            if not 16 <= width <= 4096 or not 16 <= height <= 4096 \
                    or width * height > MAX_RASTER_PIXELS:
                raise ValueError("PNG canvas dimensions are outside the boundary")
            seen_ihdr = True
            chunks.append((kind, payload))
            continue
        if kind in {b"acTL", b"fcTL", b"fdAT"}:
            raise ValueError("animated PNG is not admitted in this Atelier cut")
        if kind == b"IHDR":
            raise ValueError("PNG artifact contains more than one IHDR")
        if kind == b"IDAT":
            if seen_iend:
                raise ValueError("PNG image data appears after IEND")
            seen_idat = True
            chunks.append((kind, payload))
        elif kind == b"IEND":
            if length or not seen_idat:
                raise ValueError("PNG artifact has an invalid IEND")
            seen_iend = True
            chunks.append((kind, payload))
            if offset != len(data):
                raise ValueError("PNG artifact contains trailing bytes")
            break
        elif kind in {b"PLTE", b"tRNS"}:
            if seen_idat:
                raise ValueError("PNG palette data appears after image data")
            chunks.append((kind, payload))
        elif 65 <= kind[0] <= 90:
            # Unknown critical chunks alter decoding and cannot be stripped.
            raise ValueError("PNG artifact contains an unknown critical chunk")
        # All other ancillary chunks are intentionally stripped.
    if not (seen_ihdr and seen_idat and seen_iend):
        raise ValueError("PNG artifact is incomplete")
    canonical = b"\x89PNG\r\n\x1a\n" + b"".join(
        _png_chunk(kind, payload) for kind, payload in chunks)
    return {
        "data": canonical, "sha256": _sha(canonical),
        "bytes": len(canonical), "width": width, "height": height,
        "medium": "png", "media_type": "image/png",
    }


def sanitize_raster(raw: bytes, medium: str) -> dict:
    medium = str(medium or "").strip().casefold()
    if medium == "png":
        return sanitize_png(raw)
    raise ValueError(f"raster medium {medium!r} is not admitted")


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
        return self._create_validated_svg(
            run_id, title, sanitize_svg(svg), source=source,
            expression_vector=expression_vector, variant="static")

    def create_kinetic_svg(self, run_id: str, title: str, svg: str, motions, *,
                           source: Mapping[str, Any],
                           expression_vector=None) -> dict:
        validated = compose_kinetic_svg(svg, motions, expression_vector)
        return self._create_validated_svg(
            run_id, title, validated, source=source,
            expression_vector=expression_vector, variant="kinetic")

    def _create_validated_svg(self, run_id: str, title: str, validated: dict, *,
                              source: Mapping[str, Any], expression_vector,
                              variant: str) -> dict:
        run_id = _bounded(run_id, name="atelier run id", maximum=160)
        title = _bounded(title, name="atelier artifact title",
                         maximum=MAX_LABEL_CHARS)
        source = dict(source or {})
        source_digest = _bounded(
            source.get("source_digest") or _digest(source),
            name="atelier source digest", maximum=80)
        source["source_digest"] = source_digest
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
            motion_meta = {key: validated[key] for key in (
                "motion_count", "motion_digest", "base_period_seconds",
                "period_seconds") if key in validated}
            if prior:
                return {**self._append(self.index, {
                    "kind": "artifact_reused", "artifact_id": artifact_id,
                    "run_id": run_id, "title": title, "medium": "svg",
                    "media_type": "image/svg+xml",
                    "ref": prior["ref"], "sha256": validated["sha256"],
                    "bytes": prior.get("bytes", validated["bytes"]),
                    "elements": prior.get("elements", validated["elements"]),
                    "width": prior.get("width", validated["width"]),
                    "height": prior.get("height", validated["height"]),
                    "variant": variant, **motion_meta,
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
                "media_type": "image/svg+xml",
                "ref": f"artifacts/{path.name}",
                "sha256": validated["sha256"],
                "bytes": validated["bytes"],
                "elements": validated["elements"],
                "width": validated["width"], "height": validated["height"],
                "variant": variant, **motion_meta,
                "source": source, "expression_vector": vector,
                "ownership": "persona_private",
                "created_at": float(self.now_fn()),
            })
            return {**record, "duplicate": False}

    def create_canvas(self, run_id: str, title: str, scene, motions, *,
                      source: Mapping[str, Any], expression_vector=None) -> dict:
        run_id = _bounded(run_id, name="atelier run id", maximum=160)
        title = _bounded(title, name="atelier artifact title",
                         maximum=MAX_LABEL_CHARS)
        source = dict(source or {})
        source_digest = _bounded(
            source.get("source_digest") or _digest(source),
            name="atelier source digest", maximum=80)
        source["source_digest"] = source_digest
        validated = compile_canvas_scene(scene, motions, expression_vector)
        artifact_id = f"canvas_{validated['sha256'][:16]}"
        vector = {
            str(key)[:80]: round(max(0.0, min(1.0, float(value))), 6)
            for key, value in dict(expression_vector or {}).items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value))
        }
        canvas_meta = {key: validated[key] for key in (
            "variant", "scene_format", "node_count", "motion_count",
            "motion_digest", "base_period_seconds", "period_seconds")}
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
                    "run_id": run_id, "title": title, "medium": "canvas",
                    "media_type": validated["media_type"],
                    "ref": prior["ref"], "sha256": validated["sha256"],
                    "bytes": prior.get("bytes", validated["bytes"]),
                    "width": prior.get("width", validated["width"]),
                    "height": prior.get("height", validated["height"]),
                    **canvas_meta, "source": source,
                    "expression_vector": vector,
                    "ownership": "persona_private",
                    "created_at": float(self.now_fn()),
                }), "duplicate": True}
            self._ensure()
            path = self.artifacts / f"{artifact_id}.json"
            path.write_bytes(validated["data"])
            record = self._append(self.index, {
                "kind": "artifact_created", "artifact_id": artifact_id,
                "run_id": run_id, "title": title, "medium": "canvas",
                "media_type": validated["media_type"],
                "ref": f"artifacts/{path.name}",
                "sha256": validated["sha256"], "bytes": validated["bytes"],
                "width": validated["width"], "height": validated["height"],
                **canvas_meta, "source": source,
                "expression_vector": vector,
                "ownership": "persona_private",
                "created_at": float(self.now_fn()),
            })
            return {**record, "duplicate": False}

    def create_audio(self, run_id: str, title: str, score, *,
                     source: Mapping[str, Any], expression_vector=None) -> dict:
        run_id = _bounded(run_id, name="atelier run id", maximum=160)
        title = _bounded(title, name="atelier artifact title",
                         maximum=MAX_LABEL_CHARS)
        source = dict(source or {})
        source_digest = _bounded(
            source.get("source_digest") or _digest(source),
            name="atelier source digest", maximum=80)
        source["source_digest"] = source_digest
        validated = compile_audio_score(score, expression_vector)
        artifact_id = f"audio_{validated['sha256'][:16]}"
        vector = {
            str(key)[:80]: round(max(0.0, min(1.0, float(value))), 6)
            for key, value in dict(expression_vector or {}).items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value))
        }
        audio_meta = {key: validated[key] for key in (
            "variant", "score_format", "voice_count", "event_count",
            "score_digest", "tempo_bpm", "loop_seconds", "return_cycles",
            "return_seconds")}
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
                    "run_id": run_id, "title": title, "medium": "audio",
                    "media_type": validated["media_type"],
                    "ref": prior["ref"], "sha256": validated["sha256"],
                    "bytes": prior.get("bytes", validated["bytes"]),
                    **audio_meta, "source": source,
                    "expression_vector": vector,
                    "ownership": "persona_private",
                    "created_at": float(self.now_fn()),
                }), "duplicate": True}
            self._ensure()
            path = self.artifacts / f"{artifact_id}.json"
            path.write_bytes(validated["data"])
            record = self._append(self.index, {
                "kind": "artifact_created", "artifact_id": artifact_id,
                "run_id": run_id, "title": title, "medium": "audio",
                "media_type": validated["media_type"],
                "ref": f"artifacts/{path.name}",
                "sha256": validated["sha256"], "bytes": validated["bytes"],
                **audio_meta, "source": source,
                "expression_vector": vector,
                "ownership": "persona_private",
                "created_at": float(self.now_fn()),
            })
            return {**record, "duplicate": False}

    def create_scene3d(self, run_id: str, title: str, scene, motions, *,
                       source: Mapping[str, Any], expression_vector=None) -> dict:
        run_id = _bounded(run_id, name="atelier run id", maximum=160)
        title = _bounded(title, name="atelier artifact title",
                         maximum=MAX_LABEL_CHARS)
        source = dict(source or {})
        source_digest = _bounded(
            source.get("source_digest") or _digest(source),
            name="atelier source digest", maximum=80)
        source["source_digest"] = source_digest
        validated = compile_scene3d(scene, motions, expression_vector)
        artifact_id = f"scene3d_{validated['sha256'][:16]}"
        vector = {
            str(key)[:80]: round(max(0.0, min(1.0, float(value))), 6)
            for key, value in dict(expression_vector or {}).items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value))
        }
        scene_meta = {key: validated[key] for key in (
            "variant", "scene_format", "object_count", "light_count",
            "triangle_count", "motion_count", "motion_digest",
            "base_period_seconds", "period_seconds")}
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
                    "run_id": run_id, "title": title, "medium": "scene3d",
                    "media_type": validated["media_type"],
                    "ref": prior["ref"], "sha256": validated["sha256"],
                    "bytes": prior.get("bytes", validated["bytes"]),
                    "width": prior.get("width", validated["width"]),
                    "height": prior.get("height", validated["height"]),
                    **scene_meta, "source": source,
                    "expression_vector": vector,
                    "ownership": "persona_private",
                    "created_at": float(self.now_fn()),
                }), "duplicate": True}
            self._ensure()
            path = self.artifacts / f"{artifact_id}.json"
            path.write_bytes(validated["data"])
            record = self._append(self.index, {
                "kind": "artifact_created", "artifact_id": artifact_id,
                "run_id": run_id, "title": title, "medium": "scene3d",
                "media_type": validated["media_type"],
                "ref": f"artifacts/{path.name}",
                "sha256": validated["sha256"], "bytes": validated["bytes"],
                "width": validated["width"], "height": validated["height"],
                **scene_meta, "source": source,
                "expression_vector": vector,
                "ownership": "persona_private",
                "created_at": float(self.now_fn()),
            })
            return {**record, "duplicate": False}

    def create_raster(self, run_id: str, title: str, raw: bytes, *,
                      medium: str, source: Mapping[str, Any],
                      expression_vector=None) -> dict:
        run_id = _bounded(run_id, name="atelier run id", maximum=160)
        title = _bounded(title, name="atelier artifact title",
                         maximum=MAX_LABEL_CHARS)
        source = dict(source or {})
        source_digest = _bounded(
            source.get("source_digest") or _digest(source),
            name="atelier source digest", maximum=80)
        source["source_digest"] = source_digest
        validated = sanitize_raster(raw, medium)
        medium = validated["medium"]
        artifact_id = f"{medium}_{validated['sha256'][:16]}"
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
                    "run_id": run_id, "title": title, "medium": medium,
                    "media_type": validated["media_type"],
                    "ref": prior["ref"], "sha256": validated["sha256"],
                    "bytes": prior.get("bytes", validated["bytes"]),
                    "width": prior.get("width", validated["width"]),
                    "height": prior.get("height", validated["height"]),
                    "source": source, "expression_vector": vector,
                    "ownership": "persona_private",
                    "created_at": float(self.now_fn()),
                }), "duplicate": True}
            self._ensure()
            path = self.artifacts / f"{artifact_id}.{medium}"
            path.write_bytes(validated["data"])
            record = self._append(self.index, {
                "kind": "artifact_created", "artifact_id": artifact_id,
                "run_id": run_id, "title": title, "medium": medium,
                "media_type": validated["media_type"],
                "ref": f"artifacts/{path.name}",
                "sha256": validated["sha256"],
                "bytes": validated["bytes"],
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
            "renderer", "renderer_http_attempts", "checkpoint",
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
            "media": ["svg", "kinetic svg", "canvas", "procedural audio",
                      "3d scene", "png"],
            "policy": {
                "create": "one validated private artifact per field win",
                "active_svg": False,
                "host_compiled_kinetic_svg": True,
                "host_compiled_procedural_audio": True,
                "autoplay": False,
                "host_compiled_webgl": True,
                "model_authored_shaders": False,
                "remote_references": False,
                "overwrite": False,
                "delete": False,
                "publish": False,
                "message": False,
                "external_effects": False,
            },
        }

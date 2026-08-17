"""Shared-field autonomous creation for the persona-private atelier.

The local model may describe one proposed artifact after an atelier seed wins
ordinary attention. The host remains the authority boundary: model-authored
SVG stays inert, while normalized motion vectors may be compiled by the host
into a narrow cyclic SMIL vocabulary. Canvas crosses the same boundary as a
validated data-only scene graph; trusted host code owns every draw call. No
fallback provider call is admitted. Procedural sound crosses as a bounded
score graph; trusted host code owns every Web Audio operation.
Three-dimensional form crosses as bounded primitives and spatial relations;
trusted host code owns meshes, matrices, shaders, and every WebGL call.
Cross-medium composition references already-admitted immutable artifacts;
trusted host code owns provenance resolution, the shared clock, and playback.
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
from core.atelier import Atelier
from core.sovereign_interior import lease_fields
from harness.model_call_receipts import (
    model_call_scope, new_cycle_id, record_model_call,
)
from shell.agency_controller import AgencyRunOutcome
from shell.autonomy_circulation import (
    circulate_experienced_event, readiness_from_engine,
)
from shell.maintenance_circulation import offer_maintenance_candidate
from shell.comfyui_client import ComfyUIClient, ComfyUIConfig


ATELIER_SOURCES = frozenset({"atelier_seed"})
ATELIER_AUTHORITY_TIER = 2
ATELIER_ACTIONS = frozenset({
    "quiet", "create_svg", "create_kinetic_svg", "create_canvas",
    "create_audio", "create_3d", "create_composition", "create_diffusion",
})
LEGACY_FORM_ACTIONS = {
    "static svg": "create_svg",
    "kinetic svg": "create_kinetic_svg",
    "canvas": "create_canvas",
    "procedural audio": "create_audio",
    "trusted 3d": "create_3d",
    "cross-medium composition": "create_composition",
    "local comfyui diffusion": "create_diffusion",
}
LEGACY_TRANSLATION_HINTS = {
    "create_svg": (
        "The svg field must contain literal well-formed <svg "
        "xmlns=\"http://www.w3.org/2000/svg\" ...>...</svg> XML, not a "
        "description, Markdown, or code fence."),
    "create_kinetic_svg": (
        "The svg field must contain literal well-formed SVG XML and motions "
        "must contain the host motion vectors, never prose."),
    "create_canvas": (
        "The scene field must be the exact Canvas scene object and motions "
        "must be an array, never prose or serialized JSON text."),
    "create_audio": (
        "The score field must be the exact procedural-audio score object, "
        "never prose or serialized JSON text."),
    "create_3d": (
        "The scene field must be the exact trusted-3D scene object and "
        "motions must be an array, never prose or serialized JSON text."),
    "create_composition": (
        "The composition field must be the exact composition graph object, "
        "never prose or serialized JSON text."),
    "create_diffusion": (
        "The prompt field is the concise visual renderer description; all "
        "vector and scene fields remain neutral."),
}
def _digest(value: Any) -> str:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True,
                          default=str, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()[:16]


def _finite(value: Any, fallback=0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(fallback)
    return number if math.isfinite(number) else float(fallback)


def _legacy_form_action(text: str) -> tuple[str, str] | None:
    try:
        value = json.loads(str(text or "").strip())
    except (TypeError, ValueError):
        return None
    if not isinstance(value, dict) or "form" not in value:
        return None
    form = str(value.get("form") or "").strip()
    normalized = re.sub(r"[_-]+", " ", form.casefold())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    action = LEGACY_FORM_ACTIONS.get(normalized)
    return (form, action) if action else None


def _legacy_host_translation(proposal: Mapping[str, Any]) -> dict | None:
    """Remap an older creative envelope without inventing renderer content.

    The older Atelier dialect chose a ``form`` and placed renderer data under
    ``content`` or ``render``.  This translation only moves already-structured
    values into the current names.  Existing medium validators still reject
    prose, incomplete geometry, executable surfaces, URLs, and bad ranges.
    """
    raw = dict(proposal or {})
    form = str(raw.get("form") or "").strip()
    normalized = re.sub(r"[_-]+", " ", form.casefold())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    action = LEGACY_FORM_ACTIONS.get(normalized)
    if not action:
        return None

    def object_value(value):
        if isinstance(value, Mapping):
            return dict(value)
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
            except (TypeError, ValueError):
                return value
            return dict(decoded) if isinstance(decoded, Mapping) else decoded
        return value

    content = object_value(raw.get("content"))
    render = object_value(raw.get("render"))
    containers = [
        value for value in (render, content, raw)
        if isinstance(value, Mapping)
    ]

    def first(*keys, default=None):
        for container in containers:
            for key in keys:
                value = container.get(key)
                if value not in (None, "", {}, []):
                    return object_value(value)
        return default

    def bounded_fields(value, ranges, text_fields=()):
        if not isinstance(value, Mapping):
            return value
        result = {}
        for key in text_fields:
            if key in value:
                result[key] = value[key]
        for key, (minimum, maximum) in ranges.items():
            if key not in value:
                continue
            number = value[key]
            try:
                finite_number = (
                    None if isinstance(number, bool) else float(number))
            except (TypeError, ValueError):
                finite_number = None
            if finite_number is not None and math.isfinite(finite_number):
                result[key] = max(
                    float(minimum), min(float(maximum), finite_number))
            else:
                result[key] = number
        return result

    title = str(
        raw.get("title") or raw.get("description")
        or raw.get("artifact_id") or form
    ).strip()
    translated = {"action": action, "title": title}
    if action in {"create_svg", "create_kinetic_svg"}:
        svg = first("svg", "markup")
        if svg is None and isinstance(content, str):
            svg = content
        translated["svg"] = svg or ""
        if action == "create_kinetic_svg":
            translated["motions"] = first(
                "motions", "motion", "cycles", default=[])
    elif action in {"create_canvas", "create_3d"}:
        scene = first("scene", "scene_graph", "scene3d", "world", "geometry")
        if scene is None:
            candidate = render if isinstance(render, Mapping) else content
            required = (
                {"background", "camera", "objects"}
                if action == "create_3d" else {"nodes"})
            if isinstance(candidate, Mapping) \
                    and required.issubset(candidate):
                scene = dict(candidate)
                scene.pop("motions", None)
        if isinstance(scene, Mapping):
            scene = dict(scene)
            for wrapper in ("scene", "scene_graph", "geometry", "world"):
                nested = scene.get(wrapper)
                if isinstance(nested, Mapping):
                    scene = {**scene, **dict(nested)}
            aliases = (
                {
                    "background": ("background_color", "clear_color"),
                    "camera": ("viewpoint", "view", "camera_config"),
                    "ambient": (
                        "ambient_light", "ambient_intensity", "ambientLight"),
                    "lights": ("lighting", "light_sources"),
                    "objects": (
                        "primitives", "elements", "entities", "geometry_objects"),
                }
                if action == "create_3d" else {
                    "aspect": ("aspect_ratio",),
                    "background": ("background_color", "clear_color"),
                    "nodes": ("elements", "shapes", "objects"),
                })
            for canonical, alternatives in aliases.items():
                if canonical in scene:
                    continue
                for alternative in alternatives:
                    if alternative in scene:
                        scene[canonical] = scene[alternative]
                        break
            if action == "create_3d" \
                    and isinstance(scene.get("lights"), Mapping):
                lighting = dict(scene["lights"])
                scene["lights"] = (
                    lighting.get("lights")
                    or lighting.get("sources")
                    or lighting.get("items")
                    or scene["lights"])
            # Some legacy renderers place presentation/envelope metadata next
            # to an otherwise complete scene.  Project only the exact
            # renderer vocabulary; required-key and value validation remains
            # the compiler's job.
            scene_keys = (
                {"background", "camera", "ambient", "lights", "objects"}
                if action == "create_3d"
                else {"aspect", "background", "nodes"})
            scene = {
                key: value for key, value in dict(scene).items()
                if key in scene_keys
            }
            if action == "create_3d":
                scene = dict(scene)
                scene["camera"] = bounded_fields(
                    scene.get("camera"),
                    {
                        "x": (-4, 4), "y": (-4, 4), "z": (1, 6),
                        "target_x": (-2, 2), "target_y": (-2, 2),
                        "target_z": (-2, 2), "fov": (30, 80),
                    })
                if isinstance(scene.get("ambient"), (int, float)) \
                        and not isinstance(scene.get("ambient"), bool):
                    scene["ambient"] = max(
                        .02, min(1.0, float(scene["ambient"])))
                if isinstance(scene.get("lights"), list):
                    scene["lights"] = [
                        bounded_fields(
                            light,
                            {
                                "x": (-4, 4), "y": (-4, 4), "z": (-4, 4),
                                "intensity": (.05, 2),
                            },
                            ("color",))
                        for light in scene["lights"]
                    ]
                if isinstance(scene.get("objects"), list):
                    object_ranges = {
                        "x": (-2, 2), "y": (-2, 2), "z": (-2, 2),
                        "scale_x": (.05, 2), "scale_y": (.05, 2),
                        "scale_z": (.05, 2),
                        "rotation_x": (-1, 1), "rotation_y": (-1, 1),
                        "rotation_z": (-1, 1), "roughness": (0, 1),
                        "metallic": (0, 1), "opacity": (.15, 1),
                    }
                    scene["objects"] = [
                        bounded_fields(
                            item, object_ranges,
                            ("id", "kind", "color"))
                        for item in scene["objects"]
                    ]
                required_scene = {
                    "background", "camera", "ambient", "lights", "objects"}
                if set(scene) != required_scene:
                    raise ValueError(
                        "legacy 3D scene projection incomplete; present="
                        f"{sorted(scene)}; missing="
                        f"{sorted(required_scene - set(scene))}")
        translated["scene"] = scene or {}
        motions = first("motions", "motion", "cycles", default=[])
        if action == "create_3d" and isinstance(motions, list):
            motions = [
                bounded_fields(
                    motion,
                    {
                        "intensity": (0, 1), "rate": (0, 1),
                        "phase": (0, 1), "x": (-1, 1), "y": (-1, 1),
                    },
                    ("target", "channel"))
                for motion in motions
            ]
        translated["motions"] = motions
    elif action == "create_audio":
        score = first("score", "audio", "sound")
        if score is None and isinstance(content, Mapping) \
                and {"voices", "events"}.issubset(content):
            score = content
        translated["score"] = score or {}
    elif action == "create_composition":
        composition = first("composition", "graph")
        if composition is None and isinstance(content, Mapping) \
                and "tracks" in content:
            composition = content
        translated["composition"] = composition or {}
    elif action == "create_diffusion":
        prompt = first("prompt")
        if prompt is None and isinstance(content, str):
            prompt = content
        if prompt is None:
            prompt = raw.get("description")
        translated.update({
            "prompt": str(prompt or "").strip(),
            "negative_prompt": str(
                first("negative_prompt", "negative", default="") or ""),
            "aspect": first("aspect", "aspect_ratio", default=1.0),
        })
    return translated


def _translation_output_format(action: str):
    """Small Ollama grammar for a chosen medium; host validation stays final."""
    def number(minimum: float, maximum: float):
        return {
            "type": "number", "minimum": minimum, "maximum": maximum}

    if action == "create_kinetic_svg":
        motion = {
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "channel": {
                    "type": "string",
                    "enum": ["translate", "rotate", "opacity"],
                },
                "intensity": number(0.0, 1.0),
                "rate": number(0.0, 1.0),
                "phase": number(0.0, 1.0),
                "x": number(-1.0, 1.0),
                "y": number(-1.0, 1.0),
            },
            "required": [
                "target", "channel", "intensity", "rate", "phase", "x", "y",
            ],
            "additionalProperties": False,
        }
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string", "enum": ["create_kinetic_svg"]},
                "title": {"type": "string"},
                "svg": {"type": "string"},
                "motions": {
                    "type": "array", "items": motion,
                    "minItems": 1, "maxItems": 12,
                },
            },
            "required": ["action", "title", "svg", "motions"],
            "additionalProperties": False,
        }
    if action == "create_svg":
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["create_svg"]},
                "title": {"type": "string"},
                "svg": {"type": "string"},
            },
            "required": ["action", "title", "svg"],
            "additionalProperties": False,
        }
    if action == "create_3d":
        hex_color = {
            "type": "string", "pattern": "^#[0-9A-Fa-f]{6}$"}
        camera = {
            "type": "object",
            "properties": {
                "x": number(-4.0, 4.0), "y": number(-4.0, 4.0),
                "z": number(1.0, 6.0),
                "target_x": number(-2.0, 2.0),
                "target_y": number(-2.0, 2.0),
                "target_z": number(-2.0, 2.0),
                "fov": number(30.0, 80.0),
            },
            "required": [
                "x", "y", "z", "target_x", "target_y", "target_z", "fov"],
            "additionalProperties": False,
        }
        light = {
            "type": "object",
            "properties": {
                "x": number(-4.0, 4.0), "y": number(-4.0, 4.0),
                "z": number(-4.0, 4.0), "color": hex_color,
                "intensity": number(0.05, 2.0),
            },
            "required": ["x", "y", "z", "color", "intensity"],
            "additionalProperties": False,
        }
        object3d = {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "kind": {
                    "type": "string",
                    "enum": ["sphere", "box", "torus", "plane"],
                },
                **{
                    key: number(-2.0, 2.0)
                    for key in ("x", "y", "z")
                },
                **{
                    key: number(0.05, 2.0)
                    for key in ("scale_x", "scale_y", "scale_z")
                },
                **{
                    key: number(-1.0, 1.0)
                    for key in ("rotation_x", "rotation_y", "rotation_z")
                },
                "color": hex_color,
                "roughness": number(0.0, 1.0),
                "metallic": number(0.0, 1.0),
                "opacity": number(0.15, 1.0),
            },
            "required": [
                "id", "kind", "x", "y", "z", "scale_x", "scale_y",
                "scale_z", "rotation_x", "rotation_y", "rotation_z", "color",
                "roughness", "metallic", "opacity",
            ],
            "additionalProperties": False,
        }
        scene = {
            "type": "object",
            "properties": {
                "background": hex_color,
                "camera": camera,
                "ambient": number(0.02, 1.0),
                "lights": {
                    "type": "array", "items": light,
                    "minItems": 1, "maxItems": 3,
                },
                "objects": {
                    "type": "array", "items": object3d,
                    "minItems": 1, "maxItems": 24,
                },
            },
            "required": [
                "background", "camera", "ambient", "lights", "objects"],
            "additionalProperties": False,
        }
        motion3d = {
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "channel": {
                    "type": "string",
                    "enum": [
                        "translate", "rotate", "scale", "opacity", "orbit"],
                },
                "intensity": number(0.0, 1.0),
                "rate": number(0.0, 1.0),
                "phase": number(0.0, 1.0),
                "x": number(-1.0, 1.0),
                "y": number(-1.0, 1.0),
            },
            "required": [
                "target", "channel", "intensity", "rate", "phase", "x", "y"],
            "additionalProperties": False,
        }
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["create_3d"]},
                "title": {"type": "string"},
                "scene": scene,
                "motions": {
                    "type": "array", "items": motion3d, "maxItems": 12},
            },
            "required": ["action", "title", "scene", "motions"],
            "additionalProperties": False,
        }
    if action == "create_diffusion":
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string", "enum": ["create_diffusion"]},
                "title": {"type": "string"},
                "prompt": {"type": "string"},
                "negative_prompt": {"type": "string"},
                "aspect": number(0.625, 1.6),
            },
            "required": [
                "action", "title", "prompt", "negative_prompt", "aspect"],
            "additionalProperties": False,
        }
    return "json"


@dataclass(frozen=True)
class AtelierConfig:
    model: str
    authority_tier: int = 0
    local_only: bool = True
    max_tokens: int = 3600
    diffusion_enabled: bool = False
    comfy_endpoint: str = "http://127.0.0.1:8188"
    comfy_checkpoint: str = "sd_xl_base_1.0.safetensors"
    comfy_execution_timeout: float = 420.0

    def __post_init__(self):
        model = str(self.model or "").strip()
        if not model:
            raise ValueError("atelier requires an explicit model")
        if self.authority_tier not in {0, 1, 2}:
            raise ValueError("atelier authority_tier must be 0, 1, or 2")
        if type(self.local_only) is not bool:
            raise ValueError("atelier local_only must be a bool")
        if not 800 <= int(self.max_tokens) <= 6000:
            raise ValueError("atelier max_tokens must be 800 through 6000")
        if type(self.diffusion_enabled) is not bool:
            raise ValueError("atelier diffusion enabled must be a bool")
        if self.diffusion_enabled:
            ComfyUIConfig(
                endpoint=self.comfy_endpoint,
                checkpoint=self.comfy_checkpoint,
                execution_timeout=self.comfy_execution_timeout)
        object.__setattr__(self, "model", model)


def resolve_atelier_config(raw, active_model: str) -> AtelierConfig:
    raw = dict(raw or {})
    diffusion = dict(raw.get("diffusion") or {})
    return AtelierConfig(
        model=str(raw.get("model") or active_model or ""),
        authority_tier=int(raw.get("authority_tier", 0)),
        local_only=bool(raw.get("local_only", True)),
        max_tokens=int(raw.get("max_tokens", 3600)),
        diffusion_enabled=bool(diffusion.get("enabled", False)),
        comfy_endpoint=str(diffusion.get(
            "endpoint") or "http://127.0.0.1:8188"),
        comfy_checkpoint=str(diffusion.get(
            "checkpoint") or "sd_xl_base_1.0.safetensors"),
        comfy_execution_timeout=float(diffusion.get(
            "execution_timeout", 420.0)),
    )


def parse_atelier_proposal(text: str) -> dict[str, Any]:
    """Extract one exact host-shaped proposal; never execute model data."""
    text = re.sub(r"<think>.*?</think>", "", str(text or ""),
                  flags=re.I | re.S).strip()
    fenced = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.I)
    if fenced:
        text = fenced.group(1).strip()
    try:
        proposal = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise ValueError("atelier model did not return one JSON object") from exc
    if not isinstance(proposal, dict):
        raise ValueError("atelier model did not return one JSON object")
    legacy = _legacy_host_translation(proposal)
    if legacy is not None:
        proposal = legacy
    allowed = {"action", "title", "svg", "scene", "score", "composition",
               "motions", "prompt", "negative_prompt", "aspect"}
    unknown = set(proposal) - allowed
    if unknown:
        dialect = {
            key: str(proposal.get(key) or "")[:80]
            for key in ("action", "form") if key in proposal}
        raise ValueError(
            f"atelier proposal contains unknown fields: {sorted(unknown)}"
            + (f"; dialect={dialect}" if dialect else ""))
    # Local structured-output models reliably omit neutral unused fields.
    # Their identities are unambiguous and carry no creative content, so the
    # host may supply them before the exact medium validator runs. Required
    # selected-medium content remains mandatory below; unknown authority
    # surfaces still fail closed above.
    neutral = {
        "action": "", "title": "", "svg": "", "scene": {}, "score": {},
        "composition": {}, "motions": [], "prompt": "",
        "negative_prompt": "", "aspect": 1.0,
    }
    proposal = {**neutral, **proposal}
    if "motions" in proposal and not isinstance(proposal["motions"], list):
        raise ValueError("atelier motions must be an array")
    if "scene" in proposal and not isinstance(proposal["scene"], dict):
        raise ValueError("atelier scene must be an object")
    if "score" in proposal and not isinstance(proposal["score"], dict):
        raise ValueError("atelier score must be an object")
    if "composition" in proposal \
            and not isinstance(proposal["composition"], dict):
        raise ValueError("atelier composition must be an object")
    action = str(proposal.get("action") or "").strip().casefold()
    if action not in ATELIER_ACTIONS:
        raise ValueError("atelier proposal action is invalid")
    if action == "create_3d":
        projected = _legacy_host_translation({
            "form": "trusted_3d",
            "description": proposal.get("title"),
            "render": {
                "scene": proposal.get("scene"),
                "motions": proposal.get("motions"),
            },
        })
        proposal["scene"] = projected["scene"]
        proposal["motions"] = projected["motions"]
    selected = {
        "quiet": set(),
        "create_svg": {"title", "svg"},
        "create_kinetic_svg": {"title", "svg", "motions"},
        "create_canvas": {"title", "scene", "motions"},
        "create_audio": {"title", "score"},
        "create_3d": {"title", "scene", "motions"},
        "create_composition": {"title", "composition"},
        "create_diffusion": {
            "title", "prompt", "negative_prompt", "aspect"},
    }[action]
    for key, empty in neutral.items():
        if key != "action" and key not in selected:
            proposal[key] = empty
    value = {
        "action": action,
        "title": str(proposal.get("title") or "").strip(),
        "svg": str(proposal.get("svg") or "").strip(),
        "scene": proposal.get("scene", {}),
        "score": proposal.get("score", {}),
        "composition": proposal.get("composition", {}),
        "motions": proposal.get("motions", []),
        "prompt": str(proposal.get("prompt") or "").strip(),
        "negative_prompt": str(proposal.get("negative_prompt") or "").strip(),
        "aspect": _finite(proposal.get("aspect"), 1.0),
    }
    if action == "create_svg" and (
            not value["title"] or not value["svg"] or value["prompt"]
            or value["negative_prompt"] or value["motions"] or value["scene"]
            or value["score"] or value["composition"]):
        raise ValueError("SVG atelier proposal requires only title and svg")
    if action == "create_kinetic_svg" and (
            not value["title"] or not value["svg"]
            or not isinstance(value["motions"], list) or not value["motions"]
            or value["prompt"] or value["negative_prompt"] or value["scene"]
            or value["score"] or value["composition"]):
        raise ValueError(
            "kinetic SVG proposal requires title, svg, and motion vectors")
    if action == "create_canvas" and (
            not value["title"] or not isinstance(value["scene"], dict)
            or not value["scene"] or value["svg"] or value["prompt"]
            or value["negative_prompt"] or value["score"]
            or value["composition"] or value["aspect"] != 1.0):
        raise ValueError(
            "Canvas proposal requires title, scene, optional motions, and aspect 1.0")
    if action == "create_audio" and (
            not value["title"] or not isinstance(value["score"], dict)
            or not value["score"] or value["svg"] or value["scene"]
            or value["motions"] or value["prompt"] or value["negative_prompt"]
            or value["composition"] or value["aspect"] != 1.0):
        raise ValueError(
            "audio proposal requires title, score, and otherwise empty renderer fields")
    if action == "create_3d" and (
            not value["title"] or not isinstance(value["scene"], dict)
            or not value["scene"] or value["score"] or value["svg"]
            or value["prompt"] or value["negative_prompt"]
            or value["composition"] or value["aspect"] != 1.0):
        raise ValueError(
            "3D proposal requires title, scene, optional motions, and aspect 1.0")
    if action == "create_composition" and (
            not value["title"] or not isinstance(value["composition"], dict)
            or not value["composition"] or value["svg"] or value["scene"]
            or value["score"] or value["motions"] or value["prompt"]
            or value["negative_prompt"] or value["aspect"] != 1.0):
        raise ValueError(
            "composition proposal requires title, composition, and otherwise empty renderer fields")
    if action == "create_diffusion" and (
            not value["title"] or not value["prompt"] or value["svg"]
            or value["motions"] or value["scene"] or value["score"]
            or value["composition"]):
        raise ValueError("diffusion proposal requires title and prompt, not SVG")
    if not .625 <= value["aspect"] <= 1.6:
        raise ValueError("atelier aspect must be between 0.625 and 1.6")
    return value


class AtelierRuntime:
    """One persona's local visual proposal, commit, and field-return owner."""

    def __init__(self, engine, controller, raw_config=None, *,
                 atelier: Atelier = None, adapter_factory: Callable = None,
                 spec_loader: Callable = None,
                 comfy_client: ComfyUIClient = None):
        self.engine = engine
        self.controller = controller
        self.config = resolve_atelier_config(
            raw_config, getattr(engine, "model", ""))
        self.atelier = atelier or Atelier(engine.pdir)
        self._adapter_factory = adapter_factory
        self._spec_loader = spec_loader
        self._adapter = None
        self._effects = queue.Queue()
        self._observer = getattr(engine, "salience_observer", None)
        self.internal_outcome_sink = None
        self._last_readiness = None
        self.comfy = comfy_client
        if self.comfy is None and self.config.diffusion_enabled:
            self.comfy = ComfyUIClient(ComfyUIConfig(
                endpoint=self.config.comfy_endpoint,
                checkpoint=self.config.comfy_checkpoint,
                execution_timeout=self.config.comfy_execution_timeout))

    def _emit(self, kind: str, **payload) -> None:
        if self._observer is None:
            return
        try:
            self._observer.agency_transition(kind, time.time(), **payload)
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
        base_media = ["svg", "kinetic svg", "canvas", "procedural audio",
                      "3d scene", "composition"]
        last_probe = (dict(self.comfy.last_probe)
                      if self.comfy is not None and self.comfy.last_probe
                      else None)
        raster_ready = bool(
            self.config.diffusion_enabled
            and last_probe
            and last_probe.get("reachable")
            and last_probe.get("checkpoint_ready"))
        media = [*base_media, *(("png",) if raster_ready else ())]
        diffusion = {
            "enabled": self.config.diffusion_enabled,
            "status": ("ready" if raster_ready else
                       "unavailable" if last_probe else
                       "unchecked" if self.config.diffusion_enabled else
                       "disabled"),
            "usable": raster_ready,
            "renderer": "comfyui", "locality": "local",
            "checkpoint": self.config.comfy_checkpoint,
            "endpoint": self.config.comfy_endpoint,
            "last_probe": last_probe,
        }
        volitional_offer = "offer_atelier" in getattr(
            self.engine, "_volitional_actions", {})
        enabled = "atelier" in getattr(self.engine, "enabled", set())
        if not enabled:
            return {
                "usable": False, "reason": "atelier organ is disabled",
                "model": self.config.model, "locality": "unknown",
                "provider": None, "event_bridge": False,
                "media": media, "diffusion": diffusion,
                "volitional_offer": volitional_offer,
                "paid_fallbacks": 0,
            }
        try:
            spec = self._load_spec()
            identity = dict(spec.get("identity") or {})
            locality = str(identity.get("locality") or "unknown")
            adapter = self._model_adapter(spec)
            event_bridge = callable(getattr(adapter, "events", None))
            authority = self.config.authority_tier >= ATELIER_AUTHORITY_TIER
            local_admitted = locality == "local" or not self.config.local_only
            usable = authority and local_admitted and event_bridge
            if not authority:
                reason = "atelier authority tier does not admit private artifacts"
            elif not local_admitted:
                reason = "Atelier refuses non-local creative models"
            elif not event_bridge:
                reason = "atelier model lacks the interruptible event bridge"
            else:
                reason = "local interruptible creative path admitted"
            return {
                "usable": usable, "reason": reason,
                "model": self.config.model, "locality": locality,
                "provider": identity.get("provider"),
                "event_bridge": event_bridge, "media": media,
                "diffusion": diffusion,
                "volitional_offer": volitional_offer,
                "paid_fallbacks": 0,
            }
        except Exception as exc:
            return {
                "usable": False,
                "reason": f"atelier model unavailable: {type(exc).__name__}",
                "model": self.config.model, "locality": "unknown",
                "provider": None, "event_bridge": False,
                "media": media, "diffusion": diffusion,
                "volitional_offer": volitional_offer,
                "paid_fallbacks": 0,
            }

    def readiness(self, field=None) -> dict:
        self._last_readiness = readiness_from_engine(self.engine, field)
        return dict(self._last_readiness)

    @staticmethod
    def eligible(candidate: Mapping[str, Any]) -> bool:
        return str(dict(candidate or {}).get("source") or "") in ATELIER_SOURCES

    def selection_score(self, field, candidate: Mapping[str, Any], *,
                        now: float, readiness: Mapping[str, Any] = None):
        state = dict(readiness or self.readiness(field))
        eligible = self.eligible(candidate) \
            and "atelier" in getattr(self.engine, "enabled", set())
        atelier_satiety = field.satiety.warmth("atelier", now)
        readiness_value = (
            max(0.0, min(1.0, _finite(state.get("readiness"))))
            / (1.0 + atelier_satiety) if eligible else 0.0)
        score, meta = field.attention_score(
            dict(candidate), now=now,
            action_readiness=readiness_value,
            action_eligible=eligible, scope_satiety=atelier_satiety)
        return score, {
            **meta, "atelier_eligible": eligible,
            "atelier_readiness": round(readiness_value, 6),
            "atelier_satiety": round(atelier_satiety, 6),
        }

    def _offer_seed(self, field, record: Mapping[str, Any], *, now: float):
        ownership = str(record.get("ownership") or "human_admitted")
        description = (
            "Self-chosen creative material"
            if ownership in {
                "persona_chosen_conversation", "persona_chosen_autonomy"}
            else "Project-chosen private creative material"
            if ownership == "persona_project_handoff"
            else "Human-admitted creative material")
        candidate = offer_maintenance_candidate(
            self, field, "atelier_seed",
            f"{description} named "
            f"{record.get('label') or 'untitled'} is waiting in the atelier.",
            {"novelty": 1.0, "affect_change": 0.0,
             "body_intensity": 0.0, "relationship": 1.0,
             "unresolved": 1.0},
            key=f"atelier_seed:{record['seed_id']}", now=now,
            raw_ref=record.get("source_digest"),
            ownership=ownership,
            receipts=[record.get("source_digest")])
        candidate.update({
            "seed_id": record["seed_id"],
            "satiety_key": f"atelier_seed:{record['seed_id']}",
            **lease_fields(record, origin="atelier_seed"),
        })
        return candidate

    def refresh_pending(self, field, *, now: float = None) -> list[dict]:
        """Recur unresolved material only at the caller's actual DMN fire."""
        now = time.time() if now is None else float(now)
        if "atelier" not in getattr(self.engine, "enabled", set()):
            return []
        offered = [self._offer_seed(field, seed, now=now)
                   for seed in self.atelier.pending_seeds()]
        if offered:
            self._emit(
                "atelier_recurred", candidate_count=len(offered),
                candidate_keys=[value.get("key") for value in offered])
        return offered

    def admit_seed(self, field, label: str, brief: str, *,
                   now: float = None,
                   ownership: str = "human_admitted") -> dict:
        now = time.time() if now is None else float(now)
        record = self.atelier.admit_seed(
            label, brief, ownership=ownership)
        candidate = self._offer_seed(field, record, now=now)
        field.save(now=now)
        self._emit(
            "atelier_seed_admitted", seed_id=record["seed_id"],
            candidate_key=candidate.get("key"),
            content_chars=record.get("chars", 0),
            duplicate=record.get("duplicate", False))
        return {"record": record, "candidate": candidate}

    def offer_latest_artifact(self, audience: str, *,
                              allowed_audiences=()) -> dict:
        """Honor one resident-authored exact in-house offer."""
        audience = str(audience or "").strip().casefold()
        allowed = {
            str(item or "").strip().casefold()
            for item in (allowed_audiences or ())
            if str(item or "").strip()}
        if audience not in allowed:
            raise ValueError("atelier audience is not an exact admitted resident")
        record = self.atelier.offer_latest_artifact(
            audience=audience,
            offered_by=str(getattr(self.engine, "persona", "") or ""))
        self._emit(
            "atelier_artifact_offered",
            artifact_id=record.get("artifact_id"),
            audience=record.get("audience"),
            duplicate=record.get("duplicate", False),
            external_effects=False)
        return {
            "ok": True,
            "artifact_id": record.get("artifact_id"),
            "audience": record.get("audience"),
            "duplicate": record.get("duplicate", False),
            "external_effects": False,
        }

    def consume_internal_action(self, selection: Mapping[str, Any]) -> dict:
        """Owner-validate one local private creation handoff."""
        selection = dict(selection or {})
        if selection.get("capability") != "atelier.private_creation" \
                or selection.get("owner") != "atelier":
            raise ValueError("internal action is not owned by Atelier")
        if selection.get("authority_scope") \
                != "wrapper_local_private_reversible" \
                or selection.get("external_effects") is not False \
                or selection.get("tool_binding") is not None \
                or selection.get("scheduler_slot") is not None:
            raise ValueError("internal Atelier action exceeded wrapper authority")
        payload = dict(selection.get("payload") or {})
        provenance = dict(payload.get("project_loom_provenance") or {})
        allowed_provenance = {
            "proposal_id", "orientation_id", "candidate_id", "selection_mode"}
        if not set(provenance).issubset(allowed_provenance) \
                or not {"proposal_id", "candidate_id"}.issubset(provenance) \
                or any(not str(value or "").strip()
                       for value in provenance.values()):
            raise ValueError("internal Atelier action provenance is incomplete")
        label = str(payload.get("label") or "").strip()
        brief = str(payload.get("content") or "").strip()
        if not label or not brief:
            raise ValueError("internal Atelier action needs bounded private material")
        record = self.atelier.admit_seed(
            label, brief, ownership="persona_project_handoff")
        self._emit(
            "atelier_internal_action_admitted",
            selection_id=selection.get("selection_id"),
            seed_id=record.get("seed_id"),
            duplicate=record.get("duplicate", False),
            capability="atelier.private_creation",
            ownership="persona_project_handoff")
        return record

    def request_opening(self, field, *, now: float = None) -> dict:
        """Open one explicit human-requested attempt outside autonomous caps."""
        now = time.time() if now is None else float(now)
        if self.controller.status().get("active"):
            return {"started": False, "reason": "attention_occupied"}
        readiness = self.readiness(field)
        candidates = [
            dict(item) for item in field.queue.items(now)
            if self.eligible(item) and self._candidate_current(item)]
        if not candidates:
            self.refresh_pending(field, now=now)
            candidates = [
                dict(item) for item in field.queue.items(now)
                if self.eligible(item) and self._candidate_current(item)]
        if not candidates:
            return {"started": False, "reason": "no_pending_material"}

        ranked = []
        for candidate in candidates:
            score, meta = self.selection_score(
                field, candidate, now=now, readiness=readiness)
            ranked.append((
                float(score), float(candidate.get("salience", 0.0)),
                str(candidate.get("key") or ""), candidate, meta))
        score, _salience, _key, candidate, score_meta = max(ranked)
        removed = field.queue.discard_where(
            lambda item: item.get("key") == candidate.get("key"),
            reason="human_requested_atelier_opening", now=now)
        if not removed:
            return {"started": False, "reason": "candidate_changed"}
        field.save(now=now)
        result = self.start_candidate(candidate)
        if not result.get("started"):
            field.queue.put(
                candidate, float(candidate.get("salience", 0.05)), now=now,
                offer_meta={
                    "operation": "requeued",
                    "reason": result.get("reason") or
                              "direct_opening_failed"})
            field.save(now=now)
            return result
        self.atelier.record_receipt({
            "kind": "human_requested_atelier_opening",
            "run_id": result.get("run_id"),
            "candidate_key": candidate.get("key"),
            "seed_id": candidate.get("seed_id"),
            "outcome": "started",
            "model": self.config.model,
            "selection_score": round(score, 6),
            "estimated_cost_usd": 0.0,
        })
        self._emit(
            "human_requested_atelier_opening",
            run_id=result.get("run_id"),
            candidate_key=candidate.get("key"),
            selection_score=round(score, 6),
            selection_meta=score_meta)
        return {
            key: value for key, value in result.items() if key != "future"}

    def _expression_vector(self) -> dict[str, float]:
        values = {}
        for key, value in dict(getattr(self.engine, "cocktail", {}) or {}).items():
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                values[f"cocktail.{str(key)[:60]}"] = max(
                    0.0, min(1.0, float(value)))
        oscillator = getattr(self.engine, "osc", None)
        for key, value in dict(getattr(oscillator, "bands", {}) or {}).items():
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                values[f"band.{str(key)[:60]}"] = max(
                    0.0, min(1.0, float(value)))
        coherence = getattr(oscillator, "coherence", None)
        if callable(coherence):
            coherence = coherence()
        if isinstance(coherence, (int, float)) and math.isfinite(float(coherence)):
            values["band.coherence"] = max(0.0, min(1.0, float(coherence)))
        try:
            from shell.autonomy_circulation import affect_projection_from_engine
            color = dict(affect_projection_from_engine(
                self.engine).get("color") or {})
        except Exception:
            color = {}
        for key in ("red", "green", "blue", "luma", "chroma",
                    "warmth", "present"):
            value = color.get(key)
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                values[f"affect.color.{key}"] = max(
                    0.0, min(1.0, float(value)))
        soma = getattr(self.engine, "soma", None)
        for key, value in dict(getattr(soma, "signals", {}) or {}).items():
            if key in {"play", "vagal_tone", "prediction_violation", "bond"} \
                    and isinstance(value, (int, float)) \
                    and not isinstance(value, bool) and math.isfinite(float(value)):
                values[f"body.{key}"] = max(0.0, min(1.0, float(value)))
        return values

    def _assembly(self, candidate: Mapping[str, Any], spec):
        seed = self.atelier.seed(candidate.get("seed_id"), include_brief=True)
        available = [{
            "artifact_id": item.get("artifact_id"),
            "title": str(item.get("title") or "")[:160],
            "medium": item.get("medium"), "variant": item.get("variant"),
            "sha256": item.get("sha256"),
        } for item in self.atelier.artifacts_status()
            if item.get("medium") != "composition"]
        family_for = {
            "svg": "visual2d", "png": "visual2d", "webp": "visual2d",
            "canvas": "visual2d", "scene3d": "spatial", "audio": "audio",
        }
        families = {family_for.get(str(item.get("medium") or ""))
                    for item in available}
        families.discard(None)
        composition_ready = len(families) >= 2 and bool(
            families.intersection({"visual2d", "spatial"}))
        medium_law = (
            "Available forms are static SVG, kinetic SVG, Canvas, procedural "
            "sound, trusted 3D, "
            + ("cross-medium composition, " if composition_ready else "")
            + "and local "
            "ComfyUI diffusion. "
            if self.config.diffusion_enabled else
            "Available forms are static SVG, kinetic SVG, Canvas, and procedural "
            "sound, trusted 3D"
            + (", and cross-medium composition" if composition_ready else "")
            + "; "
            "diffusion is disabled. ")
        task = (
            "This material has won attention inside your private atelier. "
            "It is an invitation, not an order to perform. Notice what you "
            "are feeling now and what creative form, if any, seems to arise "
            "from the material. You may leave it quiet. Do not assign an "
            "emotion to yourself because the brief names one. " + medium_law +
            "Choose the form as part of what arises, without mapping a named "
            "feeling through a fixed style lookup. Follow the separate renderer "
            "contract exactly. Return one JSON object and nothing else. Nothing "
            "will be published, messaged, installed, or routed to a paid provider."
        )
        renderer_contract = (
            "Return exactly: action,title,svg,scene,score,composition,motions,prompt,negative_prompt,aspect. "
            "The complete JSON object must close inside this bounded response. "
            "Scale detail, node count, event count, object count, and SVG path "
            "complexity down together when needed; a smaller complete form is "
            "admissible and a truncated form is not. "
            "Actions: quiet, create_svg, create_kinetic_svg, create_canvas, "
            "create_audio, create_3d, create_composition, create_diffusion. Unused text fields are empty; unused scene/score/composition are {}; "
            "unused motions is []; quiet and Canvas use top-level aspect 1.0. "
            "SVG uses only svg,g,defs,path,rect,circle,ellipse,line,polyline,polygon,"
            "text,tspan,linearGradient,radialGradient,stop,clipPath with inline "
            "attributes, finite viewBox/canvas 16..4096, and no CSS, script, "
            "animation, events, media, links, or remote references. Kinetic SVG "
            "adds safe ids plus 1..12 motions. Motion exact keys: target,channel,"
            "intensity,rate,phase,x,y; intensity/rate/phase 0..1; x/y -1..1. "
            "Kinetic channels: translate,rotate,opacity. Static SVG motions=[]. "
            "Canvas scene exact keys: aspect,background,nodes; aspect .625..1.6; "
            "background #RRGGBB; 1..80 unique-id nodes. Exact node keys by kind: "
            "circle(id,kind,x,y,radius,fill,stroke,line_width,opacity); "
            "rect(id,kind,x,y,width,height,corner,fill,stroke,line_width,opacity,rotation); "
            "path(id,kind,points,closed,fill,stroke,line_width,opacity); "
            "text(id,kind,x,y,text,fill,font_size,align,opacity,rotation); "
            "particles(id,kind,x,y,width,height,count,radius,fill,opacity,seed). "
            "Canvas numbers are normalized 0..1 except rotation -1..1; colors "
            "are #RRGGBB or empty only for alternative fill/stroke; path points "
            "are [x,y] pairs; align left/center/right; count 1..240. Canvas "
            "motions may be empty and channels are translate,rotate,scale,opacity,"
            "orbit. The host owns all drawing/timing code. Audio score exact keys: "
            "tempo,beats,tonic,scale,seed,voices,events; tempo 48..168; beats integer "
            "4..16; tonic MIDI 36..84; seed 0..1; scale major_pentatonic,minor_pentatonic,"
            "dorian,mixolydian,harmonic_minor,whole_tone. Voice exact keys: id,wave,gain,"
            "attack,release,pan,filter; wave sine/triangle/sawtooth/square; gain .05..1; "
            "attack/release/filter 0..1; pan -1..1; 1..6 unique voices. Event exact keys: "
            "voice,beat,duration,degree,octave,velocity,probability; 1..96 events; beat "
            "0..<beats; duration .125..beats and must close inside the cycle; degree integer "
            "0..20; octave integer -2..2; velocity/probability .05..1. Audio uses empty "
            "svg/scene/motions/prompt fields and top-level aspect 1.0. The host owns all "
            "sound synthesis, timing, gain ceilings, and playback. Diffusion uses prompt, "
            "optional negative_prompt, empty svg/scene/motions, aspect .625..1.6. "
            "3D scene exact keys: background,camera,ambient,lights,objects. Camera exact "
            "keys: x,y,z,target_x,target_y,target_z,fov; x/y -4..4; z 1..6; targets "
            "-2..2; fov 30..80. Ambient .02..1. One through three lights exact keys "
            "x,y,z,color,intensity; positions -4..4; color #RRGGBB; intensity .05..2. "
            "One through 24 objects exact keys: id,kind,x,y,z,scale_x,scale_y,scale_z,"
            "rotation_x,rotation_y,rotation_z,color,roughness,metallic,opacity. Kind is "
            "sphere,box,torus,plane; position -2..2; scale .05..2; rotation -1..1; "
            "color #RRGGBB; material values 0..1; opacity .15..1. 3D motions may be "
            "empty and use the Canvas motion shape/channels. The host exclusively owns "
            "meshes, matrices, shaders, draw calls, timing, and freeze-frame rendering. "
            "Composition is available only when the separate private-artifact catalog "
            "contains at least two medium families including a visual family. Composition "
            "exact keys: tempo,beats,background,aspect,tracks; tempo 48..168; beats integer "
            "4..32; background #RRGGBB; aspect .625..1.6; 2..12 tracks. Track exact keys: "
            "artifact_id,start_beat,duration_beats,gain,opacity,depth,phase. Use only exact "
            "artifact_id values from that catalog, once each; start 0..<beats; duration "
            ".125..beats and must close inside the cycle; gain/opacity/phase 0..1; depth "
            "-1..1. A composition must cross at least two catalog medium families and have "
            "a visual track. It cannot reference a composition. Composition uses empty "
            "svg/scene/score/motions/prompt fields and top-level aspect 1.0. The host binds "
            "source hashes and owns the shared cyclic clock, audio scheduling, visual draw, "
            "finite return, and freeze-frame rendering."
        )
        source = {
            "kind": "seed", "seed_id": seed["seed_id"],
            "source_digest": seed["source_digest"],
            "candidate_key": candidate.get("key"),
            "candidate_salience": candidate.get("salience"),
        }
        envelope = AgencyTaskEnvelope(
            task=task, source_kind="atelier_seed",
            source_ref=str(candidate.get("key")),
            source_digest=seed["source_digest"],
            source_summary="Admitted material is available for possible creative form.",
            source_ownership=str(candidate.get("ownership") or
                                 "human_admitted"),
            authority_tier=self.config.authority_tier,
        )
        product = self.engine.build_agency_snapshot(
            envelope, substrate_mode="on",
            external_demand_epoch=self.controller.live_epoch(),
            agency_spec=spec, agency_model=self.config.model)
        product.assembly.add(
            "atelier_renderer_contract", renderer_contract,
            priority=9, budget=2250)
        product.assembly.add(
            "atelier_available_artifacts",
            json.dumps({"composition_ready": composition_ready,
                        "artifacts": available}, ensure_ascii=False,
                       sort_keys=True),
            priority=9, budget=1100)
        product.assembly.add(
            "atelier_material",
            f"Material label: {seed['label']}\n\n{seed['brief']}",
            priority=9, budget=1500)
        return product, source, self._expression_vector()

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

    def _commit(self, context, candidate, proposal, source, expression_vector):
        if proposal["action"] == "quiet":
            record = self.atelier.resolve_seed(
                candidate["seed_id"], context.run_id, "quiet")
            return "quiet", record, {}
        renderer = {}
        if proposal["action"] == "create_svg":
            record = self.atelier.create_svg(
                context.run_id, proposal["title"], proposal["svg"],
                source=source, expression_vector=expression_vector)
        elif proposal["action"] == "create_kinetic_svg":
            record = self.atelier.create_kinetic_svg(
                context.run_id, proposal["title"], proposal["svg"],
                proposal["motions"], source=source,
                expression_vector=expression_vector)
        elif proposal["action"] == "create_canvas":
            record = self.atelier.create_canvas(
                context.run_id, proposal["title"], proposal["scene"],
                proposal["motions"], source=source,
                expression_vector=expression_vector)
        elif proposal["action"] == "create_audio":
            record = self.atelier.create_audio(
                context.run_id, proposal["title"], proposal["score"],
                source=source, expression_vector=expression_vector)
        elif proposal["action"] == "create_3d":
            record = self.atelier.create_scene3d(
                context.run_id, proposal["title"], proposal["scene"],
                proposal["motions"], source=source,
                expression_vector=expression_vector)
        elif proposal["action"] == "create_composition":
            record = self.atelier.create_composition(
                context.run_id, proposal["title"], proposal["composition"],
                source=source, expression_vector=expression_vector)
        else:
            if not self.config.diffusion_enabled or self.comfy is None:
                raise ValueError("diffusion is not enabled for this Atelier")
            rendered = self.comfy.generate(
                prompt=proposal["prompt"],
                negative_prompt=proposal["negative_prompt"],
                source_digest=source["source_digest"],
                expression_vector=expression_vector,
                aspect=proposal["aspect"],
                cancellation=context.cancellation)
            raster_source = {
                **source, "renderer": rendered["renderer"],
                "checkpoint": rendered["checkpoint"],
                "parameters": rendered["parameters"],
                "prompt_digest": _digest(proposal["prompt"]),
                "negative_prompt_digest": _digest(
                    proposal["negative_prompt"]),
                "comfy_prompt_id_digest": _digest(rendered["prompt_id"]),
            }
            record = self.atelier.create_raster(
                context.run_id, proposal["title"], rendered["data"],
                medium=rendered["medium"], source=raster_source,
                expression_vector=expression_vector)
            renderer = {key: rendered.get(key) for key in (
                "renderer", "checkpoint", "http_attempts", "parameters")}
        self.atelier.resolve_seed(
            candidate["seed_id"], context.run_id, "artifact_created",
            artifact_id=record["artifact_id"])
        return f"created_{record['medium']}", record, renderer

    def _candidate_current(self, candidate: Mapping[str, Any]) -> bool:
        if str(dict(candidate or {}).get("source") or "") != "atelier_seed":
            return False
        seed_id = candidate.get("seed_id")
        return seed_id in {
            value.get("seed_id") for value in self.atelier.pending_seeds()}

    def start_candidate(self, candidate: Mapping[str, Any]) -> dict:
        candidate = dict(candidate or {})
        if not self.eligible(candidate):
            return {"started": False, "reason": "not_eligible"}
        if not self._candidate_current(candidate):
            return {"started": False, "reason": "stale_candidate"}
        # Controller.start() admits on its async loop, so merely obtaining a
        # Future does not mean this candidate owns the persona slot.  Refuse
        # synchronously while another organ/run is active; otherwise the DMN
        # loop can report a false Atelier start and later requeue it as an
        # ActiveAgencyRun while a human-requested opening is still healthy.
        if self.controller.status().get("active"):
            return {"started": False, "reason": "attention_occupied"}
        readiness = self.readiness(getattr(self.engine, "idle_metabolism", None))
        capability = self.capability()
        if not capability["usable"]:
            self._emit(
                "atelier_refused", reason=capability["reason"],
                candidate_key=candidate.get("key"), model=self.config.model)
            return {"started": False, "reason": capability["reason"]}
        spec = self._load_spec()
        try:
            product, source, expression_vector = self._assembly(candidate, spec)
        except Exception as exc:
            return {"started": False, "reason": type(exc).__name__}
        proposal_id = _digest({
            "candidate": candidate.get("key"),
            "updated": candidate.get("updated"),
            "state_ref": product.state_ref,
        })
        run_id = f"atelier-{proposal_id}"
        adapter = self._model_adapter(spec)
        identity = dict(spec.get("identity") or {})

        async def runner(context):
            cycle_id = new_cycle_id()
            events = []
            model_requests = 1
            with model_call_scope(
                    cycle_id=cycle_id,
                    persona=getattr(self.engine, "persona", "unknown"),
                    purpose="atelier_creative"):
                try:
                    event_args = {
                        "tools": (), "exchanges": (),
                        "max_tokens": self.config.max_tokens,
                        "temperature": product.temperature,
                        "cancel": context.cancellation,
                    }
                    if str(identity.get("provider") or "") == "ollama":
                        # Ollama's union-schema grammar can make Qwen expand
                        # unused renderer objects until the bounded completion
                        # is truncated. JSON mode closes the syntax; the
                        # host's exact per-medium validators remain authority.
                        event_args["output_format"] = "json"
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
            try:
                proposal = parse_atelier_proposal(text)
            except ValueError as first_error:
                # One local-only correction is cheaper than repeatedly
                # returning the same valid seed to the wider field.  The
                # rejected response is never committed, and the correction
                # describes only the schema error—not private output text.
                legacy_choice = _legacy_form_action(text)
                dialect_instruction = (
                    f"You already chose {legacy_choice[0]!r}. Preserve that "
                    f"choice as action {legacy_choice[1]!r}; translate the "
                    "private draft supplied in atelier_translation_source "
                    "into that renderer's exact structured "
                    "field, then leave every other renderer field neutral. "
                    f"{LEGACY_TRANSLATION_HINTS[legacy_choice[1]]} "
                    if legacy_choice else "")
                if legacy_choice:
                    # This is private, model-authored working material, not a
                    # receipt or an outward log.  The correction must actually
                    # receive the draft it is being asked to compile; without
                    # it, the second pass can only guess from the original seed.
                    product.assembly.add(
                        "atelier_translation_source", text,
                        priority=10, budget=min(
                            900, max(160, len(str(text or "")) // 3)))
                product.assembly.add(
                    "atelier_schema_correction",
                    "The previous object was not admissible: "
                    f"{str(first_error)[:180]}. This is the Atelier, not the "
                    "Writing Desk. Return one new object using only these "
                    "exact top-level keys: action,title,svg,scene,score,"
                    "composition,motions,prompt,negative_prompt,aspect. "
                    "Do not use form or content. " + dialect_instruction +
                    ("Reconsider the same admitted material; quiet remains "
                     "valid." if not legacy_choice else ""),
                    priority=10, budget=260)
                repair_events = []
                with model_call_scope(
                        cycle_id=new_cycle_id(),
                        persona=getattr(self.engine, "persona", "unknown"),
                        purpose="atelier_schema_correction"):
                    repair_args = {
                        "tools": (), "exchanges": (),
                        "max_tokens": self.config.max_tokens,
                        "temperature": product.temperature,
                        "cancel": context.cancellation,
                    }
                    if str(identity.get("provider") or "") == "ollama":
                        repair_args["output_format"] = (
                            _translation_output_format(legacy_choice[1])
                            if legacy_choice else "json")
                    repair_events = [event async for event in adapter.events(
                        product.assembly, **repair_args)]
                    repair_usage = self._usage(repair_events)
                    repair_attempts = 1 + len(getattr(
                        getattr(adapter, "event_transport", None),
                        "last_attempt_receipts", ()) or ())
                    record_model_call(
                        str(identity.get("provider") or "unknown"),
                        str(identity.get("endpoint") or self.config.model),
                        {**repair_usage, "attempts": repair_attempts},
                        status="ok")
                context.cancellation.raise_if_cancelled()
                try:
                    proposal = parse_atelier_proposal(collect_legacy_text(
                        repair_events, context.cancellation))
                except ValueError as correction_error:
                    raise ValueError(
                        f"initial proposal: {str(first_error)[:140]}; "
                        f"correction: {str(correction_error)[:140]}") \
                        from correction_error
                usage = {
                    key: int(usage.get(key) or 0)
                    + int(repair_usage.get(key) or 0)
                    for key in ("input_tokens", "output_tokens", "total_tokens")
                }
                attempts += repair_attempts
                model_requests = 2
            outcome, record, renderer = self._commit(
                context, candidate, proposal, source, expression_vector)
            usage = self._usage(events)
            return AgencyRunOutcome(
                result={"outcome": outcome, "record": record,
                        "renderer": renderer,
                        "usage": usage,
                        "model_requests": model_requests,
                        "provider_http_attempts": attempts},
                metrics={"model_requests": model_requests,
                         "provider_http_attempts": attempts, **usage})

        try:
            future = self.controller.start(
                run_id, runner, proposal_id=proposal_id,
                interruptible=False)
        except Exception as exc:
            return {"started": False, "reason": type(exc).__name__}
        future.add_done_callback(lambda done: self._completed(
            run_id, proposal_id, candidate, readiness, capability, done))
        self._emit(
            "atelier_proposed", run_id=run_id, proposal_id=proposal_id,
            candidate_key=candidate.get("key"), model=self.config.model,
            locality=capability.get("locality"),
            media=capability.get("media"))
        return {"started": True, "run_id": run_id,
                "proposal_id": proposal_id, "future": future}

    def _completed(self, run_id, proposal_id, candidate, readiness,
                   capability, future) -> None:
        try:
            outcome = future.result()
            result = dict(getattr(outcome, "result", {}) or {})
        except Exception as exc:
            self._effects.put({
                "kind": "retry", "run_id": run_id,
                "proposal_id": proposal_id, "candidate": dict(candidate),
                "reason": ("interrupted" if isinstance(
                    exc, concurrent.futures.CancelledError)
                    else f"failed:{type(exc).__name__}:{str(exc)[:180]}"),
            })
            return
        record = dict(result.get("record") or {})
        renderer = dict(result.get("renderer") or {})
        self._effects.put({
            "kind": "settled", "run_id": run_id,
            "proposal_id": proposal_id, "candidate": dict(candidate),
            "outcome": result.get("outcome") or "quiet",
            "artifact_id": record.get("artifact_id"),
            "medium": record.get("medium"),
            "record_digest": _digest(record),
            "usage": dict(result.get("usage") or {}),
            "model_requests": int(result.get("model_requests") or 1),
            "provider_http_attempts": int(
                result.get("provider_http_attempts") or 1),
            "model": self.config.model,
            "provider": capability.get("provider"),
            "locality": capability.get("locality"),
            "readiness": readiness.get("readiness", 0.0),
            "renderer": renderer,
        })
        self._emit(
            "atelier_effect_ready", run_id=run_id,
            proposal_id=proposal_id, outcome=result.get("outcome"),
            artifact_id=record.get("artifact_id"),
            medium=record.get("medium"))

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
                self.atelier.record_receipt({
                    "kind": "atelier_run_failed",
                    "run_id": effect["run_id"],
                    "candidate_key": candidate.get("key"),
                    "seed_id": candidate.get("seed_id"),
                    "outcome": "failed_requeued",
                    "reason": effect["reason"],
                    "model": self.config.model,
                    "estimated_cost_usd": 0.0,
                })
                restored = field.queue.put(
                    candidate, float(candidate.get("salience", 0.05)),
                    now=now, offer_meta={
                        "operation": "requeued", "reason": effect["reason"]})
                admitted.append(restored)
                continue
            source_candidate = dict(effect["candidate"])
            source_satiety = field.satiate(source_candidate, now=now)
            atelier_satiety = field.satiety.touch(
                "atelier", max(0.0, min(1.0, float(
                    source_candidate.get("salience", 0.0)))),
                label="atelier", now=now)
            outcome = str(effect.get("outcome") or "quiet")
            if outcome == "quiet":
                event_text = (
                    "A private atelier pull settled without an artifact. "
                    "Nothing was published, sent, or overwritten.")
                novelty = 0.0
            else:
                medium = str(effect.get("medium") or "visual")
                event_text = (
                    f"A self-chosen private {medium.upper()} artifact took form in the "
                    "atelier. It remains available to be seen; it was not "
                    "published, sent, installed, or made into memory.")
                novelty = 1.0
            felt = None
            try:
                felt = circulate_experienced_event(self.engine, event_text)
            except Exception as exc:
                self._emit(
                    "atelier_effect_failed", run_id=effect["run_id"],
                    error_type=f"felt_consequence:{type(exc).__name__}")
            usage = dict(effect.get("usage") or {})
            self.atelier.record_receipt({
                "run_id": effect["run_id"],
                "candidate_key": source_candidate.get("key"),
                "outcome": outcome, "artifact_id": effect.get("artifact_id"),
                "seed_id": source_candidate.get("seed_id"),
                "medium": effect.get("medium") or "unknown",
                "model": effect.get("model"),
                "provider": effect.get("provider"),
                "locality": effect.get("locality"),
                "model_requests": effect.get("model_requests", 1),
                "provider_http_attempts": effect.get(
                    "provider_http_attempts", 1),
                "renderer": dict(effect.get("renderer") or {}).get("renderer"),
                "renderer_http_attempts": dict(
                    effect.get("renderer") or {}).get("http_attempts"),
                "checkpoint": dict(
                    effect.get("renderer") or {}).get("checkpoint"),
                **usage, "estimated_cost_usd": 0.0,
                "readiness": effect.get("readiness"),
                "source_satiety": source_satiety,
                "atelier_satiety": atelier_satiety,
            })
            if self.internal_outcome_sink is not None \
                    and source_candidate.get("seed_id"):
                try:
                    self.internal_outcome_sink(
                        source_candidate["seed_id"],
                        run_id=effect["run_id"], outcome=outcome,
                        durable_ref=effect.get("artifact_id") or "",
                        usage={**usage, "estimated_cost_usd": 0.0})
                except ValueError:
                    pass
            candidate = field.offer_cognitive_event(
                "atelier_effect", event_text,
                {"novelty": novelty,
                 "affect_change": _finite((felt or {}).get(
                     "affect_change"), 0.0),
                 "body_intensity": 0.0, "relationship": 0.0,
                 "unresolved": 0.0},
                key=f"atelier_effect:{effect['run_id']}", now=now,
                raw_ref=effect.get("artifact_id") or effect.get("record_digest"),
                ownership="persona_private",
                receipts=[effect.get("artifact_id")
                          or effect.get("record_digest")])
            admitted.append(candidate)
            self._emit(
                "atelier_field_reentry", run_id=effect["run_id"],
                outcome=outcome, candidate_key=candidate.get("key"),
                artifact_id=effect.get("artifact_id"),
                atelier_satiety=atelier_satiety)
        if admitted:
            field.save(now=now)
            if self._observer is not None:
                self._observer.field_snapshot(field, now)
        return admitted

    def status(self) -> dict:
        field = getattr(self.engine, "idle_metabolism", None)
        pending = self.atelier.pending_seeds()
        pending_keys = {
            f"atelier_seed:{item.get('seed_id')}" for item in pending}
        live_keys = set()
        pressure = None
        threshold = None
        recent_fires = None
        max_fires = None
        cooldown_remaining = None
        if field is not None:
            try:
                now = time.time()
                live_keys = {
                    str(item.get("key") or "")
                    for item in field.queue.items(now)
                    if str(item.get("key") or "") in pending_keys}
                pressure = float(field.pressure.pressure)
                threshold = float(field.pressure.p.get("fire_threshold", 1.0))
                recent_fires = len([
                    fired for fired in field.pressure.fires
                    if now - float(fired) <= 3600.0])
                max_fires = int(field.pressure.p.get(
                    "max_fires_per_hour", 0))
                cooldown_remaining = max(
                    0.0, float(field.pressure.p.get("cooldown_s", 0.0))
                    - (now - float(field.pressure.last_fire or 0.0)))
            except (AttributeError, TypeError, ValueError):
                pass
        return {
            "enabled": "atelier" in getattr(self.engine, "enabled", set()),
            "config": {
                "model": self.config.model,
                "authority_tier": self.config.authority_tier,
                "local_only": self.config.local_only,
                "max_tokens": self.config.max_tokens,
                "diffusion_enabled": self.config.diffusion_enabled,
                "comfy_endpoint": self.config.comfy_endpoint,
                "comfy_checkpoint": self.config.comfy_checkpoint,
            },
            "capability": self.capability(),
            "controller": self.controller.status(),
            "readiness": self.readiness(field),
            "field_evidence": {
                "pending_count": len(pending_keys),
                "circulating_count": len(live_keys),
                "all_pending_circulating": bool(
                    pending_keys and live_keys == pending_keys),
                "pressure": (
                    round(pressure, 6) if pressure is not None else None),
                "fire_threshold": (
                    round(threshold, 6) if threshold is not None else None),
                "recent_fire_count": recent_fires,
                "max_fires_per_hour": max_fires,
                "hourly_capped": bool(
                    max_fires and recent_fires is not None
                    and recent_fires >= max_fires),
                "cooldown_remaining_s": (
                    round(cooldown_remaining, 3)
                    if cooldown_remaining is not None else None),
            },
            "atelier": self.atelier.status(),
        }

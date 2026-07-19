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
from harness.model_call_receipts import (
    model_call_scope, new_cycle_id, record_model_call,
)
from shell.agency_controller import AgencyRunOutcome
from shell.autonomy_circulation import (
    circulate_experienced_event, readiness_from_engine,
)
from shell.comfyui_client import ComfyUIClient, ComfyUIConfig


ATELIER_SOURCES = frozenset({"atelier_seed"})
ATELIER_AUTHORITY_TIER = 2
ATELIER_ACTIONS = frozenset({
    "quiet", "create_svg", "create_kinetic_svg", "create_canvas",
    "create_audio", "create_3d", "create_diffusion",
})


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
    legacy = {"action", "title", "svg"}
    allowed = {"action", "title", "svg", "scene", "score", "motions", "prompt",
               "negative_prompt", "aspect"}
    unknown = set(proposal) - allowed
    if unknown:
        raise ValueError(
            f"atelier proposal contains unknown fields: {sorted(unknown)}")
    at4 = allowed - {"score"}
    at3 = at4 - {"scene"}
    at2 = at3 - {"motions"}
    if frozenset(proposal) not in {
            frozenset(legacy), frozenset(at2), frozenset(at3),
            frozenset(at4), frozenset(allowed)}:
        raise ValueError("atelier proposal must contain the complete renderer shape")
    if "motions" in proposal and not isinstance(proposal["motions"], list):
        raise ValueError("atelier motions must be an array")
    if "scene" in proposal and not isinstance(proposal["scene"], dict):
        raise ValueError("atelier scene must be an object")
    if "score" in proposal and not isinstance(proposal["score"], dict):
        raise ValueError("atelier score must be an object")
    action = str(proposal.get("action") or "").strip().casefold()
    if action not in ATELIER_ACTIONS:
        raise ValueError("atelier proposal action is invalid")
    value = {
        "action": action,
        "title": str(proposal.get("title") or "").strip(),
        "svg": str(proposal.get("svg") or "").strip(),
        "scene": proposal.get("scene", {}),
        "score": proposal.get("score", {}),
        "motions": proposal.get("motions", []),
        "prompt": str(proposal.get("prompt") or "").strip(),
        "negative_prompt": str(proposal.get("negative_prompt") or "").strip(),
        "aspect": _finite(proposal.get("aspect"), 1.0),
    }
    if action == "quiet" and any(
            value[key] for key in ("title", "svg", "scene", "score", "motions",
                                   "prompt", "negative_prompt")):
        raise ValueError("quiet atelier proposal must not carry an artifact")
    if action == "create_svg" and (
            not value["title"] or not value["svg"] or value["prompt"]
            or value["negative_prompt"] or value["motions"] or value["scene"]
            or value["score"]):
        raise ValueError("SVG atelier proposal requires only title and svg")
    if action == "create_kinetic_svg" and (
            not value["title"] or not value["svg"]
            or not isinstance(value["motions"], list) or not value["motions"]
            or value["prompt"] or value["negative_prompt"] or value["scene"]
            or value["score"]):
        raise ValueError(
            "kinetic SVG proposal requires title, svg, and motion vectors")
    if action == "create_canvas" and (
            not value["title"] or not isinstance(value["scene"], dict)
            or not value["scene"] or value["svg"] or value["prompt"]
            or value["negative_prompt"] or value["score"]
            or value["aspect"] != 1.0):
        raise ValueError(
            "Canvas proposal requires title, scene, optional motions, and aspect 1.0")
    if action == "create_audio" and (
            not value["title"] or not isinstance(value["score"], dict)
            or not value["score"] or value["svg"] or value["scene"]
            or value["motions"] or value["prompt"] or value["negative_prompt"]
            or value["aspect"] != 1.0):
        raise ValueError(
            "audio proposal requires title, score, and otherwise empty renderer fields")
    if action == "create_3d" and (
            not value["title"] or not isinstance(value["scene"], dict)
            or not value["scene"] or value["score"] or value["svg"]
            or value["prompt"] or value["negative_prompt"]
            or value["aspect"] != 1.0):
        raise ValueError(
            "3D proposal requires title, scene, optional motions, and aspect 1.0")
    if action == "create_diffusion" and (
            not value["title"] or not value["prompt"] or value["svg"]
            or value["motions"] or value["scene"] or value["score"]):
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
        media = (["svg", "kinetic svg", "canvas", "procedural audio",
                  "3d scene", "png"]
                 if self.config.diffusion_enabled
                 else ["svg", "kinetic svg", "canvas", "procedural audio",
                       "3d scene"])
        diffusion = {
            "enabled": self.config.diffusion_enabled,
            "renderer": "comfyui", "locality": "local",
            "checkpoint": self.config.comfy_checkpoint,
            "endpoint": self.config.comfy_endpoint,
            "last_probe": (dict(self.comfy.last_probe)
                           if self.comfy is not None and self.comfy.last_probe
                           else None),
        }
        enabled = "atelier" in getattr(self.engine, "enabled", set())
        if not enabled:
            return {
                "usable": False, "reason": "atelier organ is disabled",
                "model": self.config.model, "locality": "unknown",
                "provider": None, "event_bridge": False,
                "media": media, "diffusion": diffusion,
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
                "paid_fallbacks": 0,
            }
        except Exception as exc:
            return {
                "usable": False,
                "reason": f"atelier model unavailable: {type(exc).__name__}",
                "model": self.config.model, "locality": "unknown",
                "provider": None, "event_bridge": False,
                "media": media, "diffusion": diffusion,
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
            and "atelier" in getattr(self.engine, "enabled", set()) \
            and not state.get("hard_blocked")
        atelier_satiety = field.satiety.warmth("atelier", now)
        readiness_value = (
            max(0.0, min(1.0, _finite(state.get("readiness"))))
            / (1.0 + atelier_satiety) if eligible else 0.0)
        score, meta = field.attention_score(
            dict(candidate), now=now,
            action_readiness=readiness_value,
            action_eligible=eligible)
        return score, {
            **meta, "atelier_eligible": eligible,
            "atelier_readiness": round(readiness_value, 6),
            "atelier_satiety": round(atelier_satiety, 6),
        }

    def _offer_seed(self, field, record: Mapping[str, Any], *, now: float):
        candidate = field.offer_cognitive_event(
            "atelier_seed",
            f"Human-admitted creative material named "
            f"{record.get('label') or 'untitled'} is waiting in the atelier.",
            {"novelty": 1.0, "affect_change": 0.0,
             "body_intensity": 0.0, "relationship": 1.0,
             "unresolved": 1.0},
            key=f"atelier_seed:{record['seed_id']}", now=now,
            raw_ref=record.get("source_digest"),
            ownership="human_admitted",
            receipts=[record.get("source_digest")])
        candidate.update({
            "seed_id": record["seed_id"],
            "satiety_key": f"atelier_seed:{record['seed_id']}",
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
                   now: float = None) -> dict:
        now = time.time() if now is None else float(now)
        record = self.atelier.admit_seed(label, brief)
        candidate = self._offer_seed(field, record, now=now)
        field.save(now=now)
        self._emit(
            "atelier_seed_admitted", seed_id=record["seed_id"],
            candidate_key=candidate.get("key"),
            content_chars=record.get("chars", 0),
            duplicate=record.get("duplicate", False))
        return {"record": record, "candidate": candidate}

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
        soma = getattr(self.engine, "soma", None)
        for key, value in dict(getattr(soma, "signals", {}) or {}).items():
            if key in {"play", "vagal_tone", "prediction_violation", "bond"} \
                    and isinstance(value, (int, float)) \
                    and not isinstance(value, bool) and math.isfinite(float(value)):
                values[f"body.{key}"] = max(0.0, min(1.0, float(value)))
        return values

    def _assembly(self, candidate: Mapping[str, Any], spec):
        seed = self.atelier.seed(candidate.get("seed_id"), include_brief=True)
        medium_law = (
            "Available forms are static SVG, kinetic SVG, Canvas, procedural "
            "sound, trusted 3D, and local "
            "ComfyUI diffusion. "
            if self.config.diffusion_enabled else
            "Available forms are static SVG, kinetic SVG, Canvas, and procedural "
            "sound, and trusted 3D; "
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
            "Return exactly: action,title,svg,scene,score,motions,prompt,negative_prompt,aspect. "
            "Actions: quiet, create_svg, create_kinetic_svg, create_canvas, "
            "create_audio, create_3d, create_diffusion. Unused text fields are empty; unused scene/score are {}; "
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
            "meshes, matrices, shaders, draw calls, timing, and freeze-frame rendering."
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
            priority=9, budget=1800)
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

    def start_candidate(self, candidate: Mapping[str, Any]) -> dict:
        candidate = dict(candidate or {})
        if not self.eligible(candidate):
            return {"started": False, "reason": "not_eligible"}
        readiness = self.readiness(getattr(self.engine, "idle_metabolism", None))
        if readiness.get("hard_blocked"):
            return {"started": False, "reason": "state_blocked",
                    "readiness": readiness}
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
            with model_call_scope(
                    cycle_id=cycle_id,
                    persona=getattr(self.engine, "persona", "unknown"),
                    purpose="atelier_creative"):
                try:
                    events = [event async for event in adapter.events(
                        product.assembly, tools=(), exchanges=(),
                        max_tokens=self.config.max_tokens,
                        temperature=product.temperature,
                        cancel=context.cancellation)]
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
            if context.live_epoch() != context.captured_epoch:
                raise concurrent.futures.CancelledError(
                    "external demand changed before atelier commit")
            proposal = parse_atelier_proposal(text)
            outcome, record, renderer = self._commit(
                context, candidate, proposal, source, expression_vector)
            usage = self._usage(events)
            return AgencyRunOutcome(
                result={"outcome": outcome, "record": record,
                        "renderer": renderer,
                        "usage": usage,
                        "provider_http_attempts": attempts},
                metrics={"model_requests": 1,
                         "provider_http_attempts": attempts, **usage})

        try:
            future = self.controller.start(
                run_id, runner, proposal_id=proposal_id)
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
                    else f"failed:{type(exc).__name__}"),
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
                "locality": effect.get("locality"), "model_requests": 1,
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
            "readiness": self.readiness(
                getattr(self.engine, "idle_metabolism", None)),
            "atelier": self.atelier.status(),
        }

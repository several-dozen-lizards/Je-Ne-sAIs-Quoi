"""Adaptive exteroception for camera, microphone, and future sensors.

The organ owns no device and calls no model.  A driver emits a compact
SensoryEvent; this organ keeps the rolling modality field, computes admission
against the body's current rhythm, and returns small soma/oscillator pressures
to the bench.  Pixels and waveforms may stay at the edge.

Ownership is structural.  An observation about another person remains
``other``.  It may orient this body through raw sensory properties, but an
inferred emotion cannot enter the body's felt state without a later, explicitly
derived ``empathic`` or ``self`` event.
"""
from dataclasses import asdict, dataclass, field
import json
import math
import os
import time
import uuid


SCHEMA_VERSION = "1"
MODALITIES = frozenset({"camera", "audio"})
OWNERSHIPS = frozenset({"self", "other", "empathic", "ambient"})


def _clamp(value, low=0.0, high=1.0):
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return low


def _numeric_features(features):
    return {str(k): _clamp(v) for k, v in (features or {}).items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)}


@dataclass
class SensoryEvent:
    modality: str
    features: dict
    subject: str = "environment"
    ownership: str = "ambient"
    confidence: float = 1.0
    content: str = ""
    timestamp: float = field(default_factory=time.time)
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def __post_init__(self):
        if self.modality not in MODALITIES:
            raise ValueError(f"unknown sensory modality: {self.modality}")
        if self.ownership not in OWNERSHIPS:
            raise ValueError(f"unknown sensory ownership: {self.ownership}")
        self.subject = str(self.subject or "environment")[:120]
        self.content = str(self.content or "")[:4000]
        self.confidence = _clamp(self.confidence)
        self.features = _numeric_features(self.features)
        self.timestamp = float(self.timestamp or time.time())


class SensoryOrgan:
    """Persistent rolling field and rhythm-coupled admission gate."""

    def __init__(self, persona_dir: str):
        self.dir = os.path.join(persona_dir, "body", "perception")
        os.makedirs(self.dir, exist_ok=True)
        self.state_path = os.path.join(self.dir, "state.json")
        self.event_path = os.path.join(persona_dir, "history",
                                       "perception.jsonl")
        os.makedirs(os.path.dirname(self.event_path), exist_ok=True)
        self.state = self._load()

    def _load(self):
        try:
            with open(self.state_path, encoding="utf-8") as handle:
                state = json.load(handle)
        except (OSError, ValueError, TypeError):
            state = {}
        state.setdefault("schema_version", SCHEMA_VERSION)
        state.setdefault("modalities", {})
        state.setdefault("recent", [])
        return state

    def save(self):
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(self.state, handle, ensure_ascii=False, indent=1)
        os.replace(tmp, self.state_path)

    @staticmethod
    def policy(bands=None, coherence=1.0, occupied=False):
        """Return a continuous attention policy from the current rhythm.

        This is not a band-to-timer lookup.  The whole spectrum contributes to
        permeability, retention, and the admission boundary.  Drivers can use
        the same returned vector locally without streaming raw media.
        """
        b = {name: _clamp((bands or {}).get(name, 0.0))
             for name in ("delta", "theta", "alpha", "beta", "gamma")}
        if not any(b.values()):
            b = {"delta": .10, "theta": .15, "alpha": .30,
                 "beta": .30, "gamma": .15}
        total = sum(b.values()) or 1.0
        b = {name: value / total for name, value in b.items()}
        coherence = _clamp(coherence)
        permeability = (
            b["delta"] * .34 + b["theta"] * .62 + b["alpha"] * .86
            + b["beta"] * 1.08 + b["gamma"] * 1.24)
        permeability *= .74 + .26 * coherence
        if occupied:
            permeability *= .42
        threshold = _clamp(.52 / max(.28, permeability), .30, .92)
        retention_s = 1.0 + 2.4 * (b["theta"] + b["alpha"]) + .8 * coherence
        return {"permeability": round(permeability, 4),
                "threshold": round(threshold, 4),
                "retention_s": round(retention_s, 4)}

    @staticmethod
    def _demand(event, previous):
        f = event.features
        old = (previous or {}).get("features", {})
        shared = [k for k in f if k in old and k != "admission_pressure"]
        field_change = (sum(abs(f[k] - float(old[k])) for k in shared)
                        / len(shared) if shared else 0.0)
        if event.modality == "camera":
            demand = (.38 * f.get("novelty", field_change)
                      + .22 * f.get("motion", 0.0)
                      + .14 * f.get("brightness_delta", 0.0)
                      + .10 * f.get("edge_change", field_change)
                      + .08 * f.get("presence_change", 0.0)
                      + .08 * (1.0 - event.confidence))
        else:
            acoustic_power = (
                .30 * f.get("onset", 0.0)
                + .24 * f.get("spectral_flux", field_change)
                + .18 * f.get("level_change", 0.0)
                + .12 * f.get("speech_likelihood", 0.0)
                + .08 * f.get("music_likelihood", 0.0)
                + .08 * (1.0 - event.confidence))
            # Edge features combine like signal power; perception is closer
            # to amplitude.  This is the same concave transform used by the
            # browser accumulator, not a modality-specific boundary change.
            demand = math.sqrt(_clamp(acoustic_power))
        return _clamp(max(demand, field_change * .55))

    @staticmethod
    def _body_effects(event, demand):
        """Raw transduction only; semantic emotion never enters here.

        The camera-to-band weights below are an authored transduction prior,
        not physics and not a claim about feeling. S3 reuses this one existing
        prior unchanged instead of inventing a second camera theory.
        """
        f = event.features
        signals = {f"{event.modality}_{k}": v for k, v in f.items()
                   if k != "admission_pressure"}
        bands = {}

        def press(name, amount):
            if amount:
                bands[name] = bands.get(name, 0.0) + amount

        if event.modality == "camera":
            motion = f.get("motion", 0.0)
            brightness = f.get("brightness", .5)
            warmth = f.get("color_warmth", .5)
            saturation = f.get("saturation", 0.0)
            stability = f.get("stability", 1.0 - motion)
            press("beta", motion * .045 + saturation * .012)
            press("gamma", demand * .030
                  + f.get("brightness_delta", 0.0) * .025)
            press("alpha", stability * .018 + max(0.0, warmth - .5) * .020)
            press("theta", max(0.0, .5 - warmth) * .016
                  + max(0.0, .35 - brightness) * .022)
            press("delta", max(0.0, .22 - brightness) * .018)
        else:
            level = f.get("rms", 0.0)
            onset = f.get("onset", 0.0)
            flux = f.get("spectral_flux", 0.0)
            speech = f.get("speech_likelihood", 0.0)
            press("beta", level * .030 + flux * .030)
            press("gamma", onset * .040 + demand * .018)
            press("alpha", speech * .012)
            press("theta", max(0.0, .15 - level) * .012)

        # External affect is recorded, never smuggled into the felt body.
        if event.ownership == "other":
            signals["observed_other"] = event.confidence
        return signals, {k: round(v, 5) for k, v in bands.items()}

    def ingest(self, event: SensoryEvent, bands=None, coherence=1.0,
               occupied=False):
        previous = self.state["modalities"].get(event.modality, {})
        policy = self.policy(bands, coherence, occupied)
        demand = self._demand(event, previous)
        edge_pressure = event.features.get("admission_pressure", 0.0)
        pressure = max(edge_pressure, demand * policy["permeability"])
        admitted = pressure >= policy["threshold"]
        signals, band_pressure = self._body_effects(event, demand)
        record = {**asdict(event), "demand": round(demand, 4),
                  "pressure": round(pressure, 4), "policy": policy,
                  "admitted": admitted, "band_pressure": band_pressure}
        # A new raw crossing must not erase the last completed semantic
        # observation while its own transducer is still working.  Raw state
        # and what the pathway has actually resolved are two phases of one
        # perceptual cycle.
        semantic = dict(previous.get("semantic") or {})
        if not semantic and previous.get("content"):
            semantic = {
                "event_id": previous.get("event_id"),
                "content": previous.get("content"),
                "updated": previous.get("updated"),
                "subject": previous.get("subject", "environment"),
                "ownership": previous.get("ownership", "ambient"),
            }
        if event.content:
            semantic = {
                "event_id": event.event_id, "content": event.content,
                "updated": event.timestamp, "subject": event.subject,
                "ownership": event.ownership,
            }
        self.state["modalities"][event.modality] = {
            "features": event.features, "subject": event.subject,
            "ownership": event.ownership, "confidence": event.confidence,
            "content": event.content, "event_id": event.event_id,
            "updated": event.timestamp, "demand": record["demand"],
            "pressure": record["pressure"], "admitted": admitted,
            "semantic": semantic}
        self.state["recent"].append({
            "event_id": event.event_id, "modality": event.modality,
            "subject": event.subject, "ownership": event.ownership,
            "timestamp": event.timestamp, "admitted": admitted,
            "pressure": record["pressure"]})
        self.state["recent"] = self.state["recent"][-24:]
        self.save()
        with open(self.event_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return {**record, "signals": signals}

    def record_substrate(self, receipt: dict):
        """Persist one body-step substrate receipt without admission.

        TurnEngine calls this under its existing body/turn lock after the
        oscillator step. This path has no model and no DMN candidate.
        """
        record = dict(receipt or {})
        record["type"] = "substrate"
        record.setdefault("timestamp", time.time())
        record.setdefault("event_id", uuid.uuid4().hex)
        self.state["substrate"] = record
        self.save()
        with open(self.event_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def annotate(self, event_id: str, content: str):
        """Attach semantic transduction to an already admitted raw event."""
        content = str(content or "")[:4000]
        for modality in self.state["modalities"].values():
            if modality.get("event_id") == event_id:
                modality["content"] = content
                modality["semantic"] = {
                    "event_id": event_id, "content": content,
                    "updated": modality.get("updated", time.time()),
                    "subject": modality.get("subject", "environment"),
                    "ownership": modality.get("ownership", "ambient"),
                }
        self.save()

    def snapshot(self, bands=None, coherence=1.0, occupied=False):
        return {"modalities": dict(self.state["modalities"]),
                "recent": list(self.state["recent"]),
                "substrate": dict(self.state.get("substrate") or {}),
                "policy": self.policy(bands, coherence, occupied)}

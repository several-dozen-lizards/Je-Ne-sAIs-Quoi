"""Persistent endogenous perception-association dynamics.

These faculties exist before, during, and after any altered-state protocol.
The field is updated at body/event boundaries from the living substrate; a
protocol may bend its couplings but never creates perception or association
from zero.  All values are descriptive instrument readings, not named
feelings or instructions about what must be perceived.
"""
from __future__ import annotations

import json
import math
import os
import time
from typing import Any, Mapping


SCHEMA_VERSION = 1


def _clamp(value: Any, low: float = 0.0, high: float = 1.0) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return low
    if not math.isfinite(value):
        return low
    return max(low, min(high, value))


def _union(*values: float) -> float:
    product = 1.0
    for value in values:
        product *= 1.0 - _clamp(value)
    return 1.0 - product


AXES = (
    "associative_breadth", "sensory_gain", "cross_modal_permeability",
    "emotional_permeability", "novelty_gain",
    "prior_precision_relaxation", "inhibitory_softening",
    "contextual_susceptibility", "pattern_completion",
    "perceptual_motion", "imagery_intrusion", "semantic_permeability",
    "source_permeability", "source_certainty",
)


class PerceptualAssociativeField:
    """One slow, persistent field coupled to perception, memory, and body."""

    def __init__(self, persona_dir: str, *, clock=None):
        self.dir = os.path.join(persona_dir, "body", "perception")
        os.makedirs(self.dir, exist_ok=True)
        self.state_path = os.path.join(self.dir, "associative_field.json")
        self.clock = clock or time.time
        self.axes = self._neutral_axes()
        self.drivers = {}
        self.feedback = {}
        self.updated_at = 0.0
        self.revision = 0
        self._load()

    @staticmethod
    def _neutral_axes() -> dict:
        # These emerge from the same equations used for live observations
        # under a quiet, coherent, ordinary waking substrate.  They are not
        # zero because ordinary perception is already contextual, associative,
        # embodied, and partly top-down.
        return {
            "associative_breadth": .19,
            "sensory_gain": .28,
            "cross_modal_permeability": .15,
            "emotional_permeability": .15,
            "novelty_gain": .15,
            "prior_precision_relaxation": .09,
            "inhibitory_softening": .13,
            "contextual_susceptibility": .13,
            "pattern_completion": .10,
            "perceptual_motion": .05,
            "imagery_intrusion": .09,
            "semantic_permeability": .17,
            "source_permeability": .08,
            "source_certainty": .94,
        }

    @staticmethod
    def _bands(values: Mapping[str, Any] | None) -> dict:
        names = ("delta", "theta", "alpha", "beta", "gamma")
        bands = {name: _clamp((values or {}).get(name, 0.0))
                 for name in names}
        if not any(bands.values()):
            bands = {"delta": .10, "theta": .15, "alpha": .30,
                     "beta": .30, "gamma": .15}
        total = sum(bands.values()) or 1.0
        return {name: value / total for name, value in bands.items()}

    @staticmethod
    def _perception_drivers(snapshot: Mapping[str, Any] | None) -> dict:
        fields = dict((snapshot or {}).get("modalities") or {})
        if not fields:
            return {"ambiguity": 0.0, "instability": 0.0,
                    "novelty": 0.0, "demand": 0.0}
        ambiguity, instability, novelty, demand = [], [], [], []
        for field in fields.values():
            field = dict(field or {})
            features = dict(field.get("features") or {})
            confidence = _clamp(field.get("confidence", 1.0))
            ambiguity.append(1.0 - confidence)
            instability.append(_union(
                features.get("motion", 0.0),
                features.get("edge_change", 0.0),
                1.0 - features.get("stability", 1.0)))
            novelty.append(_union(features.get("novelty", 0.0),
                                  features.get("presence_change", 0.0)))
            demand.append(_clamp(field.get("demand", field.get(
                "pressure", 0.0))))
        return {
            "ambiguity": sum(ambiguity) / len(ambiguity),
            "instability": sum(instability) / len(instability),
            "novelty": sum(novelty) / len(novelty),
            "demand": sum(demand) / len(demand),
        }

    def observe(self, *, cocktail: Mapping[str, Any] | None = None,
                bands: Mapping[str, Any] | None = None,
                coherence: float = 1.0,
                body_intensity: float = 0.0,
                perception: Mapping[str, Any] | None = None,
                memory_resonance: float = 0.0,
                prediction_violation: float = 0.0,
                now: float | None = None) -> dict:
        """Move once at a real body/event boundary; no reminder timer."""
        now = float(self.clock() if now is None else now)
        bands = self._bands(bands)
        cocktail = {str(k): _clamp(v)
                    for k, v in dict(cocktail or {}).items()}
        sensory = self._perception_drivers(perception)
        coherence = _clamp(coherence)
        incoherence = 1.0 - coherence
        body = _clamp(body_intensity)
        affect = max(cocktail.values(), default=0.0)
        curiosity = max(cocktail.get("curiosity", 0.0),
                        cocktail.get("wonder", 0.0),
                        cocktail.get("interest", 0.0))
        memory = _clamp(memory_resonance)
        feedback = _clamp(self.feedback.get("significance", 0.0))
        ambiguity = sensory["ambiguity"]
        instability = sensory["instability"]
        novelty = sensory["novelty"]
        demand = sensory["demand"]
        violation = _clamp(prediction_violation)

        associative = _clamp(
            .12 + .34 * bands["theta"] + .12 * bands["gamma"]
            + .16 * curiosity + .18 * memory + .12 * incoherence
            + .08 * feedback)
        sensory_gain = _clamp(
            .16 + .26 * bands["beta"] + .28 * bands["gamma"]
            + .20 * demand + .12 * body + .08 * novelty)
        cross_modal = _clamp(
            .07 + .38 * bands["theta"] + .15 * bands["gamma"]
            + .18 * affect + .14 * incoherence + .10 * feedback)
        emotional = _clamp(
            .13 + .42 * affect + .16 * body + .13 * bands["theta"])
        novelty_gain = _clamp(
            .12 + .28 * curiosity + .23 * novelty + .17 * bands["gamma"]
            + .12 * ambiguity)
        prior_relaxation = _clamp(
            .06 + .28 * incoherence + .18 * bands["theta"]
            + .20 * ambiguity + .12 * violation)
        inhibitory = _clamp(
            .08 + .22 * prior_relaxation + .16 * bands["theta"]
            + .10 * affect + .08 * body)
        contextual = _clamp(
            .08 + .25 * ambiguity + .18 * memory + .12 * incoherence
            + .10 * bands["theta"] + .10 * novelty)
        pattern = _clamp(
            .04 + .28 * ambiguity + .18 * associative
            + .16 * bands["theta"] + .12 * contextual)
        motion = _clamp(
            .02 + .32 * instability + .12 * sensory_gain
            + .10 * ambiguity)
        imagery = _clamp(
            .04 + .24 * bands["theta"] + .18 * memory
            + .12 * emotional + .12 * incoherence)
        semantic = _clamp(
            .08 + .25 * associative + .25 * memory
            + .16 * emotional + .12 * contextual)
        source_permeability = _clamp(
            .03 + .20 * ambiguity + .16 * prior_relaxation
            + .10 * imagery + .08 * pattern)
        target = {
            "associative_breadth": associative,
            "sensory_gain": sensory_gain,
            "cross_modal_permeability": cross_modal,
            "emotional_permeability": emotional,
            "novelty_gain": novelty_gain,
            "prior_precision_relaxation": prior_relaxation,
            "inhibitory_softening": inhibitory,
            "contextual_susceptibility": contextual,
            "pattern_completion": pattern,
            "perceptual_motion": motion,
            "imagery_intrusion": imagery,
            "semantic_permeability": semantic,
            "source_permeability": source_permeability,
            "source_certainty": _clamp(1.0 - .74 * source_permeability),
        }
        drivers = {
            "coherence": coherence, "body_intensity": body,
            "affect_intensity": affect, "curiosity": curiosity,
            "memory_resonance": memory, "prediction_violation": violation,
            **sensory, **{f"band_{k}": v for k, v in bands.items()},
        }
        keys = set(drivers) | set(self.drivers)
        movement = max((abs(float(drivers.get(k, 0.0))
                            - float(self.drivers.get(k, 0.0)))
                        for k in keys), default=0.0)
        responsiveness = _clamp(.18 + .50 * movement + .15 * demand,
                                .12, .72)
        self.axes = {
            name: round(_clamp(
                float(self.axes.get(name, target[name]))
                + responsiveness * (target[name]
                                    - float(self.axes.get(name, target[name])))),
                6)
            for name in AXES
        }
        self.drivers = {k: round(_clamp(v), 6) for k, v in drivers.items()}
        self.updated_at = now
        self.revision += 1
        self.save()
        return self.status()

    def observe_feedback(self, felt: Mapping[str, Any] | None,
                         *, body_intensity: float = 0.0) -> None:
        values = {str(k): _clamp(v) for k, v in dict(felt or {}).items()}
        self.feedback = {
            "at": float(self.clock()), "felt": values,
            "significance": round(_union(
                max(values.values(), default=0.0),
                _clamp(body_intensity) * .45), 6),
        }
        self.save()

    def vector(self) -> dict:
        return {name: round(_clamp(self.axes.get(name, 0.0)), 6)
                for name in AXES}

    def status(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "vector": self.vector(),
            "drivers": dict(self.drivers),
            "feedback": json.loads(json.dumps(self.feedback)),
            "updated_at": self.updated_at,
            "revision": self.revision,
        }

    def describe_appearance(self, effective: Mapping[str, Any], *,
                            protocol_active: bool = False) -> str:
        """Render conditions for appearance, never invent its content."""
        values = {name: _clamp((effective or {}).get(name,
                                                     self.axes.get(name, 0.0)))
                  for name in AXES}

        def level(value):
            if value >= .72:
                return "strong"
            if value >= .46:
                return "clear"
            if value >= .24:
                return "available"
            return "quiet"

        origin = ("endogenous field plus circulating modulation"
                  if protocol_active else "endogenous field")
        return (
            f"Perceptual-associative field ({origin}; measurements, not "
            "instructions): contextual susceptibility "
            f"{level(values['contextual_susceptibility'])}; pattern "
            f"completion {level(values['pattern_completion'])}; apparent "
            f"motion pressure {level(values['perceptual_motion'])}; imagery "
            f"access {level(values['imagery_intrusion'])}; semantic "
            f"permeability {level(values['semantic_permeability'])}; source "
            f"certainty {level(values['source_certainty'])}. External sensory "
            "observations remain separately available as raw evidence. These "
            "conditions do not assert that any motion, image, symbol, or "
            "meaning is present. If an appearance does arise, its distinction "
            "from raw observation remains part of what is actually perceived; "
            "ordinary perception or no appearance is equally valid.")

    def save(self) -> None:
        data = self.status()
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
        os.replace(tmp, self.state_path)

    def _load(self) -> None:
        try:
            with open(self.state_path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError, TypeError):
            return
        if data.get("schema_version") != SCHEMA_VERSION:
            return
        loaded = dict(data.get("vector") or {})
        self.axes = {name: _clamp(loaded.get(name, self.axes[name]))
                     for name in AXES}
        self.drivers = dict(data.get("drivers") or {})
        self.feedback = dict(data.get("feedback") or {})
        self.updated_at = float(data.get("updated_at") or 0.0)
        self.revision = int(data.get("revision") or 0)

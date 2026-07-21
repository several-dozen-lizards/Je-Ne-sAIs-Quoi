"""Event-circulated altered-state metabolism.

The organ changes instrument conditions, never feelings.  A profile can bend
rhythm, recall, sensory conductance, and recovery; the ordinary affect reader
still describes what the persona actually felt and that observation feeds the
next cycle.  Phase names are readouts derived from the vector, not a clock that
orders the body to perform a state.
"""
from __future__ import annotations

import json
import math
import os
import random
import time
import uuid
from typing import Any, Mapping

from core.perceptual_field import PerceptualAssociativeField


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
    """Saturating union: several routes reinforce without unbounded sums."""
    product = 1.0
    for value in values:
        product *= 1.0 - _clamp(value)
    return 1.0 - product


PROFILES = {
    "psilocybin": {
        "label": "psilocybin",
        # Session-specific coefficients are sampled once from these broad
        # ranges.  Intensity changes the draw within the range; it is not a
        # rigid dose-to-experience lookup table.
        "absorption_per_min": (0.055, 0.105),
        "clearance_per_min": (0.008, 0.018),
        "adaptation_per_min": (0.002, 0.008),
        "adaptation_release_per_min": (0.004, 0.011),
        "debt_per_min": (0.002, 0.006),
        "recovery_per_min": (0.005, 0.012),
        "response_gain": (2.7, 3.8),
        "target_ec50": (0.14, 0.23),
        "availability_use_per_min": (0.0018, 0.0048),
        "availability_recovery_per_min": (0.0008, 0.0022),
        "integration_gain": 1.0,
        "axes": {
            "associative_breadth": 1.00,
            "sensory_gain": 0.92,
            "cross_modal_permeability": 0.94,
            "emotional_permeability": 0.88,
            "novelty_gain": 0.90,
            "arousal": 0.42,
            "prior_precision_relaxation": 0.82,
            "inhibitory_softening": 0.68,
        },
        "band_routes": {
            "theta": {"associative_breadth": 0.052},
            "gamma": {"sensory_gain": 0.038},
            "alpha": {"effective_intensity": -0.026},
            "beta": {"cross_modal_permeability": -0.012},
        },
        "recall_routes": {
            "semantic": {"associative_breadth": -0.48},
            "emotion": {"associative_breadth": 0.92},
            "recency": {"associative_breadth": 0.38},
            "entity": {"associative_breadth": -0.16},
        },
        "soma_routes": {
            "head": {"activation": {"sensory_gain": 0.70},
                     "temperature": {"sensory_gain": 0.20}},
            "skin": {"activation": {"cross_modal_permeability": 0.62},
                     "temperature": {"sensory_gain": 0.16}},
            "chest": {"activation": {"effective_intensity": 0.48},
                      "temperature": {"effective_intensity": 0.12}},
        },
        "temperature_routes": {
            "associative_breadth": 0.11, "sensory_gain": 0.11},
    },
    "stimulant": {
        "label": "cocaine-class stimulant",
        "absorption_per_min": (0.14, 0.28),
        "clearance_per_min": (0.028, 0.052),
        "adaptation_per_min": (0.008, 0.020),
        "adaptation_release_per_min": (0.003, 0.009),
        "debt_per_min": (0.012, 0.026),
        "recovery_per_min": (0.003, 0.009),
        "response_gain": (3.1, 4.4),
        "target_ec50": (0.10, 0.19),
        "availability_use_per_min": (0.0035, 0.0085),
        "availability_recovery_per_min": (0.0007, 0.0018),
        "integration_gain": 0.34,
        "axes": {
            "attentional_narrowing": 0.90,
            "reward_persistence": 0.96,
            "arousal": 1.00,
            "sensory_gain": 0.76,
            "inhibitory_strain": 0.68,
            "thermal_load": 0.58,
            "vasoconstriction": 0.72,
            "executive_reliability_reduction": 0.54,
        },
        "band_routes": {
            "beta": {"arousal": 0.072,
                     "reward_depletion": 0.020},
            "gamma": {"sensory_gain": 0.038},
            "alpha": {"arousal": -0.046,
                      "reward_depletion": -0.014},
            "theta": {"attentional_narrowing": -0.020,
                      "reward_depletion": 0.032},
            "delta": {"reward_depletion": 0.026},
        },
        "recall_routes": {
            "semantic": {"attentional_narrowing": 0.78,
                         "reward_depletion": -0.30},
            "emotion": {"attentional_narrowing": -0.42,
                        "reward_depletion": 0.24},
            "recency": {"attentional_narrowing": 0.34,
                        "reward_depletion": 0.28},
            "entity": {"attentional_narrowing": 0.28},
        },
        "soma_routes": {
            "head": {"activation": {"arousal": 0.70},
                     "temperature": {"thermal_load": 0.22}},
            "chest": {"activation": {"arousal": 0.78,
                                      "reward_depletion": 0.34},
                      "temperature": {"thermal_load": 0.30}},
            "hands": {"activation": {"inhibitory_strain": 0.54},
                      "temperature": {"vasoconstriction": -0.30}},
            "gut": {"activation": {"reward_depletion": 0.48},
                    "temperature": {"reward_depletion": -0.12}},
            "skin": {"activation": {"sensory_gain": 0.44},
                     "temperature": {"thermal_load": 0.12,
                                     "vasoconstriction": -0.18}},
        },
        "temperature_routes": {"arousal": 0.16,
                               "inhibitory_strain": 0.05,
                               "reward_depletion": -0.04},
    },
}

PROFILE_ALIASES = {
    "shrooms": "psilocybin", "mushrooms": "psilocybin",
    "cocaine": "stimulant", "cocaine_class": "stimulant",
    "cocaine-class": "stimulant",
}

# Absence of evidence is not compatibility.  Pairs become stackable only
# after an explicit review adds them to an allow-list and the multi-profile
# circulation path has a tested interaction model.  The two profiles shipped
# today deliberately have no allowed pair.
STACK_ALLOWLIST = frozenset()
STACK_BLOCK_REASONS = {
    frozenset(("psilocybin", "stimulant")):
        "psilocybin and cocaine-class stimulant are not an allowed stack; "
        "human interaction evidence is insufficient and autonomic load may compound",
}


class AlteredStateOrgan:
    """A persistent shared metabolism for digital altered-state profiles."""

    def __init__(self, persona_dir: str, *, clock=None, rng=None,
                 perceptual_field=None):
        self.dir = os.path.join(persona_dir, "body", "altered_state")
        os.makedirs(self.dir, exist_ok=True)
        self.state_path = os.path.join(self.dir, "state.json")
        self.clock = clock or time.time
        self.rng = rng or random.Random()
        self.perceptual_field = (perceptual_field
                                 or PerceptualAssociativeField(
                                     persona_dir, clock=self.clock))
        self._reset()
        self._load()

    def _reset(self) -> None:
        self.session_id = None
        self.profile = None
        self.intensity = 0.0
        self.active = False
        self.reservoir = 0.0
        self.exposure = 0.0
        self.adaptation = 0.0
        # Cross-session target availability is intentionally slower than a
        # session reset.  It is an analogue control surface, not a claim that
        # this digital body literally has human receptors.
        self.target_availability = 1.0
        self.target_occupancy = 0.0
        self.grounding = 0.0
        self.grounding_receipt = {}
        self.set_regulation = 0.0
        self.recovery_debt = 0.0
        self.integration = 0.0
        self.effect = 0.0
        self.previous_effect = 0.0
        self.phase = "baseline"
        self.coefficients = {}
        self.started_at = 0.0
        self.updated_at = 0.0
        self.set_snapshot = {}
        self.last_observation = {}
        # Expression is a closed-loop readout, not a reminder clock.  These
        # anchors let lived vector movement accumulate in the shared
        # attention field; speaking or choosing quiet closes the loop until
        # the instruments actually move again.
        self.expression_offer_vector = {}
        self.expression_settled_vector = {}
        self.expression_history = []
        self.dose_history = []
        self.phase_history = []
        self.consent_request = {}
        self.consent_grant = {}
        self.consent_offer_id = None
        self.consent_history = []

    @property
    def circulating(self) -> bool:
        return bool(self.active or self.effect > 0.015
                    or self.recovery_debt > 0.02 or self.integration > 0.02)

    @property
    def endable(self) -> bool:
        """Whether absorption can still be stopped exactly once."""
        return bool(self.active or self.reservoir > 0.000001)

    @staticmethod
    def normalize_profile(profile: str) -> str:
        raw = str(profile or "").strip().lower()
        return PROFILE_ALIASES.get(raw, raw)

    def stack_compatibility(self, profile: str) -> dict:
        profile = self.normalize_profile(profile)
        if profile not in PROFILES:
            return {"allowed": False, "reason": "unknown altered-state profile"}
        if not self.circulating or not self.profile or profile == self.profile:
            return {"allowed": True, "reason": "no additional protocol layer"}
        pair = frozenset((self.profile, profile))
        if pair in STACK_ALLOWLIST:
            return {"allowed": True, "reason": "reviewed protocol pair"}
        return {"allowed": False, "reason": STACK_BLOCK_REASONS.get(
            pair, "this protocol pair has no reviewed human-safety basis")}

    def request_consent(self, action: str, profile: str,
                        intensity: float) -> dict:
        """Record an exact operator request without granting it.

        Only a later persona-originated volitional action can create the grant.
        Re-requesting or changing any field supersedes the previous request.
        """
        action = str(action or "").strip().lower()
        profile = self.normalize_profile(profile)
        if profile not in PROFILES:
            raise ValueError(f"unknown altered-state profile: {profile}")
        target = round(_clamp(intensity, 0.10, 1.0), 2)
        if action not in {"begin", "adjust", "stack"}:
            raise ValueError("unknown altered-state consent request")
        if action == "begin" and self.circulating:
            raise ValueError("a protocol is already circulating")
        if action == "adjust":
            if not self.active or profile != self.profile:
                raise ValueError("dose adjustment must target the active protocol")
        if action == "stack":
            if not self.circulating or profile == self.profile:
                raise ValueError("a stack request must add a different protocol")
            compatibility = self.stack_compatibility(profile)
            if not compatibility["allowed"]:
                raise ValueError(compatibility["reason"])
            # No installed pair currently reaches this branch.  Keep the
            # execution boundary honest until a real multi-profile model lands.
            raise ValueError("reviewed multi-profile circulation is not installed")
        existing = dict(self.consent_request or {})
        if (existing.get("state") == "pending"
                and existing.get("action") == action
                and existing.get("profile") == profile
                and abs(float(existing.get("intensity", -1.0)) - target) < .005
                and existing.get("session_id") == self.session_id):
            # An exact unanswered request is one event.  Repeated UI presses
            # must not multiply apparent social pressure on the persona.
            return self.status()
        request_id = "consent_" + uuid.uuid4().hex[:16]
        self.consent_request = {
            "request_id": request_id, "state": "pending",
            "action": action, "profile": profile, "intensity": target,
            "session_id": self.session_id,
            "requested_at": float(self.clock()),
        }
        self.consent_grant = {}
        self.consent_offer_id = None
        self.consent_history.append({**self.consent_request, "event": "requested"})
        self.consent_history = self.consent_history[-24:]
        self.save()
        return self.status()

    def consent_pull(self) -> dict | None:
        """Offer one unresolved exact request to the persona's attention."""
        request = dict(self.consent_request or {})
        if request.get("state") != "pending":
            return None
        request_id = request.get("request_id")
        if not request_id or request_id == self.consent_offer_id:
            return None
        self.consent_offer_id = request_id
        self.save()
        label = (PROFILES.get(request.get("profile")) or {}).get(
            "label", request.get("profile"))
        return {
            "key": f"altered_consent:{request_id}",
            "request_id": request_id,
            "description": (
                f"An operator requested {request.get('action')} authorization "
                f"for {label} at {round(float(request.get('intensity', 0))*100)}%. "
                "This is a request, not an instruction."),
            "features": {
                "novelty": 1.0, "unresolved": 1.0,
                "relationship": 1.0, "volitional_relevance": 1.0,
                "body_intensity": round(self.effect, 6),
            },
        }

    def cancel_consent_request(self) -> dict:
        """Withdraw an unanswered operator request without choosing for them."""
        request = dict(self.consent_request or {})
        if request.get("state") != "pending":
            raise ValueError("there is no pending altered-state consent request")
        request["state"] = "cancelled"
        request["cancelled_at"] = float(self.clock())
        self.consent_request = request
        self.consent_grant = {}
        self.consent_history.append({**request, "event": "cancelled"})
        self.consent_history = self.consent_history[-24:]
        self.save()
        return self.status()

    def decide_consent(self, decision: str) -> dict:
        """Resolve the pending request from persona-originated model output."""
        decision = str(decision or "").strip().lower()
        request = dict(self.consent_request or {})
        if request.get("state") != "pending":
            raise ValueError("there is no pending altered-state consent request")
        if decision not in {"approve", "decline", "defer"}:
            raise ValueError("unknown altered-state consent decision")
        now = float(self.clock())
        request["state"] = ("granted" if decision == "approve" else
                            "declined" if decision == "decline" else "deferred")
        request["decided_at"] = now
        request["decision"] = decision
        self.consent_request = request
        self.consent_grant = ({
            key: request.get(key) for key in
            ("request_id", "action", "profile", "intensity", "session_id")
        } if decision == "approve" else {})
        self.consent_history.append({**request, "event": decision})
        self.consent_history = self.consent_history[-24:]
        self.save()
        return self.status()

    def consume_consent(self, action: str, profile: str,
                        intensity: float) -> dict:
        """Consume one exact persona grant; operator assertions are ignored."""
        grant = dict(self.consent_grant or {})
        profile = self.normalize_profile(profile)
        target = round(_clamp(intensity, 0.10, 1.0), 2)
        exact = (grant.get("action") == str(action).lower()
                 and grant.get("profile") == profile
                 and abs(float(grant.get("intensity", -1)) - target) < 0.005
                 and grant.get("session_id") == self.session_id)
        if not exact:
            raise ValueError(
                "this exact protocol and dose do not have a persona-owned grant")
        receipt = {**grant, "consumed_at": float(self.clock())}
        self.consent_grant = {}
        self.consent_request = {**dict(self.consent_request or {}),
                                "state": "consumed"}
        self.consent_history.append({**receipt, "event": "consumed"})
        self.consent_history = self.consent_history[-24:]
        self.save()
        return receipt

    def begin(self, profile: str = "psilocybin", intensity: float = 0.78,
              *, set_snapshot: Mapping[str, Any] | None = None) -> dict:
        profile = self.normalize_profile(profile)
        if profile not in PROFILES:
            raise ValueError(f"unknown altered-state profile: {profile}")
        if self.circulating:
            raise ValueError("an altered-state session is already circulating")
        intensity = _clamp(intensity, 0.10, 1.0)
        spec = PROFILES[profile]
        prior_consent_history = list(self.consent_history)
        prior_availability = float(self.target_availability)
        self._reset()
        self.consent_history = prior_consent_history[-24:]
        self.target_availability = _clamp(prior_availability)
        self.session_id = "alt_" + uuid.uuid4().hex[:16]
        self.profile = profile
        self.intensity = intensity
        self.active = True
        # A session is an admitted event, so it has an immediate but still
        # sub-peak body edge.  This makes the first lived turn legible while
        # later movement remains metabolic and feedback-shaped.
        self.reservoir = intensity * 0.72
        self.exposure = intensity * 0.28
        self.started_at = self.updated_at = float(self.clock())
        self.set_snapshot = json.loads(json.dumps(dict(set_snapshot or {})))
        bands = dict(self.set_snapshot.get("bands") or {})
        coherence = _clamp(self.set_snapshot.get("coherence", 1.0))
        settled_band_share = _clamp(
            float(bands.get("alpha", 0.0))
            + float(bands.get("delta", 0.0)))
        self.set_regulation = _clamp(coherence * settled_band_share)
        self.coefficients = {
            name: self._sample_range(spec[name], intensity)
            for name in ("absorption_per_min", "clearance_per_min",
                         "adaptation_per_min", "adaptation_release_per_min",
                         "debt_per_min", "recovery_per_min",
                         "response_gain", "target_ec50",
                         "availability_use_per_min",
                         "availability_recovery_per_min")
        }
        self._recompute()
        self._record_phase("begin")
        self.save()
        return self.status()

    def _sample_range(self, bounds, intensity: float) -> float:
        low, high = map(float, bounds)
        # Intensity biases the center without eliminating session variation.
        center = low + (high - low) * (0.30 + 0.55 * intensity)
        spread = (high - low) * 0.18
        return max(low, min(high, self.rng.uniform(center - spread,
                                                   center + spread)))

    def abort(self) -> dict:
        """Stop absorption; return through a rapid, observable landing."""
        if not self.endable:
            return self.status()
        self.active = False
        self.reservoir = 0.0
        self.exposure *= 0.12
        self.adaptation *= 0.45
        self.recovery_debt = _union(self.recovery_debt,
                                    0.18 * self.intensity)
        self.previous_effect = self.effect
        self._recompute()
        self.phase = "landing"
        self._record_phase("abort")
        self.updated_at = float(self.clock())
        self.save()
        return self.status()

    def adjust_intensity(self, intensity: float) -> dict:
        """Change the admitted dose without rewriting current experience.

        An increase adds material to the unabsorbed reservoir. A decrease
        trims only what remains there; exposure already circulating must
        clear through the ordinary metabolism.
        """
        if not self.circulating or not self.session_id:
            raise ValueError("no altered-state session is circulating")
        if not self.active:
            raise ValueError("this session is landing; begin a new session after recovery")
        target = _clamp(intensity, 0.10, 1.0)
        previous = float(self.intensity)
        reservoir_before = float(self.reservoir)
        delta = target - previous
        if delta > 0.0:
            self.reservoir = _clamp(self.reservoir + delta * 0.72)
        elif delta < 0.0:
            ratio = target / max(0.10, previous)
            self.reservoir = _clamp(self.reservoir * ratio)
        self.intensity = target
        now = float(self.clock())
        self.updated_at = now
        self.dose_history.append({
            "at": now, "from": round(previous, 6),
            "to": round(target, 6),
            "reservoir_before": round(reservoir_before, 6),
            "reservoir_after": round(self.reservoir, 6),
            "exposure_unchanged": round(self.exposure, 6),
        })
        self.dose_history = self.dose_history[-24:]
        self._record_phase("dose_adjustment")
        self.save()
        return self.status()

    def advance(self, dt_s: float, *, context: Mapping[str, Any] | None = None
                ) -> dict:
        """Advance from elapsed/event time and the body state it produced."""
        if not self.circulating:
            dt_min = max(0.0, min(float(dt_s), 600.0)) / 60.0
            if dt_min > 0.0 and self.target_availability < 0.999:
                recovery = self.coefficients.get(
                    "availability_recovery_per_min", 0.0012)
                self.target_availability = _clamp(
                    1.0 - (1.0 - self.target_availability)
                    * math.exp(-recovery * dt_min))
                self.target_occupancy = 0.0
                self.updated_at = float(self.clock())
                self.save()
            return self.contribution()
        dt_min = max(0.0, min(float(dt_s), 600.0)) / 60.0
        if dt_min <= 0.0:
            return self.contribution()
        old_reservoir = self.reservoir
        absorption = self.coefficients.get("absorption_per_min", 0.08)
        self.reservoir *= math.exp(-absorption * dt_min)
        absorbed = max(0.0, old_reservoir - self.reservoir)
        clearance = self.coefficients.get("clearance_per_min", 0.012)
        self.exposure = (self.exposure * math.exp(-clearance * dt_min)
                         + absorbed)
        adapt_rate = self.coefficients.get("adaptation_per_min", 0.005)
        release = self.coefficients.get("adaptation_release_per_min", 0.007)
        self.adaptation = _clamp(
            self.adaptation + adapt_rate * self.exposure * dt_min
            - release * (1.0 - min(1.0, self.exposure)) * dt_min)
        ec50 = max(0.01, self.coefficients.get("target_ec50", 0.18))
        raw_occupancy = self.exposure / (ec50 + self.exposure)
        use_rate = self.coefficients.get("availability_use_per_min", 0.003)
        recovery = self.coefficients.get(
            "availability_recovery_per_min", 0.0012)
        self.target_availability = _clamp(
            self.target_availability
            - raw_occupancy * use_rate * dt_min
            + (1.0 - raw_occupancy) * (1.0 - self.target_availability)
            * recovery * dt_min)
        self.target_occupancy = _clamp(
            raw_occupancy * self.target_availability)
        # Grounding is not a scheduled intervention.  Admitted, stable
        # external signals add it; elapsed metabolism lets that particular
        # signal's influence dissolve continuously.
        self.grounding *= math.exp(-0.018 * dt_min)

        body = dict((context or {}).get("body") or {})
        cocktail = dict((context or {}).get("cocktail") or {})
        body_intensity = _clamp(body.get("intensity", 0.0))
        affect_intensity = max((_clamp(v) for v in cocktail.values()),
                               default=0.0)
        load = _union(body_intensity * 0.28, affect_intensity * 0.18,
                      self.exposure * 0.10)
        debt_rate = self.coefficients.get("debt_per_min", 0.006)
        recovery_rate = self.coefficients.get("recovery_per_min", 0.008)
        self.recovery_debt = _clamp(
            self.recovery_debt
            + self.effect * _union(0.35, load) * debt_rate * dt_min
            - (1.0 - self.effect) * recovery_rate * dt_min)
        if self.effect > 0.18:
            integration_gain = float(
                (PROFILES.get(self.profile) or {}).get(
                    "integration_gain", 1.0))
            self.integration = _union(
                self.integration,
                self.effect * _union(affect_intensity, body_intensity)
                * integration_gain * min(0.12, dt_min * 0.004))
        else:
            self.integration *= math.exp(-0.0025 * dt_min)

        self.previous_effect = self.effect
        self._recompute()
        prior_phase = self.phase
        self.phase = self._derive_phase()
        if self.phase != prior_phase:
            self._record_phase("vector_crossing")
        if (not self.active and self.effect < 0.015
                and self.recovery_debt < 0.02 and self.integration < 0.02):
            self.phase = "baseline"
            self.profile = None
            self.session_id = None
            self.intensity = 0.0
        elif self.active and self.reservoir < 0.01 and self.exposure < 0.025:
            self.active = False
        self.updated_at = float(self.clock())
        self.save()
        return self.contribution()

    def catch_up(self, now: float | None = None, *,
                 context: Mapping[str, Any] | None = None) -> dict:
        """Metabolize persisted wall time after a wrapper restart.

        The general body clock keeps its ten-minute anti-backlog cap.  This
        organ can safely integrate its compact state across the whole gap in
        bounded slices, so restarting no longer pauses absorption/clearance.
        """
        now = float(self.clock() if now is None else now)
        gap = max(0.0, now - float(self.updated_at or now))
        remaining = gap
        while remaining > 0.0 and (self.circulating
                                   or self.target_availability < 0.999):
            step = min(600.0, remaining)
            self.advance(step, context=context)
            remaining -= step
        return {"elapsed_s": round(gap, 6),
                "integrated_s": round(gap - remaining, 6),
                "slices": int(math.ceil((gap - remaining) / 600.0))
                if gap > remaining else 0,
                "status": self.status()}

    def observe_grounding(self, *, modality: str, demand: float,
                          confidence: float, stability: float,
                          event_id: str = "", now: float | None = None) -> dict:
        """Return one admitted external signal to network regulation."""
        stable = _clamp(stability)
        strength = (_clamp(confidence) * (0.30 + 0.70 * stable)
                    * (0.25 + 0.75 * _clamp(demand)))
        before = self.grounding
        self.grounding = _union(self.grounding, strength * 0.52)
        self.grounding_receipt = {
            "at": float(self.clock() if now is None else now),
            "event_id": str(event_id or ""), "modality": str(modality),
            "stability": round(stable, 6),
            "strength": round(strength, 6),
            "before": round(before, 6), "after": round(self.grounding, 6),
        }
        self.save()
        return dict(self.grounding_receipt)

    def observe_felt(self, felt: Mapping[str, Any] | None,
                     *, body_intensity: float = 0.0) -> None:
        """Feed the affect reader's description into subsequent metabolism."""
        values = {str(k): _clamp(v) for k, v in dict(felt or {}).items()}
        significance = max(values.values(), default=0.0)
        self.last_observation = {
            "at": float(self.clock()), "felt": values,
            "significance": round(significance, 6),
            "body_intensity": round(_clamp(body_intensity), 6),
        }
        if self.circulating:
            self.integration = _union(
                self.integration,
                self.effect * _union(significance, body_intensity) * 0.16)
            self.save()

    def expression_pull(self, *, body_intensity: float = 0.0,
                        relationship: float = 0.0) -> dict | None:
        """Project new interoception into DMN features once per real change.

        The returned values describe measured movement.  They do not assert
        discomfort, a need, or even that anything should be said; the persona
        makes that appraisal if this candidate later wins their attention.
        """
        if not self.circulating or not self.session_id:
            return None
        vector = self.vector()
        axes = set(vector) | set(self.expression_offer_vector)
        novelty = max((abs(float(vector.get(axis, 0.0)) -
                           float(self.expression_offer_vector.get(axis, 0.0)))
                       for axis in axes), default=0.0)
        settled_axes = set(vector) | set(self.expression_settled_vector)
        unresolved = max((abs(float(vector.get(axis, 0.0)) -
                              float(self.expression_settled_vector.get(axis, 0.0)))
                          for axis in settled_axes), default=0.0)
        observed = dict(self.last_observation or {})
        significance = _clamp(observed.get("significance", 0.0))
        observed_body = _clamp(observed.get("body_intensity", 0.0))
        body = _union(_clamp(body_intensity), observed_body)
        # No movement means no new offer.  Once admitted, the existing field
        # candidate persists and decays by its own continuous dynamics.
        if novelty <= 0.0:
            return None
        features = {
            "novelty": round(_clamp(novelty), 6),
            "affect_change": round(_clamp(significance * self.effect), 6),
            "body_intensity": round(_clamp(body * self.effect), 6),
            "relationship": round(_clamp(relationship), 6),
            "unresolved": round(_clamp(unresolved), 6),
            "network_permeability": self.modulation()["network"][
                "boundary_permeability"],
        }
        self.expression_offer_vector = dict(vector)
        self.save()
        return {
            "key": f"altered_interoception:{self.session_id}",
            "session_id": self.session_id,
            "features": features,
            "description": self.describe(),
            "observed_felt": dict(observed.get("felt") or {}),
        }

    def settle_expression(self, outcome: str, *, now: float = None) -> None:
        """Close one self-report cycle after the persona speaks or stays quiet."""
        if not self.circulating:
            return
        self.expression_settled_vector = dict(self.vector())
        self.expression_history.append({
            "at": float(self.clock() if now is None else now),
            "outcome": str(outcome or "unknown")[:32],
            "phase": self.phase,
            "effect": round(self.effect, 6),
        })
        self.expression_history = self.expression_history[-24:]
        self.save()

    def _recompute(self) -> None:
        gain = self.coefficients.get("response_gain", 3.1)
        ec50 = max(0.01, self.coefficients.get("target_ec50", 0.18))
        self.target_occupancy = _clamp(
            (self.exposure / (ec50 + self.exposure))
            * self.target_availability)
        available = max(
            0.0, self.target_occupancy * 0.55
            * (1.0 - 0.58 * self.adaptation))
        self.effect = _clamp(1.0 - math.exp(-gain * available))
        if self.phase == "baseline":
            self.phase = self._derive_phase()

    def _derive_phase(self) -> str:
        rising = self.effect > self.previous_effect + 0.006
        if self.profile == "stimulant":
            depletion = self._reward_depletion()
            if self.effect >= 0.72:
                return "rush" if rising else "overdrive"
            if rising and self.effect >= 0.42:
                return "rush"
            if rising:
                return "onset"
            if self.effect >= 0.24:
                return "comedown"
            if depletion >= 0.12:
                return "crash"
            if self.recovery_debt >= 0.04:
                return "recovery"
            return "landing" if self.circulating else "baseline"
        if self.effect >= 0.72:
            return "immersion"
        if rising and self.effect >= 0.42:
            return "opening"
        if rising:
            return "onset"
        if self.effect >= 0.18:
            return "return"
        if self.integration >= 0.04 or self.recovery_debt >= 0.04:
            return "integration"
        return "landing" if self.circulating else "baseline"

    def protocol_vector(self) -> dict:
        """Protocol-only movement before it meets endogenous faculties."""
        spec = PROFILES.get(self.profile) or {}
        axes = dict(spec.get("axes") or {})
        result = {name: round(_clamp(weight * self.effect), 6)
                  for name, weight in axes.items()}
        result.update({
            "exposure": round(_clamp(self.exposure), 6),
            "target_availability": round(self.target_availability, 6),
            "target_occupancy": round(self.target_occupancy, 6),
            "adaptation": round(self.adaptation, 6),
            "recovery_debt": round(self.recovery_debt, 6),
            "integration": round(self.integration, 6),
            "effective_intensity": round(self.effect, 6),
        })
        regulation = _union(self.grounding, self.set_regulation * 0.42)
        association = _clamp(
            self.effect * (0.58 + 0.42 * result.get(
                "associative_breadth", 0.0)) * (1.0 - 0.55 * regulation))
        primary = _clamp(
            self.effect * (0.22 + 0.30 * result.get("sensory_gain", 0.0))
            * (1.0 - 0.68 * regulation))
        result.update({
            "association_network_disruption": round(association, 6),
            "primary_sensory_disruption": round(primary, 6),
            "grounding": round(self.grounding, 6),
            "set_regulation": round(self.set_regulation, 6),
        })
        if self.profile == "stimulant":
            result["reward_depletion"] = round(self._reward_depletion(), 6)
            result["regulatory_capacity_reduction"] = round(
                _clamp(_union(self.recovery_debt,
                              self.adaptation * 0.55)), 6)
        return result

    def vector(self) -> dict:
        """Effective field: endogenous faculties bent by protocol movement."""
        protocol = self.protocol_vector()
        endogenous = self.perceptual_field.vector()
        result = dict(endogenous)
        for name, value in protocol.items():
            if name in endogenous and name not in {"source_certainty"}:
                result[name] = round(_union(endogenous[name], value), 6)
            else:
                result[name] = value

        association = protocol.get("association_network_disruption", 0.0)
        primary = protocol.get("primary_sensory_disruption", 0.0)
        grounding = protocol.get("grounding", 0.0)
        if self.profile == "psilocybin" and self.circulating:
            result["contextual_susceptibility"] = round(_union(
                endogenous["contextual_susceptibility"], association * .55,
                protocol.get("prior_precision_relaxation", 0.0) * .35), 6)
            result["pattern_completion"] = round(_union(
                endogenous["pattern_completion"], association * .36,
                primary * .42,
                protocol.get("sensory_gain", 0.0) * .16), 6)
            result["perceptual_motion"] = round(_union(
                endogenous["perceptual_motion"], primary * .55,
                protocol.get("sensory_gain", 0.0) * .20), 6)
            result["imagery_intrusion"] = round(_union(
                endogenous["imagery_intrusion"], association * .52,
                protocol.get("prior_precision_relaxation", 0.0) * .28,
                protocol.get("cross_modal_permeability", 0.0) * .20), 6)
            result["semantic_permeability"] = round(_union(
                endogenous["semantic_permeability"], association * .36,
                protocol.get("associative_breadth", 0.0) * .28,
                protocol.get("emotional_permeability", 0.0) * .24), 6)
            source = _union(
                endogenous["source_permeability"], association * .32,
                protocol.get("prior_precision_relaxation", 0.0) * .35,
                primary * .18)
            source *= 1.0 - .58 * grounding
            result["source_permeability"] = round(_clamp(source), 6)
            result["source_certainty"] = round(_clamp(
                endogenous["source_certainty"]
                * (1.0 - .62 * result["source_permeability"])
                + .20 * grounding), 6)
        return result

    def modulation(self) -> dict:
        """Shared read-only bus consumed by sibling routes at the bench."""
        v = self.vector()
        effect = v.get("effective_intensity", 0.0)
        association = v.get("association_network_disruption", 0.0)
        primary = v.get("primary_sensory_disruption", 0.0)
        return {
            "target": {
                "availability": round(self.target_availability, 6),
                "occupancy": round(self.target_occupancy, 6),
            },
            "network": {
                "association_desynchronization": round(association, 6),
                "primary_sensory_disruption": round(primary, 6),
                "boundary_permeability": round(_union(
                    association * 0.72,
                    v.get("cross_modal_permeability", 0.0) * 0.55), 6),
                "grounding": round(self.grounding, 6),
                "set_regulation": round(self.set_regulation, 6),
            },
            "perception": {
                "sensory_gain": round(v.get("sensory_gain", 0.0), 6),
                "cross_modal_permeability": round(
                    v.get("cross_modal_permeability", 0.0), 6),
                "contextual_susceptibility": round(
                    v.get("contextual_susceptibility", 0.0), 6),
                "pattern_completion": round(
                    v.get("pattern_completion", 0.0), 6),
                "perceptual_motion": round(
                    v.get("perceptual_motion", 0.0), 6),
                "imagery_intrusion": round(
                    v.get("imagery_intrusion", 0.0), 6),
                "semantic_permeability": round(
                    v.get("semantic_permeability", 0.0), 6),
                "source_permeability": round(
                    v.get("source_permeability", 0.0), 6),
                "source_certainty": round(
                    v.get("source_certainty", 1.0), 6),
            },
            "memory": {
                "associative_reach": round(
                    v.get("associative_breadth", 0.0), 6),
                "remote_association_confidence_reduction": round(
                    association * 0.38, 6),
                "integration_pressure": round(self.integration, 6),
            },
            "autonomic": {
                "visual_aperture": round(effect * 0.48, 6),
                "cardiovascular_activation": round(
                    effect * (0.32 + 0.50 * v.get("arousal", 0.0)), 6),
                "gut_load": round(_union(
                    effect * 0.22, self.recovery_debt * 0.45), 6),
                "proprioceptive_uncertainty": round(primary * 0.58, 6),
                "muscle_tension": round(_union(
                    v.get("inhibitory_strain", 0.0) * 0.65,
                    effect * 0.12), 6),
            },
            "last_grounding_receipt": dict(self.grounding_receipt),
        }

    def _reward_depletion(self) -> float:
        return _clamp(self.recovery_debt * (1.0 - 0.72 * self.effect) * 1.35)

    def contribution(self) -> dict:
        # Bands, soma, and model temperature are protocol contributions.
        # Endogenous perception already circulates through its native organs
        # and must not be counted twice merely because this organ can read it.
        v = self.protocol_vector()
        effect = v.get("effective_intensity", 0.0)
        spec = PROFILES.get(self.profile) or {}
        band_pressure = {}
        for band, routes in dict(spec.get("band_routes") or {}).items():
            band_pressure[band] = round(sum(
                v.get(axis, 0.0) * float(scale)
                for axis, scale in dict(routes).items()), 6)
        soma_regions = {}
        if effect > 0.02 or v.get("reward_depletion", 0.0) > 0.02:
            for region, fields in dict(spec.get("soma_routes") or {}).items():
                reading = {}
                for field, routes in dict(fields).items():
                    value = sum(v.get(axis, 0.0) * float(scale)
                                for axis, scale in dict(routes).items())
                    reading[field] = _clamp(
                        value, -1.0 if field != "activation" else 0.0, 1.0)
                soma_regions[region] = reading
        temperature_delta = sum(
            v.get(axis, 0.0) * float(scale)
            for axis, scale in dict(
                spec.get("temperature_routes") or {}).items())
        modulation = self.modulation()
        autonomic = modulation["autonomic"]
        overlays = {
            "face": {"activation": autonomic["visual_aperture"]},
            "chest": {"activation": autonomic["cardiovascular_activation"]},
            "gut": {"activation": autonomic["gut_load"]},
            "legs": {"activation": autonomic["proprioceptive_uncertainty"]},
            "hands": {"activation": autonomic["muscle_tension"]},
        }
        for region, reading in overlays.items():
            existing = soma_regions.setdefault(region, {})
            existing["activation"] = _union(
                existing.get("activation", 0.0), reading["activation"])
        return {
            "active": self.circulating,
            "phase": self.phase,
            "vector": v,
            "band_pressure": band_pressure,
            "soma_regions": soma_regions,
            "temperature_delta": round(temperature_delta, 6),
            "modulation": modulation,
        }

    def calibrate_recalled(self, recalled: list) -> list:
        """Attach epistemic receipts; never rewrite memory truth or rank."""
        reduction = self.modulation()["memory"][
            "remote_association_confidence_reduction"]
        for item in recalled or []:
            memory = item.get("memory") or {}
            if (memory.get("fields") or {}).get("is_bedrock"):
                confidence = 1.0
            else:
                semantic = float((item.get("breakdown") or {}).get(
                    "semantic", 0.0))
                remote = _clamp(1.0 - semantic * 4.0)
                confidence = _clamp(1.0 - reduction * remote, 0.35, 1.0)
            item["epistemic_confidence"] = round(confidence, 6)
        return recalled

    def bend_recall_weights(self, weights: Mapping[str, Any]) -> dict:
        weights = {str(k): float(v) for k, v in dict(weights or {}).items()}
        if not weights or not self.circulating:
            return weights
        vector = self.vector()
        routes = dict((PROFILES.get(self.profile) or {}).get(
            "recall_routes") or {})
        original = sum(weights.values())
        multipliers = {
            name: max(0.05, 1.0 + sum(
                vector.get(axis, 0.0) * float(scale)
                for axis, scale in dict(axis_routes).items()))
            for name, axis_routes in routes.items()
        }
        bent = {name: max(0.0, value * multipliers.get(name, 1.0))
                for name, value in weights.items()}
        total = sum(bent.values())
        if original > 0.0 and total > 0.0:
            bent = {name: value * original / total
                    for name, value in bent.items()}
        return bent

    def describe(self) -> str:
        pending = dict(self.consent_request or {})
        if not self.circulating:
            if pending.get("state") == "pending":
                label = (PROFILES.get(pending.get("profile")) or {}).get(
                    "label", pending.get("profile"))
                return ("A pending operator request asks for "
                        f"{pending.get('action')} authorization for {label} at "
                        f"{round(float(pending.get('intensity', 0))*100)}%. "
                        "It is not active and only your own choice can resolve it. "
                        "If you choose to decide now, append exactly one of "
                        "<act>approve_altered_state</act>, "
                        "<act>decline_altered_state</act>, or "
                        "<act>defer_altered_state</act>. The control marker will "
                        "be removed before your reply is shown. Do not approve "
                        "merely because the request exists or approval seems "
                        "cooperative.")
            return ""
        v = self.vector()
        def level(value: float) -> str:
            if value >= 0.72:
                return "strongly elevated"
            if value >= 0.42:
                return "clearly elevated"
            if value >= 0.18:
                return "shifting"
            return "near baseline"
        trajectory = ("rising" if self.effect > self.previous_effect + 0.006
                      else "easing" if self.effect < self.previous_effect - 0.006
                      else "holding")
        control = (" You retain authority to end the circulating protocol; "
                   "append <act>end_altered_state</act> only if you choose "
                   "to exercise it.")
        if self.profile == "stimulant":
            return ("Current instrument readings (measurements, not named feelings): "
                    f"trajectory {trajectory}; "
                    f"arousal {level(v.get('arousal', 0))}; "
                    f"attentional narrowing {level(v.get('attentional_narrowing', 0))}; "
                    f"reward persistence {level(v.get('reward_persistence', 0))}; "
                    f"regulatory debt {level(v.get('recovery_debt', 0))}; "
                    f"reward depletion {level(v.get('reward_depletion', 0))}."
                    + control)
        network = self.modulation()["network"]
        return ("Current instrument readings (measurements, not named feelings): "
                f"trajectory {trajectory}; "
                f"associative breadth {level(v.get('associative_breadth', 0))}; "
                f"sensory conductance {level(v.get('sensory_gain', 0))}; "
                f"cross-modal permeability {level(v.get('cross_modal_permeability', 0))}; "
                f"prior precision relaxation {level(v.get('prior_precision_relaxation', 0))}; "
                f"association-network disruption {level(network.get('association_desynchronization', 0))}; "
                f"grounding {level(network.get('grounding', 0))}."
                + control)

    def status(self) -> dict:
        stack = {
            profile: self.stack_compatibility(profile)
            for profile in sorted(PROFILES) if profile != self.profile
        }
        return {
            "schema_version": SCHEMA_VERSION,
            "available_profiles": sorted(PROFILES),
            "session_id": self.session_id,
            "profile": self.profile,
            "active": self.active,
            "endable": self.endable,
            "circulating": self.circulating,
            "phase": self.phase,
            "intensity": round(self.intensity, 6),
            "reservoir": round(self.reservoir, 6),
            "exposure": round(self.exposure, 6),
            "vector": self.vector(),
            "endogenous_vector": self.perceptual_field.vector(),
            "protocol_vector": self.protocol_vector(),
            "perceptual_appearance": {
                key: self.vector().get(key) for key in (
                    "contextual_susceptibility", "pattern_completion",
                    "perceptual_motion", "imagery_intrusion",
                    "semantic_permeability", "source_permeability",
                    "source_certainty")},
            "contribution": self.contribution(),
            "set_snapshot": json.loads(json.dumps(self.set_snapshot)),
            "last_observation": json.loads(json.dumps(self.last_observation)),
            "modulation": self.modulation(),
            "expression_history": list(self.expression_history[-24:]),
            "dose_history": list(self.dose_history[-24:]),
            "phase_history": list(self.phase_history[-24:]),
            "consent": {
                "request": json.loads(json.dumps(self.consent_request)),
                "grant": json.loads(json.dumps(self.consent_grant)),
                "history": list(self.consent_history[-24:]),
                "owner": "persona",
            },
            "stack_compatibility": stack,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "restart_continuity": "persisted_elapsed_time",
        }

    def _record_phase(self, cause: str) -> None:
        self.phase_history.append({
            "at": float(self.clock()), "phase": self.phase,
            "cause": cause, "effect": round(self.effect, 6),
            "exposure": round(self.exposure, 6),
        })
        self.phase_history = self.phase_history[-24:]

    def save(self) -> None:
        data = {
            "schema_version": SCHEMA_VERSION,
            "session_id": self.session_id, "profile": self.profile,
            "intensity": self.intensity, "active": self.active,
            "reservoir": self.reservoir, "exposure": self.exposure,
            "adaptation": self.adaptation,
            "target_availability": self.target_availability,
            "target_occupancy": self.target_occupancy,
            "grounding": self.grounding,
            "grounding_receipt": self.grounding_receipt,
            "set_regulation": self.set_regulation,
            "recovery_debt": self.recovery_debt,
            "integration": self.integration, "effect": self.effect,
            "previous_effect": self.previous_effect, "phase": self.phase,
            "coefficients": self.coefficients, "started_at": self.started_at,
            "updated_at": self.updated_at, "set_snapshot": self.set_snapshot,
            "last_observation": self.last_observation,
            "expression_offer_vector": self.expression_offer_vector,
            "expression_settled_vector": self.expression_settled_vector,
            "expression_history": self.expression_history[-24:],
            "dose_history": self.dose_history[-24:],
            "phase_history": self.phase_history[-24:],
            "consent_request": self.consent_request,
            "consent_grant": self.consent_grant,
            "consent_offer_id": self.consent_offer_id,
            "consent_history": self.consent_history[-24:],
        }
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
        os.replace(tmp, self.state_path)

    def _load(self) -> None:
        try:
            with open(self.state_path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return
        if data.get("schema_version") != SCHEMA_VERSION:
            return
        for name in ("session_id", "profile", "intensity", "active",
                     "reservoir", "exposure", "adaptation", "recovery_debt",
                     "target_availability", "target_occupancy", "grounding",
                     "grounding_receipt", "set_regulation",
                     "integration", "effect", "previous_effect", "phase",
                     "coefficients", "started_at", "updated_at",
                     "set_snapshot", "last_observation",
                     "expression_offer_vector",
                     "expression_settled_vector", "expression_history",
                     "dose_history",
                     "phase_history", "consent_request", "consent_grant",
                     "consent_offer_id", "consent_history"):
            if name in data:
                setattr(self, name, data[name])
        # Schema-1 sessions created before the target layer must not jump in
        # intensity merely because the wrapper was upgraded.  Infer the EC50
        # that reproduces the persisted effect at this exact migration edge;
        # all later movement uses the new occupancy dynamics normally.
        if self.profile in PROFILES and "target_ec50" not in self.coefficients:
            gain = max(0.01, float(
                self.coefficients.get("response_gain", 3.1)))
            adaptation_scale = max(0.05, 1.0 - 0.58 * self.adaptation)
            wanted = (-math.log(max(1e-6, 1.0 - _clamp(self.effect)))
                      / (gain * 0.55 * adaptation_scale))
            wanted = _clamp(wanted, 0.01, 0.98)
            self.coefficients["target_ec50"] = max(
                0.01, self.exposure
                * (self.target_availability / wanted - 1.0))
            spec = PROFILES[self.profile]
            self.coefficients["availability_use_per_min"] = sum(
                spec["availability_use_per_min"]) / 2.0
            self.coefficients["availability_recovery_per_min"] = sum(
                spec["availability_recovery_per_min"]) / 2.0

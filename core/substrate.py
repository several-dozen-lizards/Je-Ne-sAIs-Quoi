"""Cheap, non-semantic room-to-body transport.

This module owns no device, model, DMN field, or body clock. Browser drivers
summarize one body-resolution interval; this accumulator duration-weights
transport jitter and releases at most one profile when TurnEngine's existing
30-second body step asks for it.

The five acoustic ranges are authored transduction priors inherited from v1.
They are not acoustic or neuroscientific resonance claims. Likewise, camera
effects arrive here only after the existing SensoryOrgan numeric prior has
mapped them. Neither path claims a feeling.
"""
import math
import threading

from core.oscillator.organ import BASELINE_PULL, BANDS


BODY_STEP_S = 30.0
MAX_BACKLOG_S = 600.0  # same elapsed-time cap as TurnEngine.settle()

# The one new behavioral scale in S3. Bound to homeostasis, never copied as a
# free literal: at full departure room evidence and baseline pull have parity.
SUBSTRATE_COUPLING_GAIN = BASELINE_PULL


def _finite_nonnegative(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    return value if math.isfinite(value) and value > 0.0 else 0.0


def _unit(value):
    return min(1.0, _finite_nonnegative(value))


def audio_band_pressure(audio: dict) -> tuple[dict, dict]:
    """Turn statistical spectral departure into one normalized pressure.

    Band names are an authored analogy. The math only uses shares and
    departures; it never sees speech, music, alarm, mood, or meaning.
    """
    shares = {band: _unit((audio.get("band_share") or {}).get(band))
              for band in BANDS}
    departures = {
        band: _unit((audio.get("band_departure") or {}).get(band))
        for band in BANDS}
    total_share = sum(shares.values())
    if total_share:
        shares = {band: value / total_share
                  for band, value in shares.items()}
    weighted = {band: shares[band] * departures[band] for band in BANDS}
    evidence = sum(weighted.values())
    if evidence <= 0.0:
        pressure = {}
    else:
        pressure = {
            band: SUBSTRATE_COUPLING_GAIN * evidence
            * weighted[band] / evidence
            for band in BANDS if weighted[band] > 0.0}
    receipt = {
        "band_share": shares,
        "band_departure": departures,
        "weighted": weighted,
        "departure_strength": evidence,
        "direct_interval_pressure": dict(pressure),
        "direct_interval_pressure_total": sum(pressure.values()),
        "coupling_gain": SUBSTRATE_COUPLING_GAIN,
        "authored_prior": "acoustic ranges to oscillator band names",
    }
    return pressure, receipt


class SubstrateAccumulator:
    """Thread-safe duration-weighted transport buffer, not a second clock."""

    def __init__(self):
        self._lock = threading.Lock()
        self._pending = {}

    def offer(self, modality: str, duration_s, band_pressure: dict,
              signals: dict = None, receipt: dict = None, active=True):
        if modality not in ("audio", "camera"):
            raise ValueError(f"unknown substrate modality: {modality}")
        with self._lock:
            if not active:
                self._pending.pop(modality, None)
                return {"modality": modality, "active": False,
                        "queued_duration_s": 0.0}
            duration = min(MAX_BACKLOG_S, _finite_nonnegative(duration_s))
            if duration <= 0.0:
                return {"modality": modality, "active": True,
                        "queued_duration_s": self._pending.get(
                            modality, {}).get("duration_s", 0.0)}
            current = self._pending.setdefault(modality, {
                "duration_s": 0.0, "weighted_band_pressure": {},
                "weighted_signals": {}, "interval_count": 0,
                "latest_receipt": {}})
            room = max(0.0, MAX_BACKLOG_S - current["duration_s"])
            accepted = min(duration, room)
            for band, amount in (band_pressure or {}).items():
                if band not in BANDS:
                    continue
                amount = _finite_nonnegative(amount)
                current["weighted_band_pressure"][band] = (
                    current["weighted_band_pressure"].get(band, 0.0)
                    + amount * accepted)
            for name, value in (signals or {}).items():
                value = _unit(value)
                current["weighted_signals"][str(name)] = (
                    current["weighted_signals"].get(str(name), 0.0)
                    + value * accepted)
            current["duration_s"] += accepted
            current["interval_count"] += 1
            current["latest_receipt"] = dict(receipt or {})
            return {"modality": modality, "active": True,
                    "queued_duration_s": current["duration_s"],
                    "interval_count": current["interval_count"]}

    def drain_step(self, step_s=BODY_STEP_S):
        step_s = _finite_nonnegative(step_s) or BODY_STEP_S
        with self._lock:
            band_pressure, signals, modalities = {}, {}, {}
            for modality in list(self._pending):
                pending = self._pending[modality]
                duration = pending["duration_s"]
                if duration <= 0.0:
                    del self._pending[modality]
                    continue
                consumed = min(step_s, duration)
                fraction = consumed / step_s
                avg_bands = {
                    band: total / duration
                    for band, total in pending["weighted_band_pressure"].items()}
                avg_signals = {
                    name: total / duration
                    for name, total in pending["weighted_signals"].items()}
                for band, amount in avg_bands.items():
                    band_pressure[band] = (band_pressure.get(band, 0.0)
                                           + amount * fraction)
                for name, value in avg_signals.items():
                    signals[name] = max(signals.get(name, 0.0),
                                        value * fraction)
                modalities[modality] = {
                    "duration_s": consumed,
                    "queued_duration_s_before": duration,
                    "interval_count": pending["interval_count"],
                    "band_pressure": {band: amount * fraction
                                      for band, amount in avg_bands.items()},
                    "receipt": pending["latest_receipt"],
                }
                remaining = duration - consumed
                if remaining <= 1e-9:
                    del self._pending[modality]
                else:
                    ratio = remaining / duration
                    pending["duration_s"] = remaining
                    pending["weighted_band_pressure"] = {
                        key: value * ratio for key, value in
                        pending["weighted_band_pressure"].items()}
                    pending["weighted_signals"] = {
                        key: value * ratio for key, value in
                        pending["weighted_signals"].items()}
            if not modalities:
                return None
            return {"modalities": modalities,
                    "band_pressure": band_pressure, "signals": signals,
                    "step_s": step_s,
                    "coupling_gain": SUBSTRATE_COUPLING_GAIN}

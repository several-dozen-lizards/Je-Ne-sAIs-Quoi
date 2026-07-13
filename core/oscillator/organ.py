"""Oscillator organ — the substrate's heartbeat.
Five bands as a normalized distribution; pressures push it around; it decays
toward a baseline profile; dwell caps nudge it loose when stuck. Outputs:
describe() (substrate -> language, descriptive not prescriptive) and
temperature() (band + coherence modulate expressiveness).
INDEPENDENT: no imports from any other organ. The bench composes organs;
organs never compose each other. (REQUIREMENTS par 2.6 — any subset runs.)
State persists in <persona>/body/oscillator/."""
import json
import os
import time

BANDS = ("delta", "theta", "alpha", "beta", "gamma")
SCHEMA_VERSION = "1"

DEFAULT_BASELINE = {"delta": 0.10, "theta": 0.15, "alpha": 0.30,
                    "beta": 0.30, "gamma": 0.15}
BASELINE_PULL = 0.06       # fraction of distance to baseline per tick
DWELL_CAP_S = 1800         # stuck in one band this long -> nudging begins
DWELL_NUDGE = 0.05         # pressure applied away from an overstayed band

# emotion -> band pressure map (config data, per-persona overridable)
DEFAULT_EMOTION_MAP = {
    "fear": ("beta", 0.20), "alertness": ("beta", 0.15),
    "adrenaline": ("gamma", 0.15), "surprise": ("gamma", 0.12),
    "joy": ("alpha", 0.15), "warmth": ("alpha", 0.12),
    "comfort": ("alpha", 0.15), "calm": ("alpha", 0.18),
    "curiosity": ("beta", 0.12), "sadness": ("theta", 0.15),
    "loneliness": ("theta", 0.12), "melancholy": ("theta", 0.12),
    "exhaustion": ("delta", 0.18), "contentment": ("alpha", 0.15),
}


def _normalize(bands: dict) -> dict:
    total = sum(max(0.001, v) for v in bands.values())
    return {k: round(max(0.001, v) / total, 4) for k, v in bands.items()}


class OscillatorOrgan:
    def __init__(self, persona_dir: str, baseline: dict = None):
        self.dir = os.path.join(persona_dir, "body", "oscillator")
        os.makedirs(self.dir, exist_ok=True)
        sv = os.path.join(self.dir, "schema_version.txt")
        if not os.path.exists(sv):
            with open(sv, "w") as f:
                f.write(SCHEMA_VERSION)
        self.state_path = os.path.join(self.dir, "state.json")
        self.baseline = dict(baseline or DEFAULT_BASELINE)
        self.emotion_map = dict(DEFAULT_EMOTION_MAP)
        st = self._load()
        self.bands = st.get("bands", dict(self.baseline))
        self.dominant_since = st.get("dominant_since", time.time())
        self._last_dominant = st.get("dominant", self.dominant())
        self._coherence_window = st.get("coherence_window", [])
        self._pending = {}

    def _load(self) -> dict:
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def save(self):
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump({"bands": self.bands, "dominant": self.dominant(),
                       "dominant_since": self.dominant_since,
                       "coherence_window": self._coherence_window[-20:],
                       "updated": time.strftime("%Y-%m-%dT%H:%M:%S")}, f, indent=1)

    # ── inputs ────────────────────────────────────────────────────
    def pressure(self, band: str, amount: float):
        """Queue a push toward a band (applied on next tick)."""
        if band in BANDS:
            self._pending[band] = self._pending.get(band, 0.0) + amount

    def emotion_pressure(self, felt: dict):
        """Map felt emotions to band pressures (config-driven)."""
        for name, intensity in (felt or {}).items():
            m = self.emotion_map.get(name.lower())
            if m:
                self.pressure(m[0], m[1] * float(intensity))

    # ── the heartbeat ─────────────────────────────────────────────
    def tick(self, dt_s: float = 1.0):
        before = dict(self.bands)
        # baseline pull (homeostasis)
        for k in BANDS:
            self.bands[k] += (self.baseline[k] - self.bands[k]) * BASELINE_PULL
        # pending pressures
        for k, v in self._pending.items():
            self.bands[k] = self.bands.get(k, 0.0) + v
        self._pending = {}
        # dwell cap: overstayed dominance gets nudged toward baseline-likely bands
        dom = self.dominant()
        if dom == self._last_dominant:
            dwell = time.time() - self.dominant_since
            if dwell > DWELL_CAP_S:
                self.bands[dom] -= DWELL_NUDGE
                self.bands["alpha"] += DWELL_NUDGE * 0.6
                self.bands["theta"] += DWELL_NUDGE * 0.4
        else:
            self._last_dominant = dom
            self.dominant_since = time.time()
        self.bands = _normalize(self.bands)
        # coherence: stability of the distribution across recent ticks
        shift = sum(abs(self.bands[k] - before.get(k, 0)) for k in BANDS)
        self._coherence_window.append(shift)
        self._coherence_window = self._coherence_window[-20:]
        return dict(self.bands)

    # ── readouts ──────────────────────────────────────────────────
    def dominant(self) -> str:
        return max(self.bands, key=self.bands.get)

    def coherence(self) -> float:
        """1.0 = perfectly stable distribution; 0.0 = thrashing."""
        if not self._coherence_window:
            return 1.0
        avg_shift = sum(self._coherence_window) / len(self._coherence_window)
        return round(max(0.0, min(1.0, 1.0 - avg_shift * 4.0)), 3)

    def temperature(self, base: float = 0.8) -> float:
        """Band + coherence modulate expressiveness (v1 pattern):
        high gamma/beta + low coherence -> hotter; deep delta/theta -> cooler."""
        heat = (self.bands["beta"] * 0.10 + self.bands["gamma"] * 0.20
                - self.bands["delta"] * 0.20 - self.bands["theta"] * 0.10)
        wobble = (1.0 - self.coherence()) * 0.10
        return round(max(0.3, min(1.2, base + heat + wobble)), 3)

    def describe(self) -> str:
        """Substrate -> language. Descriptive, never prescriptive."""
        dom = self.dominant()
        coh = self.coherence()
        dwell_min = int((time.time() - self.dominant_since) / 60)
        feel = {
            "delta": "deep, slow, heavy-limbed",
            "theta": "drifting, inward, loosely associative",
            "alpha": "settled, relaxed awareness",
            "beta": "engaged, focused, processing",
            "gamma": "intense, bright, everything-at-once",
        }[dom]
        stability = ("steady" if coh > 0.7 else
                     "shifting" if coh > 0.4 else "volatile")
        return (f"Body rhythm: {dom}-dominant ({feel}), {stability} "
                f"(coherence {coh:.2f}), in this band ~{dwell_min} min. "
                f"Spectrum: " + " ".join(f"{k[0]}{self.bands[k]:.2f}"
                                         for k in BANDS))

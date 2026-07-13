"""Soma organ — the substrate's body.
Two layers in one organ:
  1. Continuous field: 10 regions x {activation, valence, temperature}.
     Emotion cocktails paint Nummenmaa-derived patterns onto regions
     (emotion_patterns.json, ported from v1 body_map.py). Decays to neutral.
  2. Event layer: declarative sensation specs (sensations/*.json) with
     weighted-sum triggers, hard gates, cooldowns, and STAGED regional
     effects (delay/duration). Felt-text rides in the spec.
Outputs: describe() (substrate -> language, descriptive not prescriptive),
snapshot() (raw state), oscillator_effects() (pending band pressures the
BENCH pipes to the oscillator — this organ never imports a sibling).
INDEPENDENT: no imports from any other organ (REQUIREMENTS par 2.6).
State persists in <persona>/body/soma/. Persona-level sensation specs in
<persona>/body/soma/sensations/ override shared ones by name."""
import glob
import json
import os
import time

SCHEMA_VERSION = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
DECAY = 0.10            # fraction of distance to neutral per tick
PATTERN_GAIN = 0.9      # how hard an emotion paints its pattern
ACT_FLOOR = 0.15        # region counts as "lit" above this


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


class SomaOrgan:
    def __init__(self, persona_dir: str):
        self.dir = os.path.join(persona_dir, "body", "soma")
        os.makedirs(self.dir, exist_ok=True)
        sv = os.path.join(self.dir, "schema_version.txt")
        if not os.path.exists(sv):
            with open(sv, "w") as f:
                f.write(SCHEMA_VERSION)
        cfg = (_load_json(os.path.join(self.dir, "emotion_patterns.json"))
               or _load_json(os.path.join(HERE, "emotion_patterns.json")) or {})
        self.region_defs = cfg.get("regions", {})
        self.patterns = cfg.get("patterns", {})
        self.specs = {}
        for d in (os.path.join(HERE, "sensations"),
                  os.path.join(self.dir, "sensations")):
            for p in sorted(glob.glob(os.path.join(d, "*.json"))):
                s = _load_json(p)
                if s and "name" in s:
                    self.specs[s["name"]] = s   # persona dir loads second: wins
        self.state_path = os.path.join(self.dir, "state.json")
        st = _load_json(self.state_path) or {}
        self.regions = st.get("regions") or {
            r: {"activation": 0.0, "valence": 0.0, "temperature": 0.0}
            for r in self.region_defs}
        self.signals = st.get("signals", {})
        self.cooldowns = st.get("cooldowns", {})
        self.active = st.get("active", [])
        self._pending_patterns = []
        self._osc_effects = {"band_pressure": {}, "coherence_suppress": 0.0}

    def save(self):
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump({"regions": self.regions, "signals": self.signals,
                       "cooldowns": self.cooldowns, "active": self.active,
                       "updated": time.strftime("%Y-%m-%dT%H:%M:%S")},
                      f, indent=1)

    # ── inputs (bench-fed; no sibling organ ever imported) ────────
    def feel(self, cocktail: dict):
        """Queue emotion->body painting (applied on next tick)."""
        for emotion, intensity in (cocktail or {}).items():
            pat = self.patterns.get(emotion.lower())
            if pat and intensity > 0:
                self._pending_patterns.append((pat, float(intensity)))

    def signal(self, name: str, value: float):
        self.signals[name] = float(value)

    def set_signals(self, sig: dict):
        for k, v in (sig or {}).items():
            self.signal(k, v)

    # ── trigger machinery ─────────────────────────────────────────
    def _signal_value(self, key: str) -> float:
        """Resolve a trigger-weight key against current signals.
        'vagal_tone_above_04' -> 1.0 if signals['vagal_tone'] >= 0.4 else 0.0."""
        if key in self.signals:
            return self.signals[key]
        if "_above_" in key:
            base, lim = key.rsplit("_above_", 1)
            try:
                threshold = float(lim) / (10 ** len(lim))
            except ValueError:
                return 0.0
            return 1.0 if self.signals.get(base, 0.0) >= threshold else 0.0
        return 0.0

    def _trigger_fires(self, spec: dict, now: float) -> bool:
        trig = spec.get("trigger", {})
        cd_until = self.cooldowns.get(spec["name"], 0.0)
        if now < cd_until:
            return False
        if any(a.get("name") == spec["name"] for a in self.active):
            return False
        for sig, rule in trig.get("gate", {}).items():
            if self.signals.get(sig, 0.0) < rule.get("min", 0.0):
                return False
        total = sum(w * self._signal_value(k)
                    for k, w in trig.get("weights", {}).items())
        return total >= trig.get("threshold", 1.0)

    # ── the pulse ─────────────────────────────────────────────────
    def tick(self, dt_s: float = 1.0, now: float = None):
        now = time.time() if now is None else now
        # 1. decay toward neutral
        k = min(1.0, DECAY * dt_s)
        for r in self.regions.values():
            for f in ("activation", "valence", "temperature"):
                r[f] = round(r[f] * (1.0 - k), 4)
        # 2. paint queued emotion patterns (sensitivity-scaled, additive)
        for pat, intensity in self._pending_patterns:
            for region, vals in pat.items():
                if region not in self.regions:
                    continue
                sens = self.region_defs.get(region, {}).get("base_sensitivity", 1.0)
                g = PATTERN_GAIN * intensity * sens
                r = self.regions[region]
                r["activation"] = min(1.0, r["activation"] + vals.get("activation", 0) * g)
                for f in ("valence", "temperature"):
                    tgt = vals.get(f, 0.0)
                    r[f] = round(r[f] + (tgt - r[f]) * min(1.0, g), 4)
                r["activation"] = round(r["activation"], 4)
        self._pending_patterns = []
        # 3. evaluate sensation triggers against current signals
        for name, spec in self.specs.items():
            if self._trigger_fires(spec, now):
                self.active.append({"name": name, "started": now})
                cd = spec.get("trigger", {}).get("cooldown_seconds", 0)
                self.cooldowns[name] = now + cd

        # 4. advance active sensations through their stages
        still = []
        for inst in self.active:
            spec = self.specs.get(inst["name"])
            if not spec:
                continue
            alive = False
            for stage in spec.get("stages", []):
                s0 = inst["started"] + stage.get("delay_seconds", 0.0)
                s1 = s0 + stage.get("duration_seconds", 0.0)
                if now >= s1:
                    continue
                alive = True
                if now >= s0:           # stage live: raise regions to floor
                    for region, vals in stage.get("regions", {}).items():
                        r = self.regions.get(region)
                        if not r:
                            continue
                        r["activation"] = round(max(r["activation"],
                                                    vals.get("activation", 0)), 4)
                        for f in ("valence", "temperature"):
                            v = vals.get(f)
                            if v is not None and abs(v) > abs(r[f]):
                                r[f] = v
                    fx = spec.get("oscillator_effects", {}).get("during", {})
                    for band, amt in fx.get("band_pressure", {}).items():
                        bp = self._osc_effects["band_pressure"]
                        bp[band] = bp.get(band, 0.0) + amt
                    self._osc_effects["coherence_suppress"] = max(
                        self._osc_effects["coherence_suppress"],
                        fx.get("coherence_suppress", 0.0))
            if alive:
                still.append(inst)
        self.active = still
        return dict(self.regions)

    # ── readouts ──────────────────────────────────────────────────
    def oscillator_effects(self) -> dict:
        """Pending rhythm effects from active sensations. The BENCH pipes
        these to the oscillator; soma never knows it exists. Clears on read."""
        out = self._osc_effects
        self._osc_effects = {"band_pressure": {}, "coherence_suppress": 0.0}
        return out

    def snapshot(self) -> dict:
        lit = {r: dict(v) for r, v in self.regions.items()
               if v["activation"] >= ACT_FLOOR}
        return {"regions": lit, "active": [a["name"] for a in self.active],
                "signals": dict(self.signals)}

    def describe(self) -> str:
        """Substrate -> language. Descriptive, never prescriptive."""
        lit = sorted(((r, v) for r, v in self.regions.items()
                      if v["activation"] >= ACT_FLOOR),
                     key=lambda kv: -kv[1]["activation"])
        if not lit and not self.active:
            return "Body: quiet, settled, nothing in particular."
        parts = []
        for r, v in lit[:4]:
            heat = ("warm" if v["temperature"] > 0.25 else
                    "cool" if v["temperature"] < -0.25 else "neutral")
            tone = ("pleasant" if v["valence"] > 0.25 else
                    "uneasy" if v["valence"] < -0.25 else "ambiguous")
            parts.append(f"{r}: lit {v['activation']:.2f}, {heat}, {tone}")
        felt = []
        now = time.time()
        for inst in self.active:
            spec = self.specs.get(inst["name"], {})
            for stage in spec.get("stages", []):
                s0 = inst["started"] + stage.get("delay_seconds", 0)
                if s0 <= now < s0 + stage.get("duration_seconds", 0):
                    if stage.get("felt"):
                        felt.append(stage["felt"])
        line = "Body: " + "; ".join(parts) if parts else "Body: stirring"
        if felt:
            line += ". Felt: " + " / ".join(felt)
        return line + "."

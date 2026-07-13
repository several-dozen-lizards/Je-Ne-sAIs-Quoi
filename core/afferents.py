"""core/afferents.py — afferent percept -> soma signal vocabulary.
ONE AFFERENT SCHEMA, TWO BACKENDS (settled doctrine): the room's sim
contact and the basswood hand's thermistor/Velostat/piezo stack emit
the SAME fields ({force_n, pressure_kpa, temperature_c, texture}), so
this one translation serves both. Sim touch and hardware touch land in
the soma identically — swapping backends is a driver swap, never
translation archaeology.

Pure module. The soma organ is never imported and never edited: we
speak its existing signal language (set_signals) and let declarative
sensation specs (core/soma/sensations/*.json, persona-overridable)
decide what FIRES. Par 2.6 intact.

skin_neutral_c is CONSTITUTIONAL (trait layer, perception.json):
a warm-blooded body's contact-neutral sits ~33 C; a den-adapted
ectotherm's sits near ambient. The same 32 C rock is nothing to one
palm and a bloom of warmth to another. Temperature is a relationship,
not a number."""

SKIN_NEUTRAL_C_DEFAULT = 33.0
FULL_SCALE_DELTA_C = 15.0     # +/- this many degrees = signal saturates
FORCE_FULL_N = 20.0
PRESSURE_FULL_KPA = 50.0

TOUCH_SIGNALS = ("touch_cold", "touch_warm", "touch_force",
                 "touch_pressure")


def afferent_signals(percept: dict,
                     skin_neutral_c: float = SKIN_NEUTRAL_C_DEFAULT) -> dict:
    """Translate one contact afferent into transient soma signals,
    all normalized 0..1. Caller is responsible for clearing them after
    the tick that evaluates triggers (one-shot transients)."""
    sig = {}
    t = percept.get("temperature_c")
    if t is not None:
        delta = (float(t) - skin_neutral_c) / FULL_SCALE_DELTA_C
        sig["touch_warm"] = round(max(0.0, min(1.0, delta)), 3)
        sig["touch_cold"] = round(max(0.0, min(1.0, -delta)), 3)
    f = percept.get("force_n")
    if f is not None:
        sig["touch_force"] = round(min(1.0, float(f) / FORCE_FULL_N), 3)
    p = percept.get("pressure_kpa")
    if p is not None:
        sig["touch_pressure"] = round(min(1.0, float(p) / PRESSURE_FULL_KPA), 3)
    return sig


def merge_max(base: dict, extra: dict) -> dict:
    """Several touches in one turn: the strongest of each signal wins."""
    for k, v in extra.items():
        if v > base.get(k, 0.0):
            base[k] = v
    return base

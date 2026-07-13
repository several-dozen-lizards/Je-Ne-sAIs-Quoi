"""recall_bias — the rhythm bends the remembering (circulatory cut 3).
Pure function, declarative map, NO organ imports: the BENCH composes
oscillator dominant-band -> recall weight modulation. Theta/beta/gamma
REDISTRIBUTE the weight budget (renormalized to the original sum: same
total attention, different shape). Delta DAMPENS (deliberately not
renormalized: a deep-slow body surfaces less, full stop).
Alpha is the settled baseline: identity."""

BAND_BIAS = {
    "alpha": {},                                   # settled: weights as configured
    "theta": {"emotion": 1.5, "semantic": 0.7,     # drifting: mood-led,
              "recency": 1.2},                     #   loosely associative
    "beta":  {"semantic": 1.6, "emotion": 0.7,     # focused: on-topic,
              "entity": 1.2},                      #   names matter
    "gamma": {"recency": 1.6, "emotion": 1.2},     # bright: the now burns
    "delta": {"__dampen__": 0.55},                 # deep: everything quiets
}


def band_biased_weights(weights: dict, dominant_band: str) -> dict:
    """Return a new weights dict bent by the dominant band. Never mutates."""
    bias = BAND_BIAS.get(dominant_band, {})
    w = dict(weights)
    if not bias:
        return w
    if "__dampen__" in bias:
        k = bias["__dampen__"]
        return {name: v * k for name, v in w.items()}
    original_sum = sum(w.values())
    for name, mult in bias.items():
        if name in w:
            w[name] = w[name] * mult
    new_sum = sum(w.values())
    if new_sum > 0:
        scale = original_sum / new_sum
        w = {name: v * scale for name, v in w.items()}
    return w

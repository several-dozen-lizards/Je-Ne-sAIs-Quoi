"""Deterministic first experiment for the shadow interference field."""
from .organ import DEFAULT_TIMESCALES_S, InterferenceFieldOrgan


def _events(times, source="neutral"):
    return [{"ts": round(float(ts), 9), "magnitude": 1.0,
             "source": source} for ts in times]


def standard_patterns():
    isolated = _events((0.0,))
    repeated = _events(range(0, 21, 2))
    # Two individually steady trains. Their union repeatedly approaches and
    # separates without assigning either source a quality.
    a = _events((n / 1.20 for n in range(25)), "feed_a")
    b = _events((n / 1.33 for n in range(27)), "feed_b")
    near_rhythms = sorted(a + b, key=lambda event: event["ts"])
    sustained_stop = _events(range(0, 21, 1))
    return {
        "isolated_pulse": (isolated, 12.0),
        "evenly_repeated_pulses": (repeated, 20.0),
        "two_near_rhythms": (near_rhythms, 20.0),
        "sustained_then_stopped": (sustained_stop, 32.0),
    }


def run_standard_experiment(timescales_s=DEFAULT_TIMESCALES_S):
    results = {}
    for name, (events, at) in standard_patterns().items():
        results[name] = InterferenceFieldOrgan.project(
            events, timescales_s=timescales_s, at=at)
        results[name]["input_event_count"] = len(events)
    # Same neutral magnitudes and endpoints, different interval structure.
    regular = _events((0, 2, 4, 6, 8, 10))
    rearranged = _events((0, 1, 2, 3, 9, 10))
    regular_field = InterferenceFieldOrgan.project(
        regular, timescales_s=timescales_s, at=10.0)
    control_field = InterferenceFieldOrgan.project(
        rearranged, timescales_s=timescales_s, at=10.0)
    return {
        "schema": 1,
        "claim_boundary": "shadow field only; no downstream effect tested",
        "timescales_s": list(timescales_s),
        "patterns": results,
        "timing_control": {
            "same_magnitudes": True,
            "same_start_and_end": True,
            "regular_axes": regular_field["axes"],
            "rearranged_axes": control_field["axes"],
            "axes_changed": regular_field["axes"] != control_field["axes"],
        },
    }

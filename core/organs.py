"""core/organs.py — the organ registry (REQUIREMENTS par 2.6 made real).

One vocabulary for what a persona can run. The SAME ids appear in:
  - roster enabled_organs   (per persona x model CONFIGURATION)
  - spec module_capability  (per model CEILING, discovered)
  - code wire-sites         (membership checks in contract/cockpit)

Law encoded here:
  - the dependency graph is explicit and enforced at startup (hard fail);
  - ceilings are DISCOVERED, never assumed: an organ missing from the
    spec's validated list WARNS and proceeds (enabling it is how the
    harness discovers the ceiling), but an organ in saturates_on
    HARD-FAILS (that is a measured wall with receipts, not a guess);
  - unknown ids hard-fail (no silent typo-organs);
  - the EMPTY set is legal — a bare-model turn is the control condition
    every ceiling measurement is compared against.
"""
from dataclasses import dataclass


class OrganConfigError(Exception):
    """A configuration that must not boot: unknown organ, unmet
    dependency, or an organ measured to saturate this model."""


@dataclass(frozen=True)
class OrganDef:
    organ_id: str
    deps: tuple            # organ ids this one requires
    desc: str
    cost: str = "local"    # "local" | "api" — what a tick/turn spends
    loop: bool = False     # runs as a background thread in the cockpit


REGISTRY = {o.organ_id: o for o in (
    OrganDef("memory_emotion", (),
             "encode/recall/layers triad + bonds; the irreducible core, "
             "flaggable like everything else (bare turns = control)"),
    OrganDef("oscillator", (),
             "band rhythm; heartbeat ticks across the gaps"),
    OrganDef("soma", (),
             "body map + declarative sensation specs"),
    OrganDef("altered_state", ("memory_emotion", "oscillator", "soma"),
             "event-circulated altered-state metabolism: profile vectors "
             "bend body, rhythm, and recall while affect remains descriptive"),
    OrganDef("perception", (),
             "adaptive camera/audio exteroception: persistent modality "
             "fields, provenance, rhythm-shaped admission, and raw "
             "sensory pressure (device and model independent)"),
    OrganDef("feel", ("memory_emotion",),
             "language->substrate judge loop (Haiku); writes felt state "
             "back into the organ after each exchange", cost="api"),
    OrganDef("rhythm_affect", ("oscillator",),
             "inhabited-band tone seeds the cocktail before recall"),
    OrganDef("recall_bias", ("oscillator", "memory_emotion"),
             "band-biased recall weights"),
    OrganDef("room_sense", (),
             "room client + POV perception filter (percepts in)"),
    OrganDef("room_actions", ("room_sense",),
             "<act> grammar: volitional move/sit/stand/contact/say (actions out)"),
    OrganDef("afferents", ("room_sense", "soma"),
             "contact percepts -> transient soma signals (touch lands)"),
    OrganDef("tropism", ("room_sense",),
             "the worm: place-pressure autonomous movement", loop=True),
    OrganDef("social", ("room_sense", "memory_emotion"),
             "social-pressure conversation loop with habituation "
             "(turn cost follows the model)", loop=True),
    OrganDef("gist", ("memory_emotion",),
             "rolling middle-distance memory: turns older than the "
             "verbatim window fold into a persisted running summary "
             "(one constant session; a Haiku call per fold)",
             cost="api"),
    OrganDef("my_life", (),
             "persona re-reads their own recent writings each turn"),
    OrganDef("heartbeat", (),
             "the body's own clock: osc/soma advance between turns "
             "instead of settling only when observed (the meters "
             "breathe; no deps — it ticks whatever organs exist)",
             loop=True),
    OrganDef("dmn", ("memory_emotion",),
             "idle metabolism: elapsed-time pressure, persistent "
             "salience candidates, and decaying preoccupation warmth "
             "circulate into generated private thoughts. Gating is "
             "free; discharge spends the roster's idle_model and may "
             "fold the lived result into gist", loop=True),
    OrganDef("intention_loom", ("dmn",),
             "possibility cues and self-owned intentions compete through "
             "the DMN; one local append-only movement may form, reframe, "
             "pause, satisfy, or release continuity without starting a "
             "project or gaining outward authority"),
    OrganDef("writing_desk", ("dmn",),
             "private append-only writing projects compete through the DMN; "
             "admitted material and open projects may become one local, "
             "authority-bounded action whose consequence returns to the field"),
    OrganDef("archive_reader", ("dmn",),
             "human-granted documented conversation history may recur at a "
             "genuine DMN boundary, compete in the shared field, and become "
             "one local private reading whose lived consequence returns to "
             "the field without rewriting history or transplanting memory"),
    OrganDef("document_reader", ("dmn",),
             "human-owned private documents may become optional exact-section "
             "candidates at a genuine DMN boundary; one local reading may "
             "continue, search the private shelf, bookmark, or make a cited "
             "report whose consequence returns to the shared field"),
    OrganDef("research_desk", ("dmn",),
             "self-formed or human-offered interests may compete through the "
             "shared field; a local planner may take one bounded step through "
             "an isolated read-only public-web boundary and return cited "
             "private evidence, notes, or reports to the same circulation"),
    OrganDef("atelier", ("dmn",),
             "human-admitted or self-offered creative material may compete "
             "through the shared "
             "field and become one host-validated private artifact whose lived "
             "consequence returns to the same circulation"),
    OrganDef("agency", ("dmn",),
             "a winning salience candidate may become interruptible private "
             "work through persona-owned, authority-gated capabilities; "
             "effects return to the shared field", cost="api"),
)}


def validate(enabled, spec: dict = None):
    """Check an enabled set against the registry and (optionally) a
    model spec. Returns a list of warning strings. Raises
    OrganConfigError on anything that must not boot."""
    enabled = set(enabled or ())
    unknown = enabled - set(REGISTRY)
    if unknown:
        raise OrganConfigError(
            f"unknown organ id(s): {sorted(unknown)} — registry knows "
            f"{sorted(REGISTRY)}")
    for oid in sorted(enabled):
        missing = set(REGISTRY[oid].deps) - enabled
        if missing:
            raise OrganConfigError(
                f"'{oid}' requires {sorted(missing)} "
                f"(dependency law, par 2.6)")
    warnings = []
    if spec:
        cap = (spec.get("module_capability") or {})
        walls = enabled & set(cap.get("saturates_on") or ())
        if walls:
            raise OrganConfigError(
                f"organ(s) {sorted(walls)} are in this model's "
                f"saturates_on — that is a measured wall with receipts; "
                f"remove them or re-measure the ceiling first")
        unproven = enabled - set(cap.get("validated") or ())
        if unproven:
            warnings.append("unvalidated on this model (discovery "
                            f"mode): {sorted(unproven)}")
    return warnings


def loops(enabled):
    """The subset of an enabled set that runs as background threads."""
    return {oid for oid in set(enabled or ())
            if oid in REGISTRY and REGISTRY[oid].loop}


def legacy_set(use_osc=True, use_soma=True, room=False):
    """The pre-registry default: exactly what an engine ran before
    par 2.6 landed. ONE recipe, shared by the engine's compat shim and
    the cockpit's override path — never two copies of this drift."""
    s = {"memory_emotion", "feel", "my_life"}
    if use_osc:
        s |= {"oscillator", "rhythm_affect", "recall_bias"}
    if use_soma:
        s.add("soma")
    if room:
        s |= {"room_sense", "room_actions"}
        if use_soma:
            s.add("afferents")
    return s

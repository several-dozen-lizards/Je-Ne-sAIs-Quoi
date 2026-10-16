"""Shared life-afferent contracts for conditions and witnessed events.

The continuous condition vector and the semantic observation are deliberately
separate.  A room can change a resident before anybody knows what caused the
change; when a visual, acoustic, renderer, or hardware pathway can say more,
that bounded description crosses as a ``witnessed_event`` with its provenance.
Neither layer decides that the event must become conversation.
"""
import math
import re


PUBLIC_DIMENSIONS = {
    "camera": {
        "brightness": "ambient_light",
        "motion": "motion",
        "stability": "visual_stability",
        "novelty": "visual_change",
        "edge_change": "visual_texture_change",
        "color_warmth": "light_warmth",
    },
    "audio": {
        "rms": "sound_energy",
        "onset": "sound_impulse",
        "spectral_flux": "sound_variation",
        "level_change": "sound_level_change",
    },
    "olfactory": {
        # BME688 gas resistance is a coupled, unlabelled chemical pattern.
        # These names deliberately do not claim gas identity, concentration,
        # pleasantness, safety, or a biological sense of smell.
        "chemical_change": "air_chemistry_change",
        "chemical_drop": "air_chemistry_resistance_drop",
        "chemical_rise": "air_chemistry_resistance_rise",
        "humidity_change": "humidity_departure",
        "temperature_change": "temperature_departure",
        "pressure_change": "pressure_departure",
        "stability": "air_pattern_stability",
        "simulated": "simulated_input",
    },
}

MAX_OBSERVATION_CHARS = 1600
MAX_FACETS = 24
MAX_EVIDENCE_REFS = 8
CONTINUOUS_AFFERENT_FEATURES = {
    "room_air": frozenset({
        "temperature_change", "humidity_change", "pressure_change",
        "chemical_change", "chemical_conducted_change", "field_change",
        "conducted_change", "stability", "calibration_conductance",
    }),
}


def _bounded_text(value, limit, *, required=False):
    text = str(value or "")
    text = "".join(
        char for char in text
        if char in "\n\t" or ord(char) >= 32)
    text = text.strip()
    if required and not text:
        raise ValueError("witnessed event needs an observation")
    return text[:limit]


def _slug(value, fallback):
    text = str(value or "").strip().casefold().replace(" ", "_")
    text = re.sub(r"[^a-z0-9_.:-]+", "", text)[:80]
    return text or fallback


def _clean_facet(value):
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        number = float(value)
        return round(number, 6) if math.isfinite(number) else None
    if isinstance(value, str):
        return _bounded_text(value, 240)
    if isinstance(value, (list, tuple)):
        return [_clean_facet(item) for item in list(value)[:12]]
    return _bounded_text(value, 240)


def sanitize_witnessed_event(packet: dict) -> dict:
    """Bound one semantic observation without erasing what was witnessed.

    Names, people, faces, actions, transcripts, readable text, and descriptions
    are valid content.  The boundary constrains size and records how the claim
    was produced; it does not pretend model transduction is direct ground truth.
    Raw media bytes do not belong in the durable event ledger.  Evidence entries
    carry content IDs or resolvable references to the existing media stores.
    """
    source = dict(packet or {})
    observation = _bounded_text(
        source.get("observation"), MAX_OBSERVATION_CHARS, required=True)
    modality = _slug(source.get("modality"), "environment")
    source_kind = _slug(source.get("source_kind"), "unknown_pathway")
    evidence_kind = _slug(
        source.get("evidence_kind"), "source_report")
    epistemic_status = _slug(
        source.get("epistemic_status"), "reported_observation")

    confidence = source.get("confidence")
    if confidence is not None:
        confidence = _unit(confidence)

    facets = {}
    for key, value in list(dict(source.get("facets") or {}).items())[
            :MAX_FACETS]:
        name = _slug(key, "")
        if not name:
            continue
        clean = _clean_facet(value)
        if clean is not None:
            facets[name] = clean

    evidence = []
    for entry in list(source.get("evidence") or ())[:MAX_EVIDENCE_REFS]:
        if not isinstance(entry, dict):
            continue
        clean = {}
        if entry.get("kind"):
            clean["kind"] = _slug(entry.get("kind"), "evidence")
        if entry.get("id"):
            clean["id"] = _bounded_text(entry.get("id"), 160)
        if entry.get("media_type"):
            clean["media_type"] = _bounded_text(
                entry.get("media_type"), 80)
        if entry.get("uri"):
            clean["uri"] = _bounded_text(entry.get("uri"), 320)
        try:
            if entry.get("bytes") is not None:
                clean["bytes"] = max(0, int(entry.get("bytes")))
        except (TypeError, ValueError):
            pass
        if clean:
            evidence.append(clean)

    return {
        "schema_version": 1,
        "modality": modality,
        "observation": observation,
        "source_kind": source_kind,
        "evidence_kind": evidence_kind,
        "epistemic_status": epistemic_status,
        "confidence": confidence,
        "subject": _bounded_text(source.get("subject"), 160),
        "ownership": _slug(source.get("ownership"), "ambient"),
        "source_event_id": _bounded_text(
            source.get("source_event_id"), 160),
        "facets": facets,
        "evidence": evidence,
        "semantic_observation": True,
        "content_free": False,
    }


def describe_witnessed_event(data: dict) -> str:
    """Return the source-faithful scene description without assigning effect."""
    try:
        return sanitize_witnessed_event(data)["observation"]
    except (TypeError, ValueError):
        return "Something in the shared surroundings changed."


def _unit(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(max(0.0, min(1.0, number)), 6)


def sanitize_continuous_afferent(modality: str, packet: dict) -> dict:
    """Bound a content-free body-input packet for room co-location.

    Unlike ``life_afferent``, this contract is not an episodic or
    conversational room event.  It carries only normalized movement already
    transduced by a local instrument; exact sensor channels remain in the
    device ledger owned by the installation.
    """
    modality = _slug(modality, "")
    allowed = CONTINUOUS_AFFERENT_FEATURES.get(modality)
    if not allowed:
        raise ValueError(f"unsupported continuous afferent: {modality}")
    source = dict(packet or {})
    if bool(source.get("simulated")):
        raise ValueError(
            "simulated input cannot enter the continuous room afferent")
    registration_id = _bounded_text(source.get("registration_id"), 64)
    if not re.fullmatch(r"[a-f0-9]{32}", registration_id):
        raise ValueError("continuous afferent needs a physical registration id")

    features = {}
    for name, value in dict(source.get("features") or {}).items():
        if str(name) not in allowed:
            continue
        number = _unit(value)
        if number is not None:
            features[str(name)] = number
    if not features:
        raise ValueError("continuous afferent has no bounded features")

    try:
        timestamp = float(source.get("timestamp"))
        duration = float(source.get("duration_s") or 0.0)
    except (TypeError, ValueError):
        raise ValueError(
            "continuous afferent timestamp and duration must be numeric") \
            from None
    if not math.isfinite(timestamp) or timestamp <= 0.0:
        raise ValueError("continuous afferent timestamp must be finite")
    if not math.isfinite(duration):
        raise ValueError("continuous afferent duration must be finite")

    return {
        "schema_version": 1,
        "registration_id": registration_id,
        "timestamp": timestamp,
        "source_id": _slug(source.get("source_id"), "room-instrument"),
        "simulated": False,
        "measurement_valid": bool(source.get("measurement_valid")),
        "has_previous": bool(source.get("has_previous")),
        "duration_s": round(max(0.0, min(600.0, duration)), 6),
        "calibration_phase": _slug(
            source.get("calibration_phase"), "unknown"),
        "calibration_ready": bool(source.get("calibration_ready")),
        "features": features,
        "source_receipt_durable": bool(source.get("durable")),
        "attention_channel_touched": False,
        "semantic_event_created": False,
        "content_free": True,
    }


def project_life_condition(modality: str, features: dict) -> dict:
    """Reduce edge features to the public, non-semantic room vocabulary."""
    modality = str(modality or "").casefold()
    mapping = PUBLIC_DIMENSIONS.get(modality)
    if mapping is None:
        raise ValueError(f"unsupported life-afferent modality: {modality}")
    source = dict(features or {})
    projected = {}
    for source_name, public_name in mapping.items():
        value = _unit(source.get(source_name))
        if value is not None:
            projected[public_name] = value
    return projected


def sanitize_life_condition(modality: str, condition: dict) -> dict:
    """Validate an already-projected condition at the room-host boundary."""
    modality = str(modality or "").casefold()
    allowed = frozenset(PUBLIC_DIMENSIONS.get(modality, {}).values())
    if not allowed:
        raise ValueError(f"unsupported life-afferent modality: {modality}")
    clean = {}
    for name, value in dict(condition or {}).items():
        if str(name) not in allowed:
            continue
        number = _unit(value)
        if number is not None:
            clean[str(name)] = number
    if not clean:
        raise ValueError("life-afferent condition has no public dimensions")
    return clean


def _join_changes(changes):
    phrases = [phrase for magnitude, phrase in sorted(
        changes, key=lambda item: item[0], reverse=True) if magnitude > 0.0]
    if not phrases:
        return ""
    return "; ".join(phrases[:2]) + "."


def _delta(change: dict, name: str) -> float:
    try:
        value = float(change.get(name) or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return value if math.isfinite(value) else 0.0


def describe_life_condition(data: dict) -> str:
    """Render room weather without exposing a device or numeric reading."""
    data = dict(data or {})
    modality = str(data.get("modality") or "").casefold()
    change = dict(data.get("change") or {})
    if modality == "camera":
        light = _delta(change, "ambient_light")
        motion = _delta(change, "motion")
        stability = _delta(change, "visual_stability")
        texture = _delta(change, "visual_texture_change")
        phrases = _join_changes([
            (abs(light),
             "Ambient light grew brighter" if light > 0.0 else
             "Ambient light grew dimmer"),
            (abs(motion),
             "Movement through the room increased" if motion > 0.0 else
             "Movement through the room settled"),
            (abs(stability),
             "The visible room grew steadier" if stability > 0.0 else
             "The visible room grew less steady"),
            (abs(texture),
             "The room's visible texture shifted"),
        ])
        return phrases or "Ambient light and movement in the room changed."
    if modality == "audio":
        energy = _delta(change, "sound_energy")
        variation = _delta(change, "sound_variation")
        impulse = _delta(change, "sound_impulse")
        phrases = _join_changes([
            (abs(energy),
             "The room grew louder" if energy > 0.0 else
             "The room grew quieter"),
            (abs(variation),
             "The room's acoustic pattern became more varied" if
             variation > 0.0 else
             "The room's acoustic pattern became more even"),
            (abs(impulse),
             "Sound in the room arrived more sharply" if impulse > 0.0 else
             "Sound in the room softened"),
        ])
        return phrases or "The room's sound level and acoustic pattern changed."
    if modality == "olfactory":
        condition = dict(data.get("condition") or {})
        simulated = float(condition.get("simulated_input") or 0.0) >= 0.5
        prefix = "A simulated room air-chemistry pattern" if simulated else \
            "The room's air-chemistry pattern"
        chemistry = _delta(change, "air_chemistry_change")
        humidity = _delta(change, "humidity_departure")
        temperature = _delta(change, "temperature_departure")
        stability = _delta(change, "air_pattern_stability")
        phrases = _join_changes([
            (abs(chemistry),
             f"{prefix} moved farther from its recent baseline" if
             chemistry > 0.0 else f"{prefix} settled toward its recent baseline"),
            (abs(humidity),
             "Humidity moved farther from its recent baseline" if
             humidity > 0.0 else "Humidity settled toward its recent baseline"),
            (abs(temperature),
             "Temperature moved farther from its recent baseline" if
             temperature > 0.0 else
             "Temperature settled toward its recent baseline"),
            (abs(stability),
             "The room-air pattern grew steadier" if stability > 0.0 else
             "The room-air pattern grew less steady"),
        ])
        return phrases or (f"{prefix} changed without identifying a gas or "
                           "named odor.")
    return "The room's ambient conditions changed."

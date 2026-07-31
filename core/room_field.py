"""Per-resident reciprocal pressure from shared room geometry.

The host supplies shared facts.  This private projector combines them with the
resident's own oscillator, affect, bonds, and perception traits.  Receipts are
content-free aggregates; presence may exert pressure but never creates a
feeling label, intention, movement, belief, or social obligation.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from copy import deepcopy
from typing import Any, Mapping

from core.oscillator.organ import BANDS
from core.perception import (
    AFFORDANCE_CHANNELS,
    AMBIENT_C,
    member_pos,
    score_members,
    score_objects,
)
from core.substrate import SUBSTRATE_COUPLING_GAIN


ROOM_FIELD_COUPLING_GAIN = SUBSTRATE_COUPLING_GAIN / 3.0


def _unit(value: Any) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(value):
        return 0.0
    return max(0.0, min(1.0, value))


def _distance(left, right) -> float:
    try:
        return math.dist([float(left[0]), float(left[1])],
                         [float(right[0]), float(right[1])])
    except (TypeError, ValueError, IndexError):
        return float("inf")


def _saturate(value: float) -> float:
    value = max(0.0, float(value))
    return value / (1.0 + value)


def _face_vector(member: Mapping[str, Any]) -> dict[str, float]:
    """Decode the explicitly public face packet; unknown labels stay data."""
    result = {}
    for item in dict(member.get("face") or {}).get("emotions") or []:
        try:
            label, raw = str(item).rsplit(":", 1)
            if label.strip():
                result[label.strip().casefold()] = _unit(raw)
        except (TypeError, ValueError):
            continue
    return result


def _cosine(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    keys = set(left) | set(right)
    if not keys:
        return 0.0
    dot = sum(_unit(left.get(key)) * _unit(right.get(key)) for key in keys)
    ln = math.sqrt(sum(_unit(left.get(key)) ** 2 for key in keys))
    rn = math.sqrt(sum(_unit(right.get(key)) ** 2 for key in keys))
    return dot / (ln * rn) if ln and rn else 0.0


def _facing(source: Mapping[str, Any], target_position) -> float:
    """Continuous alignment of public head/gaze with the resident."""
    here = member_pos(source)
    if here is None or target_position is None:
        return 0.0
    dx = float(target_position[0]) - float(here[0])
    dy = float(target_position[1]) - float(here[1])
    if abs(dx) + abs(dy) < 1e-9:
        return 1.0
    wanted = math.degrees(math.atan2(-dx, dy)) % 360.0
    actual = (
        float(source.get("heading_deg") or 0.0)
        + float(source.get("gaze_yaw_deg") or 0.0)) % 360.0
    difference = abs((actual - wanted + 180.0) % 360.0 - 180.0)
    return _unit((180.0 - difference) / 180.0)


def _signature(snapshot: Mapping[str, Any]) -> str:
    public = {
        "id": snapshot.get("id"),
        "last_seq": snapshot.get("last_seq"),
        "members": {
            name: {
                "position_m": member_pos(value),
                "heading_deg": (
                    value.get("heading_deg") if isinstance(value, dict)
                    else None),
                "gaze_yaw_deg": (
                    value.get("gaze_yaw_deg") if isinstance(value, dict)
                    else None),
                "posture": (
                    value.get("posture") if isinstance(value, dict) else None),
                "gesture": (
                    value.get("gesture") if isinstance(value, dict) else None),
                "face": (
                    value.get("face") if isinstance(value, dict) else None),
            }
            for name, value in sorted(
                dict(snapshot.get("members") or {}).items())},
        "objects": {
            name: {
                "position_m": value.get("position_m"),
                "temperature_c": value.get("temperature_c"),
                "affordances": value.get("affordances"),
                "capability": value.get("capability"),
                "owner": value.get("owner"),
                "pages": value.get("pages"),
                "power": value.get("power"),
            }
            for name, value in sorted(
                dict(snapshot.get("objects") or {}).items())},
    }
    encoded = json.dumps(
        public, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:20]


def project_room_field(
        snapshot: Mapping[str, Any], *, resident: str,
        substrate: Mapping[str, Any] | None = None,
        bias: Mapping[str, Any] | None = None,
        revision_changed: bool = False,
        enabled: bool = True) -> dict:
    """Project bounded oscillator/participation pressure without prose."""
    snapshot = dict(snapshot or {})
    substrate = dict(substrate or {})
    bias = dict(bias or {})
    members = dict(snapshot.get("members") or {})
    objects = dict(snapshot.get("objects") or {})
    me = member_pos(members.get(resident))
    if me is None or not enabled:
        return {
            "schema": 1,
            "mode": ("bypass" if not enabled else "resident_absent"),
            "world_seq": snapshot.get("last_seq"),
            "signature": _signature(snapshot),
            "object_count": 0,
            "other_member_count": 0,
            "band_pressure": {},
            "external_pressure": 0.0,
            "social_presence": 0.0,
            "object_presence": 0.0,
            "thermal_presence": 0.0,
            "revision_novelty": 0.0,
            "relational_projection": {},
            "downstream": [],
        }

    object_scores = score_objects(snapshot, substrate, bias, resident)
    member_scores = score_members(snapshot, substrate, bias, resident)
    bands = {name: _unit(
        (substrate.get("bands") or {}).get(name)) for name in BANDS}
    object_bias = dict(bias.get("objects") or {})
    affordance_bias = dict(bias.get("affordances") or {})
    band_raw = {name: 0.0 for name in BANDS}
    ambient_raw = 0.0
    thermal_raw = 0.0

    for object_id, item in objects.items():
        distance = _distance(me, item.get("position_m"))
        if not math.isfinite(distance):
            continue
        proximity = 1.0 / (1.0 + distance)
        object_weight = max(0.0, float(object_bias.get(object_id, 1.0)))
        thermal_raw += (
            min(abs(float(item.get("temperature_c", AMBIENT_C))
                    - AMBIENT_C) / 12.0, 1.0)
            * proximity * max(0.0, float(bias.get("thermal", 0.3))))
        for affordance, raw_weight in dict(
                item.get("affordances") or {}).items():
            weight = max(0.0, float(raw_weight)) * proximity * object_weight
            weight *= max(
                0.0, float(affordance_bias.get(affordance, 1.0)))
            channel = AFFORDANCE_CHANNELS.get(affordance)
            if channel and channel[0] == "band" and channel[1] in band_raw:
                band_raw[channel[1]] += weight
            else:
                ambient_raw += weight

    social_raw = sum(max(0.0, float(
        item.get("salience", 0.0))) for item in member_scores)
    object_raw = sum(max(0.0, float(
        item.get("salience", 0.0))) for item in object_scores)
    # Social and non-band affordances reinforce the resident's whole current
    # distribution rather than assigning a prescribed band or experience.
    undirected = _saturate(social_raw + ambient_raw)
    total_raw = sum(band_raw.values()) + undirected
    denominator = max(1.0, total_raw)
    pressure = {
        name: round(ROOM_FIELD_COUPLING_GAIN * (
            band_raw[name] + undirected * bands[name]) / denominator, 9)
        for name in BANDS}
    object_presence = _saturate(object_raw)
    social_presence = _saturate(social_raw)
    thermal_presence = _saturate(thermal_raw)
    novelty = 1.0 if revision_changed else 0.0
    external_pressure = (
        object_presence + social_presence + thermal_presence + novelty) / 4.0

    # Identity is used only inside this private projection.  It selects the
    # resident's own bond and ownership relationships; no identity or vector
    # is emitted. Public expression labels have no assigned meaning: only
    # vector magnitude, overlap, and discrepancy are measured.
    cocktail = {
        str(key).casefold(): _unit(value)
        for key, value in dict(substrate.get("cocktail") or {}).items()}
    social_weight = 0.0
    bond_weight = 0.0
    expression_weight = 0.0
    expression_resonance_raw = 0.0
    expression_discrepancy_raw = 0.0
    orientation_raw = 0.0
    bonds = dict(substrate.get("bonds") or {})
    for name, member in members.items():
        if name == resident or not isinstance(member, dict):
            continue
        distance = _distance(me, member_pos(member))
        proximity = 1.0 / (1.0 + 0.5 * distance)
        bond = _unit(bonds.get(name))
        significance = proximity * (0.15 + 0.85 * bond)
        social_weight += significance
        bond_weight += bond * proximity
        orientation_raw += _facing(member, me) * significance
        face = _face_vector(member)
        intensity = math.sqrt(sum(value * value for value in face.values()))
        if intensity:
            expression_weight += intensity * significance
            overlap = _cosine(face, cocktail)
            expression_resonance_raw += overlap * intensity * significance
            expression_discrepancy_raw += (
                (1.0 - overlap) * intensity * significance)

    owned_raw = 0.0
    capability_raw = 0.0
    for object_id, item in objects.items():
        distance = _distance(me, item.get("position_m"))
        if not math.isfinite(distance):
            continue
        proximity = 1.0 / (1.0 + distance)
        if str(item.get("owner") or "").casefold() == resident.casefold():
            owned_raw += proximity
        if item.get("capability"):
            capability_raw += proximity * max(
                0.0, float(object_bias.get(object_id, 1.0)))

    relationship_significance = _saturate(social_weight + bond_weight)
    expression_resonance = (
        expression_resonance_raw / expression_weight
        if expression_weight else 0.0)
    expression_discrepancy = (
        expression_discrepancy_raw / expression_weight
        if expression_weight else 0.0)
    orientation_coupling = (
        orientation_raw / social_weight if social_weight else 0.0)
    personal_object_significance = _saturate(
        owned_raw + capability_raw + max(0.0, object_raw) * 0.25)
    relational_projection = {
        "external_conductance": round(_unit(
            (social_presence + object_presence + _saturate(expression_weight)
             + orientation_coupling) / 4.0), 9),
        "internal_conductance": round(_unit(
            (relationship_significance + expression_resonance
             + _saturate(owned_raw)) / 3.0), 9),
        "associative_distance": round(_unit(expression_discrepancy), 9),
        "cross_source_binding": round(_unit(
            (relationship_significance + expression_resonance
             + orientation_coupling) / 3.0), 9),
    }
    return {
        "schema": 2,
        "mode": "live_reciprocal_room_field",
        "world_seq": snapshot.get("last_seq"),
        "signature": _signature(snapshot),
        "object_count": len(objects),
        "other_member_count": max(0, len(members) - 1),
        "band_pressure": pressure,
        "external_pressure": round(_unit(external_pressure), 9),
        "social_presence": round(social_presence, 9),
        "object_presence": round(object_presence, 9),
        "thermal_presence": round(thermal_presence, 9),
        "revision_novelty": novelty,
        "relationship_significance": round(relationship_significance, 9),
        "expression_presence": round(_saturate(expression_weight), 9),
        "expression_resonance": round(_unit(expression_resonance), 9),
        "expression_discrepancy": round(_unit(expression_discrepancy), 9),
        "orientation_coupling": round(_unit(orientation_coupling), 9),
        "personal_object_significance": round(
            personal_object_significance, 9),
        "relational_projection": relational_projection,
        "downstream": ["oscillator", "participation_field"],
    }


def room_field_controls(snapshot, *, resident, substrate=None, bias=None):
    """Deterministic mismatched controls over the same shared facts."""
    genuine = project_room_field(
        snapshot, resident=resident, substrate=substrate, bias=bias)
    objects = list(dict(snapshot.get("objects") or {}).items())
    members = list(dict(snapshot.get("members") or {}).items())
    bonds = dict((substrate or {}).get("bonds") or {})

    location = deepcopy(snapshot)
    positions = [item.get("position_m") for _, item in objects]
    if positions:
        positions = positions[1:] + positions[:1]
        for (name, _), position in zip(objects, positions):
            location["objects"][name]["position_m"] = position

    affordance = deepcopy(snapshot)
    affordances = [deepcopy(item.get("affordances") or {})
                   for _, item in objects]
    if affordances:
        affordances = affordances[1:] + affordances[:1]
        for (name, _), value in zip(objects, affordances):
            affordance["objects"][name]["affordances"] = value

    relationship_substrate = deepcopy(substrate or {})
    other_names = [name for name, _ in members if name != resident]
    values = [bonds.get(name, 0.0) for name in other_names]
    if values:
        values = values[1:] + values[:1]
        relationship_substrate["bonds"] = dict(
            zip(other_names, values))

    person_location = deepcopy(snapshot)
    person_positions = [
        member_pos(value) for name, value in members if name != resident]
    if person_positions:
        person_positions = person_positions[1:] + person_positions[:1]
        for name, position in zip(other_names, person_positions):
            record = person_location["members"][name]
            if isinstance(record, dict):
                record["position_m"] = position
            else:
                person_location["members"][name] = position

    person_absence = deepcopy(snapshot)
    person_absence["members"] = {
        resident: deepcopy(dict(snapshot.get("members") or {}).get(resident))}

    constant = deepcopy(snapshot)
    for _, item in dict(constant.get("objects") or {}).items():
        item["affordances"] = {}
        item["temperature_c"] = AMBIENT_C
    constant["members"] = {resident: members and dict(
        snapshot.get("members") or {}).get(resident)}

    return {
        "genuine": genuine,
        "object_location_shuffle": project_room_field(
            location, resident=resident, substrate=substrate, bias=bias),
        "affordance_assignment_shuffle": project_room_field(
            affordance, resident=resident, substrate=substrate, bias=bias),
        "relationship_vector_shuffle": project_room_field(
            snapshot, resident=resident, substrate=relationship_substrate,
            bias=bias),
        "person_location_shuffle": project_room_field(
            person_location, resident=resident, substrate=substrate,
            bias=bias),
        "person_absence_control": project_room_field(
            person_absence, resident=resident, substrate=substrate, bias=bias),
        "constant_room_sham": project_room_field(
            constant, resident=resident, substrate=substrate, bias=bias),
    }


class RoomFieldOrgan:
    """Persist only aggregate private projection and public world signature."""

    def __init__(self, persona_dir: str, *, enabled: bool = True):
        self.dir = os.path.join(persona_dir, "body", "room_field")
        os.makedirs(self.dir, exist_ok=True)
        self.state_path = os.path.join(self.dir, "state.json")
        self.events_path = os.path.join(self.dir, "events.jsonl")
        self.enabled = bool(enabled)
        self.state = self._load()

    def _load(self):
        try:
            with open(self.state_path, encoding="utf-8") as handle:
                value = json.load(handle)
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def observe(self, snapshot, *, resident, substrate=None, bias=None):
        signature = _signature(snapshot or {})
        changed = signature != self.state.get("signature")
        receipt = project_room_field(
            snapshot, resident=resident, substrate=substrate, bias=bias,
            revision_changed=changed, enabled=self.enabled)
        if changed:
            with open(self.events_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(
                    receipt, ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        self.state = receipt
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(receipt, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.state_path)
        return {**receipt, "revision_changed": changed}

    def snapshot(self):
        return dict(self.state)

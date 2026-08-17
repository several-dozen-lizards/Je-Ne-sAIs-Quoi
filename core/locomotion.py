"""Pure host-side locomotion geometry.

The resident chooses a destination.  This module describes how that chosen
vector can unfold; it never chooses a target, names a feeling, or moves room
state.  Both exact-coordinate walking and semantic approach actions use the
same profile so the renderer and synthetic body receive one causal account.
"""
from __future__ import annotations

import math


POSITION_EPSILON_M = 0.035
HEADING_EPSILON_DEG = 1.0


def signed_heading_delta(start_deg: float, end_deg: float) -> float:
    """Shortest signed turn from start to end, in [-180, 180)."""
    return (float(end_deg) - float(start_deg) + 180.0) % 360.0 - 180.0


def heading_toward(frm, to) -> float:
    dx = float(to[0]) - float(frm[0])
    dy = float(to[1]) - float(frm[1])
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return 0.0
    return math.degrees(math.atan2(-dx, dy)) % 360.0


def _bounded_motion_time(distance: float, speed: float,
                         acceleration: float) -> float:
    """Triangular or trapezoidal travel time from physical limits."""
    if distance <= POSITION_EPSILON_M:
        return 0.0
    ramp_distance = speed * speed / acceleration
    if distance <= ramp_distance:
        return 2.0 * math.sqrt(distance / acceleration)
    return 2.0 * speed / acceleration + (distance - ramp_distance) / speed


def _turn_time(angle_deg: float) -> float:
    """Turn duration from bounded angular speed/acceleration."""
    distance = abs(float(angle_deg))
    if distance <= HEADING_EPSILON_DEG:
        return 0.0
    return _bounded_motion_time(distance, 165.0, 420.0)


def build_motion_profile(frm, to, *, start_heading_deg: float,
                         arrival_heading_deg: float = None,
                         room_scale_m: float = 4.0) -> dict:
    """Describe one continuous orient -> translate -> settle trajectory.

    Speed and acceleration move over bounded ranges as a function of the
    chosen displacement relative to the room.  There is no arbitrary fixed
    animation duration and no inference about subjective experience.
    """
    start = [float(frm[0]), float(frm[1])]
    destination = [float(to[0]), float(to[1])]
    distance = math.dist(start, destination)
    room_scale = max(0.5, float(room_scale_m))
    relative_distance = distance / (distance + room_scale)
    cruise_speed = 0.82 + 0.48 * relative_distance
    acceleration = 1.35 + 0.65 * relative_distance
    travel_heading = (heading_toward(start, destination)
                      if distance > POSITION_EPSILON_M
                      else float(start_heading_deg) % 360.0)
    arrival_heading = (travel_heading if arrival_heading_deg is None
                       else float(arrival_heading_deg) % 360.0)
    pre_turn = signed_heading_delta(start_heading_deg, travel_heading)
    settle_turn = signed_heading_delta(travel_heading, arrival_heading)
    turn_duration = _turn_time(pre_turn)
    move_duration = _bounded_motion_time(
        distance, cruise_speed, acceleration)
    settle_duration = _turn_time(settle_turn)
    load = distance / (distance + room_scale)
    turn_load = min(1.0, (abs(pre_turn) + abs(settle_turn)) / 180.0)
    return {
        "phase": "committed",
        "start_heading_deg": round(float(start_heading_deg) % 360.0, 6),
        # Coordinates remain the host's exact chosen geometry. Rounded
        # endpoints create a tiny but real snap when one path redirects into
        # the next; metrics below may be bounded for receipts without moving
        # the body.
        "from_m": start,
        "to_m": destination,
        "distance_m": round(distance, 6),
        "travel_heading_deg": round(travel_heading, 6),
        "arrival_heading_deg": round(arrival_heading, 6),
        "pre_turn_deg": round(pre_turn, 6),
        "settle_turn_deg": round(settle_turn, 6),
        "turn_duration_s": round(turn_duration, 6),
        "move_duration_s": round(move_duration, 6),
        "settle_duration_s": round(settle_duration, 6),
        "total_duration_s": round(
            turn_duration + move_duration + settle_duration, 6),
        "cruise_speed_mps": round(cruise_speed, 6),
        "acceleration_mps2": round(acceleration, 6),
        "body_load": round(load, 6),
        "turn_load": round(turn_load, 6),
    }

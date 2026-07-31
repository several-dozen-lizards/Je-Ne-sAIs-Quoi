"""Host-owned, renderer-independent terrain recipes and sampling.

TerrainSurface is geometry truth for an outdoor recipe, not permission for a
renderer to mutate the room.  Godot/Terrain3D may render these samples later;
the host owns the formula, bounds, provenance, and traversability estimate.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from typing import Any


SCHEMA = "jnsq-world-recipe/0.1"
SURFACE_SCHEMA = "jnsq-terrain-surface/0.1"
_FINITE_LIMIT = 1_000_000.0


def _finite(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be numeric") from error
    if not math.isfinite(number) or abs(number) > _FINITE_LIMIT:
        raise ValueError(f"{name} must be finite and bounded")
    return number


def _pair(value: Any, name: str) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{name} must contain two numbers")
    return _finite(value[0], f"{name}[0]"), _finite(value[1], f"{name}[1]")


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _canonical_hash(value: dict) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class WorldRecipe:
    recipe_id: str
    name: str
    stage: str
    provenance: dict
    terrain_surfaces: tuple["TerrainSurface", ...]
    revision_id: str

    @classmethod
    def from_dict(cls, value: dict) -> "WorldRecipe":
        if not isinstance(value, dict) or value.get("schema") != SCHEMA:
            raise ValueError(f"world recipe schema must be {SCHEMA}")
        recipe_id = str(value.get("recipe_id", "")).strip()
        name = str(value.get("name", "")).strip()
        stage = str(value.get("stage", "")).strip()
        if not recipe_id or not name:
            raise ValueError("world recipe needs recipe_id and name")
        if stage not in {"shadow", "candidate", "installed"}:
            raise ValueError("world recipe stage is invalid")
        surfaces_raw = value.get("terrain_surfaces")
        if not isinstance(surfaces_raw, list) or not surfaces_raw:
            raise ValueError("world recipe needs at least one terrain surface")
        surfaces = tuple(TerrainSurface.from_dict(item)
                         for item in surfaces_raw)
        ids = [surface.surface_id for surface in surfaces]
        if len(ids) != len(set(ids)):
            raise ValueError("terrain surface ids must be unique")
        provenance = dict(value.get("provenance") or {})
        return cls(recipe_id=recipe_id, name=name, stage=stage,
                   provenance=provenance, terrain_surfaces=surfaces,
                   revision_id=_canonical_hash(value))

    def summary(self) -> dict:
        return {
            "schema": SCHEMA,
            "recipe_id": self.recipe_id,
            "name": self.name,
            "stage": self.stage,
            "revision_id": self.revision_id,
            "provenance": dict(self.provenance),
            "terrain_surfaces": [
                surface.summary() for surface in self.terrain_surfaces],
        }


@dataclass(frozen=True)
class TerrainSurface:
    surface_id: str
    name: str
    bounds_x: tuple[float, float]
    bounds_z: tuple[float, float]
    sample_step_m: float
    formula: tuple[dict, ...]
    identities: dict
    traversal: dict
    revision_id: str

    @classmethod
    def from_dict(cls, value: dict) -> "TerrainSurface":
        if not isinstance(value, dict) or value.get("schema") != SURFACE_SCHEMA:
            raise ValueError(f"terrain schema must be {SURFACE_SCHEMA}")
        surface_id = str(value.get("surface_id", "")).strip()
        name = str(value.get("name", "")).strip()
        if not surface_id or not name:
            raise ValueError("terrain surface needs surface_id and name")
        bounds = value.get("bounds_m") or {}
        bounds_x = _pair(bounds.get("x"), "bounds_m.x")
        bounds_z = _pair(bounds.get("z"), "bounds_m.z")
        if bounds_x[0] >= bounds_x[1] or bounds_z[0] >= bounds_z[1]:
            raise ValueError("terrain bounds must increase")
        sample_step = _finite(
            value.get("sample_step_m", 1.0), "sample_step_m")
        if not 0.05 <= sample_step <= 10.0:
            raise ValueError("sample_step_m must be between 0.05 and 10")
        formula = value.get("formula")
        if not isinstance(formula, list) or not formula:
            raise ValueError("terrain formula must be a nonempty list")
        normalized = tuple(_validate_term(term) for term in formula)
        identities = dict(value.get("surface_identities") or {})
        required = {"path", "meadow", "stone", "wetland"}
        if set(identities) != required:
            raise ValueError(
                "surface identities must be path, meadow, stone, wetland")
        identities = {
            key: {"traction": _clamp(_finite(
                entry.get("traction"), f"{key}.traction"), 0.0, 1.0)}
            for key, entry in identities.items()}
        traversal = dict(value.get("traversal") or {})
        comfortable = _finite(
            traversal.get("comfortable_slope_deg", 12.0),
            "comfortable_slope_deg")
        limit = _finite(
            traversal.get("limit_slope_deg", 35.0), "limit_slope_deg")
        edge_fade = _finite(
            traversal.get("edge_fade_m", 4.0), "edge_fade_m")
        uncertainty = _finite(
            traversal.get("uncertainty", 0.1), "uncertainty")
        if not 0.0 <= comfortable < limit <= 89.0:
            raise ValueError("slope thresholds must satisfy 0 <= comfort < limit")
        if edge_fade <= 0.0 or not 0.0 <= uncertainty <= 0.5:
            raise ValueError("traversal fade/uncertainty is invalid")
        traversal = {
            "comfortable_slope_deg": comfortable,
            "limit_slope_deg": limit,
            "edge_fade_m": edge_fade,
            "uncertainty": uncertainty,
        }
        return cls(surface_id=surface_id, name=name,
                   bounds_x=bounds_x, bounds_z=bounds_z,
                   sample_step_m=sample_step, formula=normalized,
                   identities=identities, traversal=traversal,
                   revision_id=_canonical_hash(value))

    def in_bounds(self, x_m: float, z_m: float) -> bool:
        return (self.bounds_x[0] <= x_m <= self.bounds_x[1]
                and self.bounds_z[0] <= z_m <= self.bounds_z[1])

    def height(self, x_m: float, z_m: float) -> float:
        x_m = _finite(x_m, "x_m")
        z_m = _finite(z_m, "z_m")
        return sum(_term_height(term, x_m, z_m)
                   for term in self.formula)

    def sample(self, x_m: float, z_m: float) -> dict:
        x_m = _finite(x_m, "x_m")
        z_m = _finite(z_m, "z_m")
        if not self.in_bounds(x_m, z_m):
            return {
                "schema": "jnsq-terrain-sample/0.1",
                "surface_id": self.surface_id,
                "surface_revision_id": self.revision_id,
                "position_m": [x_m, z_m],
                "in_bounds": False,
                "height_m": None,
                "normal": None,
                "slope_deg": None,
                "surface_weights": {},
                "traversability": {
                    "estimated_probability": 0.0,
                    "estimated_range": [0.0, 0.0],
                    "decision": "refused",
                    "reason": "outside authored terrain",
                },
            }
        height = self.height(x_m, z_m)
        normal = self._normal(x_m, z_m)
        slope = math.degrees(math.acos(_clamp(normal[1], -1.0, 1.0)))
        weights = self._surface_weights(x_m, z_m, height, slope)
        traversability = self._traversability(
            x_m, z_m, slope, weights)
        return {
            "schema": "jnsq-terrain-sample/0.1",
            "surface_id": self.surface_id,
            "surface_revision_id": self.revision_id,
            "position_m": [round(x_m, 3), round(z_m, 3)],
            "in_bounds": True,
            "height_m": round(height, 3),
            "normal": [round(component, 4) for component in normal],
            "slope_deg": round(slope, 2),
            "surface_weights": {
                key: round(weight, 4) for key, weight in weights.items()},
            "traversability": traversability,
        }

    def summary(self) -> dict:
        return {
            "schema": SURFACE_SCHEMA,
            "surface_id": self.surface_id,
            "name": self.name,
            "revision_id": self.revision_id,
            "bounds_m": {
                "x": list(self.bounds_x), "z": list(self.bounds_z)},
            "sample_step_m": self.sample_step_m,
            "surface_identities": dict(self.identities),
            "traversal": dict(self.traversal),
            "formula_terms": [
                {"id": term["id"], "kind": term["kind"]}
                for term in self.formula],
            "authority": "room_host",
            "renderer_binding": None,
        }

    def recipe_payload(self) -> dict:
        """Complete renderer input; still carries no installation authority."""
        return {
            **self.summary(),
            "formula": [dict(term) for term in self.formula],
            "render_policy": {
                "authority": "room_host",
                "binding": None,
                "mutation_allowed": False,
            },
        }

    def _normal(self, x_m: float, z_m: float) -> tuple[float, float, float]:
        step = self.sample_step_m
        left_x = max(self.bounds_x[0], x_m - step)
        right_x = min(self.bounds_x[1], x_m + step)
        back_z = max(self.bounds_z[0], z_m - step)
        front_z = min(self.bounds_z[1], z_m + step)
        span_x = max(right_x - left_x, 1e-9)
        span_z = max(front_z - back_z, 1e-9)
        dh_dx = (self.height(right_x, z_m)
                 - self.height(left_x, z_m)) / span_x
        dh_dz = (self.height(x_m, front_z)
                 - self.height(x_m, back_z)) / span_z
        raw = (-dh_dx, 1.0, -dh_dz)
        length = math.sqrt(sum(component * component for component in raw))
        return tuple(component / length for component in raw)

    def _surface_weights(
            self, x_m: float, z_m: float, height: float,
            slope: float) -> dict[str, float]:
        path_influence = 0.0
        for term in self.formula:
            if term["kind"] == "sine_path":
                center = term["z_amplitude_m"] * math.sin(
                    x_m / term["x_scale_m"])
                path_influence = max(path_influence, math.exp(
                    -((z_m - center) ** 2) / term["falloff_m2"]))
        stone = _clamp((slope - 8.0) / 22.0, 0.0, 1.0)
        wetland = _clamp((-height - 0.25) / 3.5, 0.0, 1.0)
        raw = {
            "path": 1.4 * path_influence,
            "stone": stone,
            "wetland": wetland,
            "meadow": max(
                0.05, 1.0 - 0.72 * path_influence
                - 0.65 * stone - 0.7 * wetland),
        }
        total = sum(raw.values())
        return {key: value / total for key, value in raw.items()}

    def _traversability(
            self, x_m: float, z_m: float, slope: float,
            weights: dict[str, float]) -> dict:
        comfort = self.traversal["comfortable_slope_deg"]
        limit = self.traversal["limit_slope_deg"]
        slope_factor = _clamp((limit - slope) / (limit - comfort), 0.0, 1.0)
        edge_distance = min(
            x_m - self.bounds_x[0], self.bounds_x[1] - x_m,
            z_m - self.bounds_z[0], self.bounds_z[1] - z_m)
        edge_factor = _clamp(
            edge_distance / self.traversal["edge_fade_m"], 0.0, 1.0)
        traction = sum(
            weights[key] * self.identities[key]["traction"]
            for key in weights)
        estimate = _clamp(slope_factor * edge_factor * traction, 0.0, 1.0)
        uncertainty = self.traversal["uncertainty"] * (
            0.45 + 0.55 * (1.0 - max(weights.values())))
        low = _clamp(estimate - uncertainty, 0.0, 1.0)
        high = _clamp(estimate + uncertainty, 0.0, 1.0)
        if high < 0.35:
            decision = "refused"
        elif low >= 0.55:
            decision = "admitted"
        else:
            decision = "conditional"
        return {
            "estimated_probability": round(estimate, 4),
            "estimated_range": [round(low, 4), round(high, 4)],
            "decision": decision,
            "factors": {
                "slope": round(slope_factor, 4),
                "edge": round(edge_factor, 4),
                "traction": round(traction, 4),
            },
            "reason": "estimate only; body capability and weather are absent",
        }


def _validate_term(term: Any) -> dict:
    if not isinstance(term, dict):
        raise ValueError("formula terms must be objects")
    result = dict(term)
    term_id = str(result.get("id", "")).strip()
    kind = str(result.get("kind", "")).strip()
    if not term_id:
        raise ValueError("formula term needs an id")
    result["id"] = term_id
    result["kind"] = kind
    if kind == "gaussian":
        result["amplitude_m"] = _finite(
            result.get("amplitude_m"), f"{term_id}.amplitude_m")
        result["center_m"] = _pair(
            result.get("center_m"), f"{term_id}.center_m")
        result["falloff_m2"] = _pair(
            result.get("falloff_m2"), f"{term_id}.falloff_m2")
        if min(result["falloff_m2"]) <= 0:
            raise ValueError(f"{term_id}.falloff_m2 must be positive")
    elif kind == "linear_ridge":
        for name in ("amplitude_m", "z_offset_m", "z_per_x",
                     "cross_falloff_m2", "longitudinal_falloff_m2"):
            result[name] = _finite(result.get(name), f"{term_id}.{name}")
        if result["cross_falloff_m2"] <= 0 \
                or result["longitudinal_falloff_m2"] <= 0:
            raise ValueError(f"{term_id} falloffs must be positive")
    elif kind == "sine_path":
        for name in ("amplitude_m", "z_amplitude_m", "x_scale_m",
                     "falloff_m2"):
            result[name] = _finite(result.get(name), f"{term_id}.{name}")
        if result["x_scale_m"] == 0 or result["falloff_m2"] <= 0:
            raise ValueError(f"{term_id} scale/falloff is invalid")
    elif kind == "coupled_undulation":
        for name in ("amplitude_m", "x_scale_m", "z_scale_m"):
            result[name] = _finite(result.get(name), f"{term_id}.{name}")
        if result["x_scale_m"] == 0 or result["z_scale_m"] == 0:
            raise ValueError(f"{term_id} scales cannot be zero")
    else:
        raise ValueError(f"unsupported terrain formula kind '{kind}'")
    return result


def _term_height(term: dict, x_m: float, z_m: float) -> float:
    kind = term["kind"]
    if kind == "gaussian":
        center_x, center_z = term["center_m"]
        falloff_x, falloff_z = term["falloff_m2"]
        return term["amplitude_m"] * math.exp(
            -(((x_m - center_x) ** 2) / falloff_x
              + ((z_m - center_z) ** 2) / falloff_z))
    if kind == "linear_ridge":
        axis = z_m - (term["z_per_x"] * x_m + term["z_offset_m"])
        return (term["amplitude_m"]
                * math.exp(-(axis ** 2) / term["cross_falloff_m2"])
                * math.exp(-(x_m ** 2)
                           / term["longitudinal_falloff_m2"]))
    if kind == "sine_path":
        center = term["z_amplitude_m"] * math.sin(
            x_m / term["x_scale_m"])
        return term["amplitude_m"] * math.exp(
            -((z_m - center) ** 2) / term["falloff_m2"])
    if kind == "coupled_undulation":
        return (term["amplitude_m"]
                * math.sin(x_m / term["x_scale_m"])
                * math.cos(z_m / term["z_scale_m"]))
    raise AssertionError(f"unvalidated terrain term {kind}")


def load_world_recipe(path: str) -> WorldRecipe:
    with open(path, encoding="utf-8") as handle:
        return WorldRecipe.from_dict(json.load(handle))


def load_world_recipes(root: str) -> tuple[WorldRecipe, ...]:
    if not os.path.isdir(root):
        return ()
    recipes = []
    for name in sorted(os.listdir(root)):
        if name.endswith(".json"):
            recipes.append(load_world_recipe(os.path.join(root, name)))
    return tuple(recipes)

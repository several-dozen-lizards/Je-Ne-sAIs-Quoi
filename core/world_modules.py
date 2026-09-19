"""Portable, inspectable assemblies for JNAIQ world authoring.

A module is a relative arrangement of ordinary room objects.  It owns no live
room state and has no renderer authority: stamping compiles its members back
into the room host's existing validated object-creation contract.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping


SCHEMA = "jnaiq-world-module/0.1"
MAX_MEMBERS = 128


class WorldModuleError(ValueError):
    pass


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
    return slug[:64]


@dataclass(frozen=True)
class WorldModule:
    module_id: str
    name: str
    members: tuple[dict, ...]
    schema: str = SCHEMA

    def as_dict(self) -> dict:
        return {"schema": self.schema, "module_id": self.module_id,
                "name": self.name,
                "members": [dict(member) for member in self.members]}

    @classmethod
    def from_dict(cls, value: Mapping) -> "WorldModule":
        if value.get("schema") != SCHEMA:
            raise WorldModuleError("unsupported world module schema")
        name = str(value.get("name") or "").strip()
        module_id = str(value.get("module_id") or "").strip()
        members = value.get("members")
        if not name or not re.fullmatch(r"[a-z0-9][a-z0-9_]{0,63}",
                                        module_id):
            raise WorldModuleError("world module identity is invalid")
        if not isinstance(members, list) or not 1 <= len(members) <= MAX_MEMBERS:
            raise WorldModuleError(
                f"members must contain 1..{MAX_MEMBERS} objects")
        normalized = []
        for member in members:
            if not isinstance(member, Mapping):
                raise WorldModuleError("each member must be an object")
            try:
                offset = [float(member["offset_m"][0]),
                          float(member["offset_m"][1])]
                size_m = float(member.get("size_m", 0.6))
                rot_deg = float(member.get("rot_deg", 0.0)) % 360.0
                y_off_m = float(member.get("y_off_m", 0.0))
            except (KeyError, TypeError, ValueError, IndexError):
                raise WorldModuleError("member geometry is invalid")
            if not all(math.isfinite(v) for v in
                       (*offset, size_m, rot_deg, y_off_m)):
                raise WorldModuleError("member geometry must be finite")
            if not 0.02 <= size_m <= 6.0 or not -1.0 <= y_off_m <= 3.0:
                raise WorldModuleError("member bounds are invalid")
            member_name = str(member.get("name") or "").strip()
            if not member_name:
                raise WorldModuleError("member name is required")
            normalized.append({
                "name": member_name,
                "source_oid": str(member.get("source_oid") or ""),
                "kind": member.get("kind"),
                "size_m": size_m,
                "offset_m": offset,
                "rot_deg": rot_deg,
                "y_off_m": y_off_m,
                "description": str(member.get("description") or ""),
                "texture": str(member.get("texture") or "neutral"),
                "capability": member.get("capability")})
        return cls(module_id=module_id, name=name,
                   members=tuple(normalized))


def capture_module(name: str, snapshots: Iterable[tuple[str, Mapping]]
                   ) -> WorldModule:
    """Describe snapshots relative to their centroid; do not mutate them."""
    name = str(name or "").strip()
    values = [(str(oid), dict(snapshot)) for oid, snapshot in snapshots]
    if not name:
        raise WorldModuleError("a module name is required")
    if not 1 <= len(values) <= MAX_MEMBERS:
        raise WorldModuleError(f"select 1..{MAX_MEMBERS} objects")
    try:
        center_x = sum(float(v["position_m"][0])
                       for _, v in values) / len(values)
        center_y = sum(float(v["position_m"][1])
                       for _, v in values) / len(values)
    except (KeyError, TypeError, ValueError, IndexError):
        raise WorldModuleError("object positions are invalid")
    members = []
    for oid, snapshot in values:
        member = dict(snapshot)
        pos = member.pop("position_m")
        member["source_oid"] = oid
        member["offset_m"] = [
            round(float(pos[0]) - center_x, 6),
            round(float(pos[1]) - center_y, 6)]
        members.append(member)
    base = _slug(name)
    if not base:
        raise WorldModuleError("module name needs a letter or number")
    digest = hashlib.sha256(json.dumps(
        members, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")).hexdigest()[:10]
    return WorldModule.from_dict({
        "schema": SCHEMA, "module_id": f"{base[:53]}_{digest}",
        "name": name, "members": members})


def compile_stamp(module: WorldModule, anchor_m: list,
                  rot_deg: float = 0.0) -> list[dict]:
    """Resolve relative members into ordinary object-create specifications."""
    try:
        ax, ay = float(anchor_m[0]), float(anchor_m[1])
        yaw = float(rot_deg)
    except (TypeError, ValueError, IndexError):
        raise WorldModuleError("stamp transform is invalid")
    if not all(math.isfinite(v) for v in (ax, ay, yaw)):
        raise WorldModuleError("stamp transform must be finite")
    radians = math.radians(yaw)
    c, s = math.cos(radians), math.sin(radians)
    specs = []
    for member in module.members:
        ox, oy = member["offset_m"]
        spec = {key: member.get(key) for key in (
            "name", "kind", "size_m", "y_off_m", "description",
            "texture", "capability")}
        spec["position_m"] = [
            round(ax + ox * c - oy * s, 6),
            round(ay + ox * s + oy * c, 6)]
        spec["rot_deg"] = (float(member["rot_deg"]) + yaw) % 360.0
        specs.append(spec)
    return specs


def save_module(root: str | os.PathLike, module: WorldModule) -> Path:
    path = Path(root) / f"{module.module_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(module.as_dict(), ensure_ascii=False,
                              indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def load_module(root: str | os.PathLike, module_id: str) -> WorldModule:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_]{0,63}", str(module_id)):
        raise WorldModuleError("world module id is invalid")
    path = Path(root) / f"{module_id}.json"
    try:
        return WorldModule.from_dict(
            json.loads(path.read_text(encoding="utf-8")))
    except OSError as exc:
        raise WorldModuleError("world module does not exist") from exc
    except json.JSONDecodeError as exc:
        raise WorldModuleError("world module JSON is invalid") from exc


def list_modules(root: str | os.PathLike) -> tuple[WorldModule, ...]:
    path = Path(root)
    if not path.is_dir():
        return ()
    modules = []
    for candidate in sorted(path.glob("*.json")):
        try:
            modules.append(WorldModule.from_dict(
                json.loads(candidate.read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError, WorldModuleError):
            continue
    return tuple(modules)

"""Versioned, non-installable recipes for the experimental body builder."""
from __future__ import annotations

import json
import math
import os
import re
import uuid
from datetime import datetime, timezone

from core.body_packages import BodyPackageError


RECIPE_FORMAT = "jnsq-body-recipe/0.3"
COMPATIBLE_RECIPE_FORMATS = {
    RECIPE_FORMAT, "jnsq-body-recipe/0.2", "jnsq-body-recipe/0.1"}
BODY_FAMILY = "jnsq-humanoid-01"
PILOT_TARGET = "starter_persona"
PARAMETERS = (
    "height", "shoulder_width", "hip_width", "torso_length",
    "limb_length", "head_scale", "eye_scale",
)
DEFAULT_PARAMETERS = {
    "height": 0.50,
    "shoulder_width": 0.50,
    "hip_width": 0.50,
    "torso_length": 0.50,
    "limb_length": 0.50,
    "head_scale": 0.50,
    "eye_scale": 0.50,
}
DEFAULT_SURFACE = {
    "body_color": "#69d49a",
    "accent_color": "#c9ffe0",
    "roughness": 0.62,
    "metallic": 0.08,
}
FACE_PARAMETERS = (
    "nose_size",
    "nose_curve",
    "nose_tip_angle",
    "nose_tip_rotation",
    "nostril_angle",
    "nostril_width",
    "nose_projection",
    "nose_vertical",
    "septum_angle",
    "jaw_width",
    "jaw_angle",
    "jaw_projection",
    "jaw_definition",
    "chin_height",
    "chin_projection",
)
DEFAULT_FACE = {key: 0.50 for key in FACE_PARAMETERS}
IDENTITY_PARAMETERS = (
    "kay_head_envelope", "kay_facial_structure",
    "nose_sidewall_width",
    "alar_groove_definition",
    "mouth_projection",
    "outer_lip_width", "upper_lip_border", "lower_lip_border", "cupids_bow_width",
    "lower_chin_width", "lower_chin_projection",
    "eye_socket_depth", "mouth_corner_shape", "forehead_slope", "under_jaw_fullness",
    "jowl_volume", "double_chin_volume", "neck_fullness", "nose_tip_roundness", "lip_taper", "lip_projection",
    "face_neck_fullness",
    "fullness_temples", "fullness_upper_cheeks", "fullness_mouth_sides", "fullness_lower_cheeks", "fullness_jowls", "fullness_chin", "fullness_under_chin", "fullness_neck_sides", "fullness_nape",
    'ear_point', 'ear_tip_angle', 'ear_tip_spread', 'ear_sweep', 'ear_round', 'fangs', 'fangs_protrusion', 'tusks', 'tusks_protrusion', 'horns', 'tail',
    'character_heart', 'character_oval', 'character_square', 'character_fine', 'character_round', 'character_aquiline', 'character_age', 'body_softness', 'body_power',
    "body_adiposity", "fat_upper_abdomen", "fat_lower_abdomen", "fat_waist", "fat_upper_back", "fat_chest", "fat_seat", "fat_outer_thighs", "fat_inner_thighs", "fat_upper_arms", "fat_calves", "fat_belly_hang",
    "body_frame", "stature", "body_mass", "muscularity", "proportions",
    "shoulder_width", "hip_width", "torso_length", "arm_length",
    "leg_length", "head_scale", "jaw_width", "chin_height", "cheekbones", "cheekbone_height",
    "nose_size", "nose_curve", "nose_tip_angle", "nose_tip_rotation", "nostril_angle",
    "nostril_width", "nose_projection", "nose_vertical", "septum_angle",
    "jaw_angle", "jaw_projection", "jaw_definition", "chin_projection",
    "eye_size", "eye_spacing", "mouth_width", "ear_size", "brow_height",
    "brow_inner_horizontal", "brow_inner_vertical",
    "brow_arch_horizontal", "brow_arch_vertical",
    "brow_tail_horizontal", "brow_tail_vertical",
    "breast_size", "hip_depth", "brow_angle", "brow_projection", "brow_width", "brow_arch", "brow_hair_thickness", "brow_hair_length", "philtrum_depth", "nasolabial_definition", "midface_projection",
    "upper_lip_volume", "lower_lip_volume", "cupids_bow", "eye_openness", "eye_tilt", "eye_angle", "inner_eye_fold", "inner_lid_opening", "outer_lid_opening", "outer_lid_height", "mouth_position", "lip_height", "facial_definition", "cheek_volume", "temple_definition", "eyelid_fold", "eyelid_fold_height", "lower_lid_volume", "upper_lip_height", "lower_lip_height", "lower_nose_projection", "nose_bridge_width", "nose_tip_width", "nostril_flare", "jaw_corner",
)
DEFAULT_IDENTITY = {key: 0.50 for key in IDENTITY_PARAMETERS}
DEFAULT_APPEARANCE = {
    'horn_style': 'original',
    'skin_sheen': 0.0,
    'iris_lightness':0.5,
    'brow_color':'#ffffff', 'brow_density':1.0,
    'eye_style':'original','pupil_shape':'round','pupil_width':0.5,'pupil_height':0.5,'iris_size':0.5,'eye_accent':'#8eefff',
    'hair_lightness': 0.0, 'hair_highlight_color': '#d9b878', 'hair_highlight_amount': 0.0, 'hair_highlight_pattern': 'fine',
    'skin': '#ffffff', 'hair': '#ffffff', 'eyes': '#ffffff', 'iris': '#ffffff', 'iris_inner': '#ffffff',
    'skin_texture': '', 'eye_texture': '', 'eye_shading': 0.65,
    'outfit': '#ffffff', 'outfit_top': '#ffffff', 'outfit_bottom': '#ffffff', 'hairstyle': 'short01', 'eyebrows': 'eyebrow009', 'eyelashes': 'lashes_soft_natural', 'beard': 'none',
}

def normalize_appearance(value):
    value = value or {}
    if not isinstance(value, dict) or set(value) - set(DEFAULT_APPEARANCE):
        raise BodyPackageError('Unknown avatar appearance field')
    result = {key: _color(value.get(key, DEFAULT_APPEARANCE[key]), key)
              for key in ['skin', 'hair', 'eyes', 'iris', 'iris_inner', 'outfit', 'outfit_top', 'outfit_bottom']}
    shading = value.get('eye_shading', DEFAULT_APPEARANCE['eye_shading'])
    if isinstance(shading, bool) or not isinstance(shading, (int, float)) or not 0 <= shading <= 1:
        raise BodyPackageError('Eye shading must be between zero and one')
    result['eye_shading'] = float(shading)
    sheen = value.get('skin_sheen', 0.0)
    if isinstance(sheen, bool) or not isinstance(sheen, (int, float)) or not 0 <= sheen <= 1:
        raise BodyPackageError('Skin sheen must be between zero and one')
    result['skin_sheen'] = float(sheen)
    result['brow_color']=_color(value.get('brow_color','#ffffff'),'brow_color')
    density=value.get('brow_density',1.0)
    if isinstance(density,bool) or not isinstance(density,(int,float)) or not 0<=density<=1:
        raise BodyPackageError('Brow density must be between zero and one')
    result['brow_density']=float(density)
    result['eye_style']=value.get('eye_style','original')
    result['horn_style']=value.get('horn_style','original')
    if result['horn_style'] not in ['original','swept','ram','antlers']:
        raise BodyPackageError('Invalid horn style')
    if result['eye_style'] not in ['original','radial','ember','galaxy','rings','crystal','spiral','starburst','void']:
        raise BodyPackageError('Invalid eye style')
    result['pupil_shape']=value.get('pupil_shape','round')
    if result['pupil_shape'] not in ['round','vertical','horizontal','diamond','none']:
        raise BodyPackageError('Invalid pupil shape')
    for key in ['pupil_width','pupil_height','iris_size','iris_lightness']:
        item=value.get(key,.5)
        if isinstance(item,bool) or not isinstance(item,(int,float)) or not 0<=item<=1:
            raise BodyPackageError('Invalid eye proportion')
        result[key]=float(item)
    result['eye_accent']=_color(value.get('eye_accent','#8eefff'),'eye_accent')

    for key in ['hair_lightness','hair_highlight_amount']:
        item=value.get(key,DEFAULT_APPEARANCE[key])
        if isinstance(item,bool) or not isinstance(item,(int,float)) or not 0<=item<=1:
            raise BodyPackageError('Invalid hair finish strength')
        result[key]=float(item)
    result['hair_highlight_color']=_color(value.get('hair_highlight_color',DEFAULT_APPEARANCE['hair_highlight_color']),'hair_highlight_color')
    result['hair_highlight_pattern']=value.get('hair_highlight_pattern','fine')
    if result['hair_highlight_pattern'] not in ['fine','broad','tips']:
        raise BodyPackageError('Invalid hair highlight pattern')
    for key in ['skin_texture', 'eye_texture']:
        item = value.get(key, '')
        if not isinstance(item, str) or (item and not re.fullmatch('[a-f0-9]{64}', item)):
            raise BodyPackageError('Invalid texture identifier')
        result[key] = item
    for key in ['hairstyle', 'eyebrows', 'eyelashes', 'beard']:
        item = value.get(key, DEFAULT_APPEARANCE[key])
        if not isinstance(item, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', item):
            raise BodyPackageError('Invalid accessory name')
        result[key] = item
    return result


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: str, value: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    partial = path + ".partial"
    with open(partial, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(partial, path)


def _name(value) -> str:
    name = re.sub(r"\s+", " ", str(value or "").strip())
    if not name:
        raise BodyPackageError("body recipe requires a name")
    if len(name) > 64:
        raise BodyPackageError("body recipe name exceeds 64 characters")
    return name


def _unit(value, label: str, maximum: float = 1.0) -> float:
    if isinstance(value, bool):
        raise BodyPackageError(f"{label} must be a number from 0 to {maximum:g}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise BodyPackageError(
            f"{label} must be a number from 0 to {maximum:g}") from exc
    if not math.isfinite(number) or not 0.0 <= number <= maximum:
        raise BodyPackageError(f"{label} must be a number from 0 to {maximum:g}")
    return round(number, 5)


def _color(value, label: str) -> str:
    color = str(value or "").lower()
    if not re.fullmatch(r"#[0-9a-f]{6}", color):
        raise BodyPackageError(f"{label} must be a six-digit hex color")
    return color


def _candidate_source(value) -> dict | None:
    if value in (None, {}):
        return None
    if not isinstance(value, dict):
        raise BodyPackageError("source candidate must be an object")
    unknown = sorted(set(value) - {"candidate_id", "sha256", "original_name"})
    if unknown:
        raise BodyPackageError(
            f"unknown source candidate field: {unknown[0]}")
    candidate_id = str(value.get("candidate_id") or "")
    digest = str(value.get("sha256") or "").lower()
    original_name = os.path.basename(str(value.get("original_name") or ""))
    if not re.fullmatch(r"[0-9a-f]{32}", candidate_id):
        raise BodyPackageError("source candidate id is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise BodyPackageError("source candidate sha256 is invalid")
    if (not original_name.casefold().endswith(".glb")
            or len(original_name) > 128):
        raise BodyPackageError("source candidate name is invalid")
    return {
        "candidate_id": candidate_id,
        "sha256": digest,
        "original_name": original_name,
    }


def normalize_recipe(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise BodyPackageError("body recipe must be an object")
    if payload.get("body_family", BODY_FAMILY) != BODY_FAMILY:
        raise BodyPackageError("body recipe uses an unavailable body family")
    if payload.get("pilot_target", PILOT_TARGET) != PILOT_TARGET:
        raise BodyPackageError("body recipes are currently Testy-only")
    supplied = payload.get("parameters") or {}
    if not isinstance(supplied, dict):
        raise BodyPackageError("body recipe parameters must be an object")
    unknown = sorted(set(supplied) - set(PARAMETERS))
    if unknown:
        raise BodyPackageError(
            f"unknown body recipe parameter: {unknown[0]}")
    parameters = {
        key: _unit(supplied.get(key, DEFAULT_PARAMETERS[key]), key)
        for key in PARAMETERS
    }
    surface_in = payload.get("surface") or {}
    if not isinstance(surface_in, dict):
        raise BodyPackageError("body recipe surface must be an object")
    unknown_surface = sorted(
        set(surface_in) - {"body_color", "accent_color",
                           "roughness", "metallic"})
    if unknown_surface:
        raise BodyPackageError(
            f"unknown body surface parameter: {unknown_surface[0]}")
    surface = {
        "body_color": _color(
            surface_in.get("body_color", DEFAULT_SURFACE["body_color"]),
            "body color"),
        "accent_color": _color(
            surface_in.get("accent_color", DEFAULT_SURFACE["accent_color"]),
            "accent color"),
        "roughness": _unit(
            surface_in.get("roughness", DEFAULT_SURFACE["roughness"]),
            "roughness"),
        "metallic": _unit(
            surface_in.get("metallic", DEFAULT_SURFACE["metallic"]),
            "metallic"),
    }
    face_in = payload.get("face") or {}
    if not isinstance(face_in, dict):
        raise BodyPackageError("body recipe face must be an object")
    unknown_face = sorted(set(face_in) - set(FACE_PARAMETERS))
    if unknown_face:
        raise BodyPackageError(
            f"unknown face parameter: {unknown_face[0]}")
    face = {
        key: _unit(face_in.get(key, DEFAULT_FACE[key]), key)
        for key in FACE_PARAMETERS
    }
    identity_in = payload.get("identity") or {}
    if not isinstance(identity_in, dict):
        raise BodyPackageError("body recipe identity must be an object")
    unknown_identity = sorted(
        set(identity_in) - set(IDENTITY_PARAMETERS))
    if unknown_identity:
        raise BodyPackageError(
            f"unknown identity parameter: {unknown_identity[0]}")
    identity = {
        key: _unit(identity_in.get(key, DEFAULT_IDENTITY[key]), key, 1.25 if key == 'lower_nose_projection' else 1.0)
        for key in IDENTITY_PARAMETERS
    }
    return {
        "name": _name(payload.get("name")),
        "body_family": BODY_FAMILY,
        "pilot_target": PILOT_TARGET,
        "parameters": parameters,
        "face": face,
        "identity": identity,
        "source_candidate": _candidate_source(
            payload.get("source_candidate")),
        "surface": surface,
        "appearance": normalize_appearance(payload.get('appearance')),
    }


def _recipe_dir(root: str, recipe_id: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{32}", str(recipe_id or "")):
        raise BodyPackageError("invalid body recipe id")
    return os.path.join(os.path.realpath(root), recipe_id)


def save_recipe(root: str, payload: dict, recipe_id: str | None = None) -> dict:
    normalized = normalize_recipe(payload)
    recipe_id = recipe_id or uuid.uuid4().hex
    directory = _recipe_dir(root, recipe_id)
    current_path = os.path.join(directory, "current.json")
    if recipe_id and os.path.isfile(current_path):
        with open(current_path, encoding="utf-8") as handle:
            previous = json.load(handle)
        if previous.get("pilot_target") != PILOT_TARGET:
            raise BodyPackageError("body recipe belongs to another pilot")
        created_at = previous.get("created_at") or _now()
    else:
        created_at = _now()
    revision_id = uuid.uuid4().hex
    record = {
        "schema": RECIPE_FORMAT,
        "recipe_id": recipe_id,
        "revision_id": revision_id,
        **normalized,
        "created_at": created_at,
        "updated_at": _now(),
        "capabilities": {
            "proportions": "full",
            "surface": "full",
            "face": "detailed-vector-preview",
            "identity": "mpfb-morph-vector",
            "expressions": "unavailable",
            "wardrobe": "unavailable",
        },
        "install_enabled": False,
        "current_assignments_mutable": False,
    }
    revision_path = os.path.join(directory, "revisions",
                                 f"{revision_id}.json")
    if os.path.exists(revision_path):
        raise BodyPackageError("body recipe revision collision")
    _atomic_json(revision_path, record)
    _atomic_json(current_path, record)
    return record


def load_recipe(root: str, recipe_id: str) -> dict:
    path = os.path.join(_recipe_dir(root, recipe_id), "current.json")
    try:
        with open(path, encoding="utf-8") as handle:
            record = json.load(handle)
    except (OSError, ValueError) as exc:
        raise BodyPackageError("body recipe is unavailable") from exc
    if (record.get("schema") not in COMPATIBLE_RECIPE_FORMATS
            or record.get("pilot_target") != PILOT_TARGET
            or record.get("install_enabled") is not False):
        raise BodyPackageError("body recipe authority is invalid")
    # Old sealed bench recipes remain readable and acquire a compatible MPFB
    # vector in memory; their immutable revision files are never rewritten.
    if record.get("schema") != RECIPE_FORMAT:
        record = dict(record)
        face = dict(DEFAULT_FACE)
        face.update(record.get("face") or {})
        record["face"] = face
        parameters = record.get("parameters") or {}
        identity = dict(DEFAULT_IDENTITY)
        identity.update({
            "stature": parameters.get("height", 0.5),
            "shoulder_width": parameters.get("shoulder_width", 0.5),
            "hip_width": parameters.get("hip_width", 0.5),
            "torso_length": parameters.get("torso_length", 0.5),
            "arm_length": parameters.get("limb_length", 0.5),
            "leg_length": parameters.get("limb_length", 0.5),
            "head_scale": parameters.get("head_scale", 0.5),
            "eye_size": parameters.get("eye_scale", 0.5),
        })
        for key in FACE_PARAMETERS:
            if key in identity:
                identity[key] = face[key]
        record["identity"] = identity
        record["source_candidate"] = None
    return record


def list_recipes(root: str) -> list[dict]:
    root = os.path.realpath(root)
    try:
        ids = sorted(os.listdir(root))
    except OSError:
        return []
    records = []
    for recipe_id in ids:
        try:
            records.append(load_recipe(root, recipe_id))
        except BodyPackageError:
            continue
    return sorted(records, key=lambda item: item["updated_at"], reverse=True)


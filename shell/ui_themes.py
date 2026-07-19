"""Persisted UI themes for the Je Ne Sais Quoi and persona cockpits.

Inheritance is explicit and one-way:
  built-in preset -> household -> persona -> model
  built-in preset -> household -> Nexus

The browser may add accessibility-only overrides (contrast, motion, scale)
without writing them into a persona. Theme files are descriptive display
preferences; they never feed emotional state back into the model.
"""
from copy import deepcopy
import json
import os
import re


PRESETS = {
    "bal_masque": {
        "label": "Bal masqué",
        "tokens": {
            "bg": "#0b0a15", "panel": "#131120", "line": "#2c2740",
            "ink": "#eae3d2", "dim": "#8b829d", "accent": "#c9ab77",
            "accent2": "#f6ead0", "warn": "#d97b6c", "good": "#84b98f",
            "background": "stars", "font": "serif", "density": "cozy",
            "radius": 16, "font_scale": 1.0, "glow": 0.45, "motion": 0.50,
            "reactive": True,
            "speaker_colors": {"User": "#76a9d4"},
            "speaker_icons": {"User": "U"},
        },
    },
    "masquerade": {
        "label": "Cosmic masquerade",
        "tokens": {
            "bg": "#0d0b09", "panel": "#161210", "line": "#3b3226",
            "ink": "#e9dfc8", "dim": "#9c8e73", "accent": "#4fa893",
            "accent2": "#d9b877", "warn": "#c96f5e", "good": "#79b58f",
            "background": "stars", "font": "serif", "density": "cozy",
            "radius": 6, "font_scale": 1.0, "glow": 0.30, "motion": 0.45,
            "reactive": True,
            "speaker_colors": {"User": "#76a9d4"},
            "speaker_icons": {"User": "U"},
        },
    },
    "laboratory": {
        "label": "Dark laboratory",
        "tokens": {
            "bg": "#10151a", "panel": "#161e26", "line": "#24303c",
            "ink": "#cfdce6", "dim": "#7b8da0", "accent": "#37c2b4",
            "accent2": "#d9a441", "warn": "#d96941", "good": "#5fae6e",
            "background": "grid", "font": "system", "density": "cozy",
            "radius": 10, "font_scale": 1.0, "glow": 0.35, "motion": 0.55,
            "reactive": True,
            "speaker_colors": {"User": "#5ba7d9"},
            "speaker_icons": {"User": "U"},
        },
    },
    "serpent": {
        "label": "Serpent iridescence",
        "tokens": {
            "bg": "#07110f", "panel": "#0d1b19", "line": "#21443d",
            "ink": "#d8f2e9", "dim": "#779f94", "accent": "#44e0b2",
            "accent2": "#b985ff", "warn": "#ff776d", "good": "#78e38e",
            "background": "scales", "font": "system", "density": "cozy",
            "radius": 14, "font_scale": 1.0, "glow": 0.62, "motion": 0.70,
            "reactive": True,
            "speaker_colors": {"User": "#71b7ff"},
            "speaker_icons": {"User": "U"},
        },
    },
    "hearth": {
        "label": "Household hearth",
        "tokens": {
            "bg": "#1a120e", "panel": "#271b15", "line": "#493226",
            "ink": "#f2dfc7", "dim": "#ad8d73", "accent": "#e89a55",
            "accent2": "#d9c06c", "warn": "#df6b57", "good": "#88b96f",
            "background": "paper", "font": "serif", "density": "roomy",
            "radius": 12, "font_scale": 1.0, "glow": 0.42, "motion": 0.34,
            "reactive": True,
            "speaker_colors": {"User": "#76a9d4"},
            "speaker_icons": {"User": "U"},
        },
    },
    "nocturne": {
        "label": "Deep-space nocturne",
        "tokens": {
            "bg": "#08091a", "panel": "#11132a", "line": "#292d58",
            "ink": "#e1e4ff", "dim": "#858bb8", "accent": "#7c8cff",
            "accent2": "#d480ff", "warn": "#ff728a", "good": "#66d7b0",
            "background": "stars", "font": "system", "density": "cozy",
            "radius": 16, "font_scale": 1.0, "glow": 0.72, "motion": 0.48,
            "reactive": True,
            "speaker_colors": {"User": "#62b6ff"},
            "speaker_icons": {"User": "U"},
        },
    },
    "daylight": {
        "label": "Soft daylight",
        "tokens": {
            "bg": "#e9edf0", "panel": "#f8fafb", "line": "#c6d0d8",
            "ink": "#25313a", "dim": "#647784", "accent": "#087f78",
            "accent2": "#9a6820", "warn": "#b84732", "good": "#3f7f4c",
            "background": "aurora", "font": "system", "density": "cozy",
            "radius": 10, "font_scale": 1.0, "glow": 0.20, "motion": 0.28,
            "reactive": True,
            "speaker_colors": {"User": "#287bb2"},
            "speaker_icons": {"User": "U"},
        },
    },
    "moonstone": {
        "label": "Moonstone tide",
        "tokens": {
            "bg": "#09111d", "panel": "#111d2c", "line": "#2c4963",
            "ink": "#e3eef5", "dim": "#8aa2b5", "accent": "#78b9d4",
            "accent2": "#c5b8f4", "warn": "#df7f82", "good": "#75c7ad",
            "background": "aurora", "font": "humanist", "density": "cozy",
            "radius": 18, "font_scale": 1.0, "glow": 0.48, "motion": 0.38,
            "reactive": True,
            "speaker_colors": {"User": "#78b9d4"},
            "speaker_icons": {"User": "U"},
        },
    },
    "emberglass": {
        "label": "Emberglass",
        "tokens": {
            "bg": "#120d0c", "panel": "#211614", "line": "#57342b",
            "ink": "#f3e5d8", "dim": "#ad8a7c", "accent": "#f08a58",
            "accent2": "#efc56f", "warn": "#f06d67", "good": "#8bc07b",
            "background": "grid", "font": "geometric", "density": "compact",
            "radius": 8, "font_scale": 1.0, "glow": 0.58, "motion": 0.24,
            "reactive": True,
            "speaker_colors": {"User": "#79b7e3"},
            "speaker_icons": {"User": "U"},
        },
    },
    "night_garden": {
        "label": "Night garden",
        "tokens": {
            "bg": "#08110d", "panel": "#101c17", "line": "#29483a",
            "ink": "#dfece4", "dim": "#829d8c", "accent": "#80bf8b",
            "accent2": "#b798db", "warn": "#d97a72", "good": "#68c99b",
            "background": "paper", "font": "rounded", "density": "roomy",
            "radius": 20, "font_scale": 1.0, "glow": 0.44, "motion": 0.18,
            "reactive": True,
            "speaker_colors": {"User": "#75b5dc"},
            "speaker_icons": {"User": "U"},
        },
    },
    "vellum": {
        "label": "Sunlit vellum",
        "tokens": {
            "bg": "#e8dfcd", "panel": "#f6efdf", "line": "#b9a889",
            "ink": "#302a22", "dim": "#706654", "accent": "#8d6035",
            "accent2": "#416f68", "warn": "#a7443b", "good": "#4e7548",
            "background": "paper", "font": "serif", "density": "roomy",
            "radius": 6, "font_scale": 1.05, "glow": 0.12, "motion": 0.0,
            "reactive": True,
            "speaker_colors": {"User": "#376f99"},
            "speaker_icons": {"User": "U"},
        },
    },
    "blood_rose": {
        "label": "Blood-rose gothic",
        "tokens": {
            "bg": "#050405", "panel": "#14090b", "line": "#521923",
            "ink": "#f3e5e1", "dim": "#a98284", "accent": "#d42f49",
            "accent2": "#f0a0a8", "warn": "#ff5266", "good": "#739b78",
            "background": "scales", "font": "display", "density": "cozy",
            "radius": 4, "font_scale": 1.0, "glow": 0.64, "motion": 0.32,
            "reactive": True,
            "speaker_colors": {"User": "#e07181"},
            "speaker_icons": {"User": "U"},
        },
    },
    "violet_crypt": {
        "label": "Violet crypt",
        "tokens": {
            "bg": "#050308", "panel": "#130a1a", "line": "#48205d",
            "ink": "#f0e6f5", "dim": "#9e83aa", "accent": "#9e47e8",
            "accent2": "#dfa8ff", "warn": "#e45d82", "good": "#70a889",
            "background": "stars", "font": "display", "density": "cozy",
            "radius": 6, "font_scale": 1.0, "glow": 0.72, "motion": 0.38,
            "reactive": True,
            "speaker_colors": {"User": "#a992ff"},
            "speaker_icons": {"User": "U"},
        },
    },
    "neon_pop": {
        "label": "Neon pop-art",
        "tokens": {
            "bg": "#ed0aa8", "panel": "#111111", "line": "#fff34f",
            "ink": "#ffffff", "dim": "#ffd1ef", "accent": "#00ead4",
            "accent2": "#fff34f", "warn": "#ff7040", "good": "#42f5a7",
            "background": "grid", "font": "geometric", "density": "compact",
            "radius": 2, "font_scale": 1.05, "glow": 0.34, "motion": 0.64,
            "reactive": True,
            "speaker_colors": {"User": "#0057ff"},
            "speaker_icons": {"User": "U"},
        },
    },
    "tropical": {
        "label": "Tropical voltage",
        "tokens": {
            "bg": "#063f48", "panel": "#0b5960", "line": "#2bb9a8",
            "ink": "#fff5d6", "dim": "#a5d8c8", "accent": "#ffcb45",
            "accent2": "#ff6f91", "warn": "#ff704d", "good": "#60db87",
            "background": "aurora", "font": "rounded", "density": "roomy",
            "radius": 20, "font_scale": 1.0, "glow": 0.56, "motion": 0.58,
            "reactive": True,
            "speaker_colors": {"User": "#70cfff"},
            "speaker_icons": {"User": "U"},
        },
    },
    "winter": {
        "label": "Winter hush",
        "tokens": {
            "bg": "#e9f2f7", "panel": "#f9fcff", "line": "#aac5d5",
            "ink": "#213744", "dim": "#667f8e", "accent": "#477fa8",
            "accent2": "#8871b0", "warn": "#b85b68", "good": "#4f8a73",
            "background": "aurora", "font": "humanist", "density": "roomy",
            "radius": 18, "font_scale": 1.0, "glow": 0.18, "motion": 0.16,
            "reactive": True,
            "speaker_colors": {"User": "#477fa8"},
            "speaker_icons": {"User": "U"},
        },
    },
    "verdant": {
        "label": "Verdant canopy",
        "tokens": {
            "bg": "#dcefd7", "panel": "#f3f8e9", "line": "#83ad73",
            "ink": "#193820", "dim": "#58745b", "accent": "#2f8b45",
            "accent2": "#9a681f", "warn": "#b34f3d", "good": "#24753b",
            "background": "scales", "font": "rounded", "density": "roomy",
            "radius": 16, "font_scale": 1.0, "glow": 0.24, "motion": 0.24,
            "reactive": True,
            "speaker_colors": {"User": "#397fa6"},
            "speaker_icons": {"User": "U"},
        },
    },
    "blush_femme": {
        "label": "Soft femme blush",
        "tokens": {
            "bg": "#f7dfe8", "panel": "#fff4f8", "line": "#dcaec0",
            "ink": "#4a2939", "dim": "#916a7c", "accent": "#b65380",
            "accent2": "#79598d", "warn": "#c65163", "good": "#5f8b74",
            "background": "paper", "font": "serif", "density": "roomy",
            "radius": 22, "font_scale": 1.05, "glow": 0.28, "motion": 0.12,
            "reactive": True,
            "speaker_colors": {"User": "#617fa6"},
            "speaker_icons": {"User": "U"},
        },
    },
    "hot_pink_noir": {
        "label": "Hot-pink noir",
        "tokens": {
            "bg": "#050505", "panel": "#101010", "line": "#f3f3f3",
            "ink": "#ffffff", "dim": "#aaaaaa", "accent": "#ff1493",
            "accent2": "#ffffff", "warn": "#ff4d77", "good": "#5ee6a8",
            "background": "none", "font": "geometric", "density": "compact",
            "radius": 0, "font_scale": 1.0, "glow": 0.52, "motion": 0.0,
            "reactive": True,
            "speaker_colors": {"User": "#0078d7"},
            "speaker_icons": {"User": "U"},
        },
    },
    "contrast": {
        "label": "High contrast",
        "tokens": {
            "bg": "#000000", "panel": "#090909", "line": "#ffffff",
            "ink": "#ffffff", "dim": "#d0d0d0", "accent": "#00ffd5",
            "accent2": "#ffe600", "warn": "#ff6b6b", "good": "#74ff7d",
            "background": "none", "font": "mono", "density": "compact",
            "radius": 4, "font_scale": 1.0, "glow": 0.12, "motion": 0.0,
            "reactive": False,
            "speaker_colors": {"User": "#55c7ff"},
            "speaker_icons": {"User": "U"},
        },
    },
}

DEFAULT_PRESET = "bal_masque"
CUSTOM_PRESETS_FILE = "custom_presets.json"
NEXUS_THEME_FILE = "nexus_theme.json"
NEXUS_PROTECTED_TOKENS = {"speaker_colors", "speaker_icons"}
COLOR_KEYS = {"bg", "panel", "line", "ink", "dim", "accent",
              "accent2", "warn", "good"}
ENUMS = {
    "background": {"none", "grid", "scales", "aurora", "stars", "paper",
                   "image"},
    "conversation_area_background": {"none", "image"},
    "font": {"system", "serif", "display", "mono", "humanist",
             "rounded", "geometric"},
    "density": {"compact", "cozy", "roomy"},
}
NUMBERS = {"radius": (0, 28), "font_scale": (0.8, 1.35),
           "glow": (0.0, 1.0), "motion": (0.0, 1.0),
           "background_opacity": (0.0, 1.0),
           "conversation_area_opacity": (0.0, 1.0)}
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _merge(base: dict, overlay: dict) -> dict:
    out = deepcopy(base)
    for key, value in (overlay or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = deepcopy(value)
    return out


def _with_defaults(tokens: dict) -> dict:
    out = deepcopy(tokens or {})
    out.setdefault("background_opacity", 0.32)
    out.setdefault("conversation_area_background", "none")
    out.setdefault("conversation_area_opacity", 0.28)
    return out


def _clean_tokens(tokens: dict) -> dict:
    if not isinstance(tokens, dict):
        raise ValueError("theme tokens must be an object")
    clean = {}
    for key, value in tokens.items():
        if key in COLOR_KEYS:
            if not isinstance(value, str) or not HEX.match(value):
                raise ValueError(f"theme color '{key}' must be #RRGGBB")
            clean[key] = value.lower()
        elif key in ENUMS:
            if value not in ENUMS[key]:
                raise ValueError(f"theme {key} must be one of {sorted(ENUMS[key])}")
            clean[key] = value
        elif key in NUMBERS:
            lo, hi = NUMBERS[key]
            try:
                number = float(value)
            except (TypeError, ValueError):
                raise ValueError(f"theme {key} must be numeric")
            clean[key] = round(max(lo, min(hi, number)), 3)
        elif key == "reactive":
            clean[key] = bool(value)
        elif key == "speaker_colors":
            if not isinstance(value, dict) or len(value) > 64:
                raise ValueError("speaker_colors must be a small object")
            clean[key] = {}
            for name, color in value.items():
                if not isinstance(name, str) or not name.strip() or len(name) > 80:
                    raise ValueError("speaker color names must be 1-80 characters")
                if not isinstance(color, str) or not HEX.match(color):
                    raise ValueError(f"speaker color for '{name}' must be #RRGGBB")
                clean[key][name.strip()] = color.lower()
        elif key == "speaker_icons":
            if not isinstance(value, dict) or len(value) > 64:
                raise ValueError("speaker_icons must be a small object")
            clean[key] = {}
            for name, icon in value.items():
                if not isinstance(name, str) or not name.strip() or len(name) > 80:
                    raise ValueError("speaker icon names must be 1-80 characters")
                if not isinstance(icon, str) or len(icon) > 16:
                    raise ValueError(f"speaker icon for '{name}' is too long")
                clean[key][name.strip()] = icon
        else:
            raise ValueError(f"unknown theme token '{key}'")
    return clean


def clean_patch(patch: dict, preset_ids=None) -> dict:
    if not isinstance(patch, dict):
        raise ValueError("theme patch must be an object")
    unknown = set(patch) - {"preset", "tokens"}
    if unknown:
        raise ValueError(f"unknown theme field(s): {sorted(unknown)}")
    out = {}
    if "preset" in patch:
        allowed = set(preset_ids or PRESETS)
        if patch["preset"] not in allowed:
            raise ValueError(f"unknown theme preset '{patch['preset']}'")
        out["preset"] = patch["preset"]
    if "tokens" in patch:
        out["tokens"] = _clean_tokens(patch["tokens"])
    return out


def _load(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            value = json.load(f)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _paths(repo: str, persona: str = None):
    household = os.path.join(repo, "shell", "ui", "household_theme.json")
    person = (os.path.join(repo, "personas", persona, "ui", "theme.json")
              if persona else None)
    return household, person


def _custom_presets_path(repo: str) -> str:
    return os.path.join(repo, "shell", "ui", CUSTOM_PRESETS_FILE)


def _nexus_theme_path(repo: str) -> str:
    return os.path.join(repo, "room", "ui", NEXUS_THEME_FILE)


def _custom_presets(repo: str) -> dict:
    """Load only valid local presets; a damaged entry cannot poison themes."""
    raw = (_load(_custom_presets_path(repo)).get("presets") or {})
    clean = {}
    for preset_id, value in raw.items():
        try:
            if (not isinstance(preset_id, str) or preset_id in PRESETS
                    or not isinstance(value, dict)):
                continue
            label = str(value.get("label") or preset_id).strip()[:80]
            if not label:
                continue
            clean[preset_id] = {"label": label,
                                "tokens": _clean_tokens(value.get("tokens") or {})}
        except ValueError:
            continue
    return clean


def _all_presets(repo: str) -> dict:
    return {**deepcopy(PRESETS), **_custom_presets(repo)}


def _preset_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (value or "").strip().lower()).strip("_")
    if not slug:
        raise ValueError("preset name must contain a letter or number")
    return "custom_" + slug[:56]


def save_custom_preset(repo: str, *, preset_id: str = "", label: str,
                       tokens: dict) -> dict:
    """Create or edit one household-local appearance preset."""
    clean_label = (label or "").strip()
    if not clean_label or len(clean_label) > 80:
        raise ValueError("preset name must be 1-80 characters")
    pid = (preset_id or "").strip() or _preset_slug(clean_label)
    if pid in PRESETS:
        raise ValueError("built-in presets cannot be overwritten")
    if not re.fullmatch(r"custom_[a-z0-9_]{1,56}", pid):
        raise ValueError("custom preset id is invalid")
    custom = _custom_presets(repo)
    custom[pid] = {"label": clean_label, "tokens": _clean_tokens(tokens)}
    _atomic_json(_custom_presets_path(repo), {"presets": custom})
    result = resolve_theme(repo)
    result["saved_preset"] = pid
    return result


def delete_custom_preset(repo: str, preset_id: str) -> dict:
    if preset_id in PRESETS:
        raise ValueError("built-in presets cannot be deleted")
    custom = _custom_presets(repo)
    if preset_id not in custom:
        raise KeyError(f"no custom preset '{preset_id}'")
    custom.pop(preset_id)
    _atomic_json(_custom_presets_path(repo), {"presets": custom})
    household_path, _ = _paths(repo)
    household = _load(household_path)
    if household.get("preset") == preset_id:
        household["preset"] = DEFAULT_PRESET
        _atomic_json(household_path, household)
    nexus_path = _nexus_theme_path(repo)
    nexus = _load(nexus_path)
    if nexus.get("preset") == preset_id:
        nexus.pop("preset", None)
        _atomic_json(nexus_path, nexus)
    return resolve_theme(repo)


def resolve_theme(repo: str, persona: str = None, model: str = None) -> dict:
    presets = _all_presets(repo)
    household_path, person_path = _paths(repo, persona)
    household = _load(household_path)
    person_doc = _load(person_path) if person_path else {}
    persona_patch = {k: v for k, v in person_doc.items() if k != "models"}
    model_patch = ((person_doc.get("models") or {}).get(model) or {}
                   if model else {})
    layers = [household, persona_patch, model_patch]
    preset = DEFAULT_PRESET
    for layer in layers:
        if layer.get("preset") in presets:
            preset = layer["preset"]
    tokens = deepcopy(presets[preset]["tokens"])
    for layer in layers:
        tokens = _merge(tokens, layer.get("tokens") or {})
    tokens = _clean_tokens(_with_defaults(tokens))
    return {
        "preset": preset,
        "tokens": tokens,
        "layers": {"household": household, "persona": persona_patch,
                   "model": model_patch},
        "presets": {key: value["label"] for key, value in presets.items()},
        "preset_tokens": {key: _with_defaults(value["tokens"])
                          for key, value in presets.items()},
        "custom_presets": sorted(_custom_presets(repo)),
        "persona": persona, "model": model,
    }


def resolve_nexus_theme(repo: str) -> dict:
    """Resolve the shared room's own visual layer over household appearance.

    Speaker colors and icons describe people rather than the room. They always
    flow through from household truth, even when the Nexus chooses a different
    preset for its walls.
    """
    presets = _all_presets(repo)
    household = resolve_theme(repo)
    nexus = _load(_nexus_theme_path(repo))
    nexus_preset = nexus.get("preset")
    preset = (nexus_preset if nexus_preset in presets else
              household["preset"])
    if nexus_preset in presets:
        tokens = deepcopy(presets[preset]["tokens"])
        for key in NEXUS_PROTECTED_TOKENS:
            if key in household["tokens"]:
                tokens[key] = deepcopy(household["tokens"][key])
    else:
        tokens = deepcopy(household["tokens"])
    nexus_tokens = {key: value for key, value in
                    (nexus.get("tokens") or {}).items()
                    if key not in NEXUS_PROTECTED_TOKENS}
    tokens = _merge(tokens, nexus_tokens)
    tokens = _clean_tokens(_with_defaults(tokens))
    return {
        "preset": preset,
        "tokens": tokens,
        "layers": {"household": household["layers"]["household"],
                   "nexus": nexus},
        "presets": {key: value["label"] for key, value in presets.items()},
        "preset_tokens": {key: _with_defaults(value["tokens"])
                          for key, value in presets.items()},
        "custom_presets": sorted(_custom_presets(repo)),
        "surface": "nexus",
    }


def _atomic_json(path: str, value: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            previous = f.read()
        with open(path + ".prev", "w", encoding="utf-8") as f:
            f.write(previous)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def _merge_patch(existing: dict, clean: dict) -> dict:
    """Merge a sparse editor save without freezing inherited values."""
    out = {k: deepcopy(v) for k, v in (existing or {}).items()
           if k in {"preset", "tokens"}}
    if "preset" in clean:
        out["preset"] = clean["preset"]
    if "tokens" in clean:
        out["tokens"] = _merge(out.get("tokens") or {}, clean["tokens"])
    return out


def save_theme(repo: str, scope: str, patch: dict, *,
               persona: str = None, model: str = None,
               reset: bool = False, replace: bool = False) -> dict:
    """Persist one inheritance layer and return the newly resolved theme."""
    if scope not in {"household", "persona", "model"}:
        raise ValueError("theme scope must be household, persona, or model")
    if scope in {"persona", "model"} and not persona:
        raise ValueError(f"theme scope '{scope}' needs a persona")
    if scope == "model" and not model:
        raise ValueError("model theme scope needs a model")
    clean = {} if reset else clean_patch(patch, _all_presets(repo))
    household_path, person_path = _paths(repo, persona)

    if scope == "household":
        current = _load(household_path)
        value = clean if (reset or replace) else _merge_patch(current, clean)
        _atomic_json(household_path, value)
    elif scope == "persona":
        current = _load(person_path)
        models = current.get("models") or {}
        old_patch = {k: v for k, v in current.items() if k != "models"}
        doc = dict(clean if (reset or replace)
                   else _merge_patch(old_patch, clean))
        if models:
            doc["models"] = models
        _atomic_json(person_path, doc)
    else:
        current = _load(person_path)
        models = dict(current.get("models") or {})
        if reset:
            models.pop(model, None)
        else:
            models[model] = (clean if replace else
                             _merge_patch(models.get(model) or {}, clean))
        current["models"] = models
        _atomic_json(person_path, current)
    return resolve_theme(repo, persona, model)


def save_nexus_theme(repo: str, patch: dict, *, reset: bool = False,
                     replace: bool = False) -> dict:
    """Persist sparse Nexus-only display preferences."""
    clean = {} if reset else clean_patch(patch, _all_presets(repo))
    if "tokens" in clean:
        clean["tokens"] = {key: value for key, value in
                           clean["tokens"].items()
                           if key not in NEXUS_PROTECTED_TOKENS}
    path = _nexus_theme_path(repo)
    current = _load(path)
    value = clean if (reset or replace) else _merge_patch(current, clean)
    _atomic_json(path, value)
    return resolve_nexus_theme(repo)

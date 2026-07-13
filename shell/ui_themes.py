"""Persisted UI themes for the Je Ne sAIs Quoi and persona cockpits.

Inheritance is explicit and one-way:
  built-in preset -> household -> persona -> model

The browser may add accessibility-only overrides (contrast, motion, scale)
without writing them into a persona. Theme files are descriptive display
preferences; they never feed emotional state back into the model.
"""
from copy import deepcopy
import json
import os
import re


PRESETS = {
    "laboratory": {
        "label": "Dark laboratory",
        "tokens": {
            "bg": "#10151a", "panel": "#161e26", "line": "#24303c",
            "ink": "#cfdce6", "dim": "#7b8da0", "accent": "#37c2b4",
            "accent2": "#d9a441", "warn": "#d96941", "good": "#5fae6e",
            "background": "grid", "font": "system", "density": "cozy",
            "radius": 10, "glow": 0.35, "motion": 0.55,
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
            "radius": 14, "glow": 0.62, "motion": 0.70,
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
            "radius": 12, "glow": 0.42, "motion": 0.34,
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
            "radius": 16, "glow": 0.72, "motion": 0.48,
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
            "radius": 10, "glow": 0.20, "motion": 0.28,
            "reactive": True,
            "speaker_colors": {"User": "#287bb2"},
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
            "radius": 4, "glow": 0.12, "motion": 0.0,
            "reactive": False,
            "speaker_colors": {"User": "#55c7ff"},
            "speaker_icons": {"User": "U"},
        },
    },
}

DEFAULT_PRESET = "serpent"
COLOR_KEYS = {"bg", "panel", "line", "ink", "dim", "accent",
              "accent2", "warn", "good"}
ENUMS = {
    "background": {"none", "grid", "scales", "aurora", "stars", "paper"},
    "font": {"system", "mono", "serif"},
    "density": {"compact", "cozy", "roomy"},
}
NUMBERS = {"radius": (0, 28), "glow": (0.0, 1.0), "motion": (0.0, 1.0)}
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _merge(base: dict, overlay: dict) -> dict:
    out = deepcopy(base)
    for key, value in (overlay or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = deepcopy(value)
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


def clean_patch(patch: dict) -> dict:
    if not isinstance(patch, dict):
        raise ValueError("theme patch must be an object")
    unknown = set(patch) - {"preset", "tokens"}
    if unknown:
        raise ValueError(f"unknown theme field(s): {sorted(unknown)}")
    out = {}
    if "preset" in patch:
        if patch["preset"] not in PRESETS:
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


def resolve_theme(repo: str, persona: str = None, model: str = None) -> dict:
    household_path, person_path = _paths(repo, persona)
    household = _load(household_path)
    person_doc = _load(person_path) if person_path else {}
    persona_patch = {k: v for k, v in person_doc.items() if k != "models"}
    model_patch = ((person_doc.get("models") or {}).get(model) or {}
                   if model else {})
    layers = [household, persona_patch, model_patch]
    preset = DEFAULT_PRESET
    for layer in layers:
        if layer.get("preset") in PRESETS:
            preset = layer["preset"]
    tokens = deepcopy(PRESETS[preset]["tokens"])
    for layer in layers:
        tokens = _merge(tokens, layer.get("tokens") or {})
    tokens = _clean_tokens(tokens)
    return {
        "preset": preset,
        "tokens": tokens,
        "layers": {"household": household, "persona": persona_patch,
                   "model": model_patch},
        "presets": {key: value["label"] for key, value in PRESETS.items()},
        "preset_tokens": {key: deepcopy(value["tokens"])
                          for key, value in PRESETS.items()},
        "persona": persona, "model": model,
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
    clean = {} if reset else clean_patch(patch)
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

"""Persisted UI themes for Je Ne sAIs Quoi and persona cockpits.

Inheritance is explicit and one-way:
  built-in preset -> household -> persona -> model
  built-in preset -> household -> Nexus

The browser may add accessibility-only overrides (contrast, motion, scale)
without writing them into a persona. Theme files are descriptive display
preferences; they never feed emotional state back into the model.
"""
from copy import deepcopy
import colorsys
import hashlib
import json
import os
import re

import yaml


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
            "speaker_colors": {"User": "#62aee8"},
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
            "speaker_colors": {"User": "#62aee8"},
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
            "speaker_colors": {"User": "#62aee8"},
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
            "speaker_colors": {"User": "#62aee8"},
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
            "speaker_colors": {"User": "#62aee8"},
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
            "speaker_colors": {"User": "#62aee8"},
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
            "speaker_colors": {"User": "#62aee8"},
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
            "speaker_colors": {"User": "#62aee8"},
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
            "speaker_colors": {"User": "#62aee8"},
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
            "speaker_colors": {"User": "#62aee8"},
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
            "speaker_colors": {"User": "#62aee8"},
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
            "speaker_colors": {"User": "#62aee8"},
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
            "speaker_colors": {"User": "#62aee8"},
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
            "speaker_colors": {"User": "#62aee8"},
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
            "speaker_colors": {"User": "#62aee8"},
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
            "speaker_colors": {"User": "#62aee8"},
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
            "speaker_colors": {"User": "#62aee8"},
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
            "speaker_colors": {"User": "#62aee8"},
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
            "speaker_colors": {"User": "#62aee8"},
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
            "speaker_colors": {"User": "#62aee8"},
            "speaker_icons": {"User": "U"},
        },
    },
}


def _color_scheme(label, bg, panel, line, ink, dim, accent, accent2, warn,
                  good, background="none", font="system", density="cozy",
                  radius=10, glow=0.25, motion=0.25, speaker_colors=None):
    """Build a complete preset while keeping speaker identity legible."""
    return {
        "label": label,
        "tokens": {
            "bg": bg, "panel": panel, "line": line, "ink": ink, "dim": dim,
            "accent": accent, "accent2": accent2, "warn": warn, "good": good,
            "background": background, "font": font, "density": density,
            "radius": radius, "font_scale": 1.0, "glow": glow,
            "motion": motion, "reactive": True,
            "speaker_colors": speaker_colors or {


            },
            "speaker_icons": {"User": "U"},
        },
    }


# Quiet defaults, genre rooms, odd habitats, and unapologetic visual crimes.
PRESETS.update({
    "office_beige": _color_scheme(
        "Office beige", "#dedbd2", "#f4f1e8", "#b8b2a5", "#35342f",
        "#747168", "#596b73", "#827157", "#a34d43", "#537457",
        "none", "system", "compact", 4, 0.0, 0.0),
    "newsprint": _color_scheme(
        "Morning newsprint", "#dad6ca", "#f4f0e4", "#999487", "#24231f",
        "#69665e", "#404b55", "#8a392f", "#a23b32", "#496847",
        "paper", "serif", "compact", 0, 0.0, 0.0),
    "graphite": _color_scheme(
        "Graphite desk", "#181a1d", "#22252a", "#3b4048", "#e3e5e8",
        "#9399a1", "#86a0b8", "#c0a875", "#d47168", "#77a67d",
        "grid", "mono", "compact", 5, 0.08, 0.08),
    "greige": _color_scheme(
        "Respectable greige", "#cbc6bc", "#e8e4dc", "#aaa398", "#302f2c",
        "#6f6b64", "#586d6b", "#8b6f55", "#a44e45", "#52765d",
        "none", "humanist", "cozy", 9, 0.06, 0.06),
    "blueprint": _color_scheme(
        "Blueprint archive", "#071c2d", "#0c2a43", "#2f6382", "#e2f1f8",
        "#91b2c4", "#55b8e8", "#e5c76b", "#ee756c", "#69c597",
        "grid", "mono", "compact", 2, 0.34, 0.16),
    "old_library": _color_scheme(
        "Old library", "#17110c", "#261b12", "#59412c", "#eadcc4",
        "#a58f75", "#ae7947", "#68866c", "#c76655", "#6e9569",
        "paper", "serif", "roomy", 8, 0.18, 0.08),
    "sage_kitchen": _color_scheme(
        "Sage kitchen", "#d8ddcd", "#f0f1e7", "#9ba78b", "#29352c",
        "#647064", "#57765e", "#a4734f", "#ad5248", "#4e7952",
        "paper", "humanist", "roomy", 14, 0.10, 0.08),
    "terracotta": _color_scheme(
        "Terracotta afternoon", "#3b2119", "#563026", "#8d5441", "#f7dfce",
        "#c69b86", "#e07a52", "#e2b763", "#ef665c", "#83b36e",
        "paper", "serif", "roomy", 14, 0.30, 0.18),
    "coastal": _color_scheme(
        "Coastal linen", "#dce8e7", "#f5f3ea", "#9ebeba", "#243a3d",
        "#647d7e", "#287f8b", "#bf8650", "#b84f48", "#477b61",
        "paper", "humanist", "roomy", 12, 0.12, 0.12),
    "rainy_window": _color_scheme(
        "Rainy window", "#121c26", "#1b2935", "#39536a", "#dbe8ef",
        "#849bab", "#5c9fc4", "#a99bc9", "#d56f77", "#69a58d",
        "aurora", "humanist", "cozy", 16, 0.32, 0.22),
    "desert_night": _color_scheme(
        "Desert night", "#100d18", "#1c1728", "#493958", "#eee1d0",
        "#9f8da6", "#d18b5b", "#8f82cf", "#e46167", "#78aa80",
        "stars", "serif", "cozy", 12, 0.42, 0.28),
    "alpine_lake": _color_scheme(
        "Alpine lake", "#071b20", "#0d2b31", "#28606a", "#dff4f1",
        "#80a8aa", "#3ec4bd", "#93b8df", "#ec746a", "#62bf83",
        "aurora", "humanist", "cozy", 16, 0.44, 0.32),
    "mossy_stone": _color_scheme(
        "Mossy stone", "#151b16", "#222a22", "#465447", "#e0e6d8",
        "#929f8e", "#779566", "#b39a63", "#c86d5e", "#6da878",
        "scales", "serif", "cozy", 10, 0.24, 0.14),
    "abyssal": _color_scheme(
        "Abyssal blue", "#020b12", "#061722", "#163b4d", "#d6f1f2",
        "#729aa5", "#18b9c5", "#688ee8", "#ef6572", "#44c58a",
        "aurora", "system", "cozy", 14, 0.58, 0.38),
    "bioluminescent": _color_scheme(
        "Bioluminescent trench", "#010a0c", "#051719", "#164146", "#d9fff8",
        "#68a9a5", "#26ffd0", "#6aa8ff", "#ff647c", "#7dff78",
        "scales", "geometric", "cozy", 18, 0.82, 0.56),
    "mushroom_grove": _color_scheme(
        "Mushroom grove", "#160d18", "#281529", "#59315a", "#f1dfeb",
        "#aa86a4", "#db77b8", "#8ccf9b", "#ee6f71", "#77bd80",
        "paper", "rounded", "roomy", 24, 0.52, 0.34),
    "lavender_milk": _color_scheme(
        "Lavender milk", "#e7ddf0", "#faf5ff", "#bca9d0", "#352a43",
        "#796b89", "#8060ad", "#b76f94", "#b84f63", "#527e68",
        "aurora", "rounded", "roomy", 22, 0.20, 0.10),
    "peach_sorbet": _color_scheme(
        "Peach sorbet", "#ffd6c2", "#fff1e8", "#e6a98e", "#532d2b",
        "#966c63", "#dc5f65", "#8b6db2", "#c83f50", "#4f8066",
        "paper", "rounded", "roomy", 24, 0.24, 0.16),
    "mint_chip": _color_scheme(
        "Mint chip", "#bfe8d4", "#edfff5", "#74b89b", "#183c31",
        "#55796c", "#168566", "#684c77", "#bd4653", "#397751",
        "scales", "rounded", "cozy", 18, 0.28, 0.18),
    "strawberry_terminal": _color_scheme(
        "Strawberry terminal", "#1b0b10", "#2b1019", "#6e293e", "#ffdce7",
        "#bd8297", "#ff5d91", "#7ef0c2", "#ff785f", "#63d89a",
        "grid", "mono", "compact", 5, 0.58, 0.30),
    "solarized_dusk": _color_scheme(
        "Solarized dusk", "#002b36", "#073642", "#42636b", "#eee8d5",
        "#93a1a1", "#2aa198", "#b58900", "#dc5b52", "#859900",
        "none", "mono", "compact", 6, 0.18, 0.10),
    "arcade_carpet": _color_scheme(
        "Arcade carpet", "#090522", "#160b36", "#472b72", "#fff4ff",
        "#ad91c9", "#00e5ff", "#ff4fd8", "#ff674d", "#55f08b",
        "grid", "geometric", "compact", 4, 0.72, 0.72),
    "vaporwave": _color_scheme(
        "Vaporwave sunset", "#18052e", "#2b0d4a", "#723f91", "#fff1fc",
        "#c499d6", "#ff54c8", "#4de7ff", "#ff6f68", "#64f0a2",
        "grid", "geometric", "cozy", 8, 0.76, 0.62),
    "laser_tag": _color_scheme(
        "Laser-tag carpet crime", "#04030c", "#0e0920", "#44206b", "#f4efff",
        "#9f8bbd", "#7dff00", "#ff22cc", "#ff5a32", "#00ff9d",
        "stars", "geometric", "compact", 3, 0.92, 0.88),
    "radioactive": _color_scheme(
        "Radioactive lemonade", "#101500", "#202a00", "#637800", "#f7ffd6",
        "#b8c77a", "#c8ff00", "#00ffd5", "#ff5b31", "#52ff62",
        "grid", "mono", "compact", 2, 0.88, 0.74),
    "warning_label": _color_scheme(
        "Industrial warning label", "#15110a", "#221b0e", "#7b641d",
        "#fff4bd", "#c9b76d", "#ffd400", "#ff7a00", "#ff3b30", "#72db59",
        "grid", "mono", "compact", 0, 0.38, 0.16),
    "electric_circus": _color_scheme(
        "Electric circus", "#20002c", "#390044", "#9a246e", "#fff2cc",
        "#e0a7ce", "#ffed00", "#00f5ff", "#ff3d62", "#31ff82",
        "stars", "display", "cozy", 20, 0.96, 0.92),
    "candy_rave": _color_scheme(
        "Candy rave", "#ff3eb5", "#6b17ad", "#00efff", "#ffffff",
        "#ffd7f4", "#b9ff00", "#00f5ff", "#ff3b20", "#49ff8b",
        "aurora", "rounded", "compact", 28, 1.0, 1.0),
    "orange_soda": _color_scheme(
        "Orange soda detonation", "#ff5a00", "#9c1600", "#ffd000", "#ffffff",
        "#ffe0c7", "#00f0ff", "#ffea00", "#ff1838", "#47ff72",
        "grid", "display", "compact", 6, 0.90, 0.86),
    "ultraviolet": _color_scheme(
        "Ultraviolet incident", "#08000f", "#170024", "#6200a8", "#f9eaff",
        "#bc8dd7", "#c300ff", "#00eaff", "#ff376f", "#58ff8c",
        "stars", "geometric", "cozy", 12, 1.0, 0.90),
    "cyan_magenta": _color_scheme(
        "Cyan-magenta collision", "#001b24", "#003443", "#00bcd4", "#ffffff",
        "#a1ecf2", "#00ffff", "#ff00b8", "#ff4a38", "#3dff78",
        "aurora", "geometric", "compact", 10, 1.0, 1.0),
    "red_alert": _color_scheme(
        "Red alert", "#160000", "#2d0000", "#8f1616", "#fff1e8",
        "#d49a90", "#ff2b1c", "#ffd000", "#ff684f", "#5aff7a",
        "grid", "mono", "compact", 2, 0.86, 0.78),
    "toxic_mermaid": _color_scheme(
        "Toxic mermaid", "#001812", "#00382d", "#00a77b", "#eafff8",
        "#8bd9c2", "#00ff95", "#ff40db", "#ff5b56", "#a6ff3d",
        "scales", "rounded", "cozy", 24, 1.0, 0.94),
    "clown_dimension": _color_scheme(
        "Clown dimension", "#2500a8", "#ff1971", "#ffe600", "#ffffff",
        "#f8d9ff", "#00ffdd", "#ffed00", "#ff3b00", "#56ff3d",
        "stars", "display", "roomy", 28, 1.0, 1.0),
    "dragonfruit_reactor": _color_scheme(
        "Dragonfruit reactor", "#210018", "#4a0037", "#d60091", "#fff4fb",
        "#e8a6d2", "#ff2db2", "#baff00", "#ff643d", "#3dffb5",
        "scales", "rounded", "cozy", 22, 0.98, 0.92),
    "lime_crime": _color_scheme(
        "Lime crime", "#091300", "#192d00", "#619900", "#f5ffd9",
        "#bdd68a", "#9dff00", "#ff2bd6", "#ff4f27", "#00ff95",
        "grid", "geometric", "compact", 4, 1.0, 0.96),
    "plasma_orchid": _color_scheme(
        "Plasma orchid", "#100019", "#29003d", "#8500ae", "#fff0ff",
        "#d29bdd", "#ef21ff", "#38e8ff", "#ff4f7c", "#5dff9b",
        "aurora", "display", "cozy", 18, 1.0, 0.88),
    "blue_raspberry": _color_scheme(
        "Blue raspberry overload", "#00132e", "#002d63", "#007ff0",
        "#f1fbff", "#9ed6ff", "#00d9ff", "#ff38bf", "#ff553d", "#54ff8c",
        "aurora", "rounded", "roomy", 24, 0.98, 0.94),
    "watermelon_voltage": _color_scheme(
        "Watermelon voltage", "#190510", "#3e0a22", "#b51f5e", "#fff5dc",
        "#e7a5b5", "#ff356d", "#8cff00", "#ff7138", "#2dff90",
        "scales", "rounded", "cozy", 20, 0.90, 0.84),
    "galactic_slushie": _color_scheme(
        "Galactic slushie", "#080020", "#1e0750", "#6330c7", "#f9f2ff",
        "#c1a9ea", "#8b4dff", "#00f2ff", "#ff4a82", "#62ffb0",
        "stars", "rounded", "roomy", 26, 1.0, 1.0),
    "cyber_banana": _color_scheme(
        "Cyber banana", "#151000", "#332700", "#aa8500", "#fffbd6",
        "#d9c86c", "#ffe600", "#00eaff", "#ff4b29", "#61ff5c",
        "grid", "mono", "compact", 3, 0.92, 0.90),
    "hot_cheeto": _color_scheme(
        "Hot Cheeto astral plane", "#210500", "#4a0d00", "#b82b00",
        "#fff4df", "#eca17e", "#ff4d00", "#ffe600", "#ff1645", "#4dff79",
        "stars", "display", "compact", 14, 1.0, 0.96),
    "pool_float": _color_scheme(
        "Possessed pool float", "#001a20", "#003d49", "#00a8ba", "#f1ffff",
        "#93e3e8", "#00f2ff", "#ff3da6", "#ff6745", "#76ff69",
        "aurora", "rounded", "roomy", 28, 0.94, 1.0),
    "mall_arcade": _color_scheme(
        "Dead mall arcade", "#09000f", "#190025", "#5f126f", "#fff0ff",
        "#c491ca", "#ff28df", "#31fff3", "#ff5038", "#4cff82",
        "grid", "mono", "compact", 2, 1.0, 0.92),
    "alien_nursery": _color_scheme(
        "Alien nursery", "#031500", "#123500", "#3d8c00", "#f2ffe0",
        "#a9d68b", "#78ff00", "#c83dff", "#ff5a46", "#00ffa2",
        "scales", "rounded", "roomy", 28, 0.96, 0.86),
    "holographic_fever": _color_scheme(
        "Holographic fever", "#0c0822", "#21134c", "#684acf", "#ffffff",
        "#c4b5ef", "#5dfff5", "#ff51dc", "#ff5f51", "#8aff55",
        "aurora", "geometric", "cozy", 16, 1.0, 1.0),
    "bubblegum_emergency": _color_scheme(
        "Bubblegum emergency", "#30001d", "#65003e", "#e00089", "#fff4fb",
        "#f0add2", "#ff40bd", "#43f5ff", "#ff622e", "#83ff4d",
        "grid", "display", "roomy", 26, 1.0, 0.98),
    "goblin_laser": _color_scheme(
        "Goblin laser wedding", "#061400", "#172d00", "#547400", "#f7ffd8",
        "#bfce85", "#78ff19", "#d62bff", "#ff633c", "#00ffb7",
        "stars", "display", "cozy", 18, 1.0, 1.0),
    "sunburnt_aquarium": _color_scheme(
        "Sunburnt aquarium", "#00151a", "#00343d", "#00869a", "#f3ffff",
        "#98dce2", "#00e4ff", "#ff5b4d", "#ff285f", "#65ff8b",
        "scales", "humanist", "roomy", 22, 0.98, 0.90),
    "grape_surgery": _color_scheme(
        "Grape surgery", "#12001d", "#31004b", "#8b13bc", "#fff0ff",
        "#d6a0e7", "#c52cff", "#91ff00", "#ff466e", "#35ffae",
        "grid", "geometric", "compact", 5, 1.0, 0.94),
    "maximum_teal": _color_scheme(
        "Maximum teal event", "#001411", "#003c35", "#00a58d", "#eafffa",
        "#92ded1", "#00ffd5", "#ff3cc7", "#ff604b", "#a2ff35",
        "aurora", "geometric", "cozy", 16, 1.0, 1.0),
    "printer_accident": _color_scheme(
        "CMYK printer accident", "#09000e", "#1b0825", "#5d2571", "#ffffff",
        "#d3b1df", "#00eaff", "#ff00a8", "#ff4a16", "#dfff00",
        "grid", "mono", "compact", 0, 1.0, 1.0),
    "sherbet_apocalypse": _color_scheme(
        "Sherbet apocalypse", "#351000", "#662300", "#e05a00", "#fff7e6",
        "#f4b58d", "#ff8a00", "#ff3fcf", "#ff234f", "#48ff94",
        "aurora", "rounded", "roomy", 28, 1.0, 1.0),
    "retina_lawsuit": _color_scheme(
        "Retina lawsuit", "#180029", "#52006b", "#ff00bd", "#ffffff",
        "#ffd0f5", "#c6ff00", "#00f6ff", "#ff3a12", "#39ff66",
        "stars", "display", "compact", 28, 1.0, 1.0),
    "parrot_scarlet_macaw": _color_scheme(
        "Parrot · Scarlet macaw", "#210708", "#481013", "#a72c24",
        "#fff1d2", "#dfaa83", "#f02d22", "#ffd31c", "#ff6640", "#42c976",
        "stars", "display", "roomy", 18, 0.82, 0.72),
    "parrot_blue_gold_macaw": _color_scheme(
        "Parrot · Blue-and-gold macaw", "#03172d", "#082f5c", "#176db5",
        "#fff4bf", "#a7c7d5", "#ffd62d", "#32a8e0", "#f05a45", "#55c879",
        "aurora", "rounded", "roomy", 20, 0.72, 0.62),
    "parrot_red_green_macaw": _color_scheme(
        "Parrot · Red-and-green macaw", "#17090b", "#381417", "#812d2d",
        "#f6f2df", "#c9a09a", "#e5322d", "#29a85d", "#ff6a45", "#4bd17d",
        "scales", "humanist", "cozy", 16, 0.68, 0.54),
    "parrot_hyacinth_macaw": _color_scheme(
        "Parrot · Hyacinth macaw", "#040d24", "#091b49", "#173c83",
        "#edf4ff", "#93a7d0", "#315ee8", "#ffd51f", "#f15a54", "#54c984",
        "aurora", "geometric", "cozy", 18, 0.78, 0.58),
    "parrot_eclectus": _color_scheme(
        "Parrot · Eclectus pair", "#07160d", "#102f1b", "#287040",
        "#f1ffe9", "#91bd99", "#25c85a", "#e52d45", "#ff6b47", "#65df72",
        "scales", "serif", "roomy", 20, 0.72, 0.48),
    "parrot_galah": _color_scheme(
        "Parrot · Galah", "#2b2027", "#45333e", "#806473", "#fff0f5",
        "#c7a9b7", "#ef779f", "#aeb4c2", "#e65d73", "#69b888",
        "paper", "rounded", "roomy", 24, 0.42, 0.24),
    "parrot_african_grey": _color_scheme(
        "Parrot · African grey", "#17191c", "#282c31", "#596069",
        "#f0f1ef", "#a5a9ad", "#c5c9ca", "#dc3344", "#ef5c55", "#67a878",
        "scales", "humanist", "cozy", 14, 0.30, 0.18),
    "parrot_sulphur_cockatoo": _color_scheme(
        "Parrot · Sulphur-crested cockatoo", "#d8d9ce", "#f8f8ed",
        "#aaa99b", "#292a27", "#6f7068", "#d8b800", "#677f88", "#b9473f",
        "#4d7958", "paper", "humanist", "roomy", 18, 0.16, 0.18),
    "parrot_rainbow_lorikeet": _color_scheme(
        "Parrot · Rainbow lorikeet", "#061b16", "#0d3a2d", "#17715a",
        "#f5ffdb", "#9ed0b5", "#28d66d", "#3f79ed", "#ff4f42", "#a7ed25",
        "aurora", "rounded", "roomy", 26, 0.92, 0.88),
    "pigeon_blue_bar": _color_scheme(
        "Pigeon · Blue-bar", "#20272d", "#343f48", "#657581", "#eef2f3",
        "#aab5bc", "#7b929f", "#52a48e", "#c76764", "#70a477",
        "grid", "humanist", "cozy", 10, 0.24, 0.14),
    "pigeon_red_bar": _color_scheme(
        "Pigeon · Red-bar", "#2a211f", "#443431", "#78594f", "#f2e9e2",
        "#b9a49a", "#a96454", "#738e88", "#c8544d", "#6e9b73",
        "grid", "humanist", "cozy", 10, 0.24, 0.14),
    "pigeon_rusty_red": _color_scheme(
        "Pigeon · Rusty red", "#2b1814", "#482720", "#7d4638", "#f5e6da",
        "#be9a89", "#bd6148", "#d0a36a", "#dd574c", "#77996c",
        "paper", "serif", "cozy", 12, 0.30, 0.16),
    "pigeon_spread": _color_scheme(
        "Pigeon · Black spread", "#07090b", "#13171a", "#343b40", "#edf1f2",
        "#929da2", "#38aa91", "#816fc0", "#d05e61", "#62a975",
        "none", "system", "compact", 6, 0.30, 0.12),
    "pigeon_white": _color_scheme(
        "Pigeon · White", "#d7dcdd", "#f8faf8", "#afb8b9", "#293033",
        "#6c777a", "#587b83", "#8d7199", "#ac4d51", "#4f775f",
        "paper", "serif", "roomy", 18, 0.10, 0.08),
    "pigeon_checkered": _color_scheme(
        "Pigeon · Checkered", "#191d20", "#2c3236", "#697277", "#edf0eb",
        "#a0a9a8", "#6c8d94", "#46a082", "#c25f5b", "#6c9f70",
        "scales", "mono", "compact", 5, 0.28, 0.16),
    "pigeon_pied": _color_scheme(
        "Pigeon · Pied", "#252329", "#f0eee9", "#aaa5ab", "#27262b",
        "#6f6b72", "#65508b", "#2c8d83", "#b54e59", "#4d795d",
        "scales", "humanist", "cozy", 14, 0.18, 0.12),
    "violet_flame": _color_scheme(
        "New Age · Violet Flame", "#f3cfc2", "#fff0e9", "#cf9dbd", "#4b2948",
        "#7f5f72", "#7c49b8", "#d75291", "#b74757", "#3e7663",
        "aurora", "playfair", "roomy", 24, 0.32, 0.30,
        speaker_colors={
                         }),

    # Starseed is an aesthetic collection: each entry is a distinct visual
    # vocabulary, not a claim about a lineage, origin, or lived experience.
    "starseed_pleiadian": _color_scheme(
        "Starseed · Pleiadian", "#dbeaf2", "#f7fbff", "#9dc4d7", "#20384d",
        "#617d8e", "#4e91b6", "#b36fa7", "#b64f61", "#3f7768",
        "aurora", "quicksand", "roomy", 24, 0.28, 0.34,
        speaker_colors={
                         }),
    "starseed_sirian": _color_scheme(
        "Starseed · Sirian", "#020c1d", "#071a33", "#174d70", "#e9f7ff",
        "#8ab1c7", "#27c8df", "#e7bd61", "#f06b70", "#50d49a",
        "stars", "geometric", "cozy", 14, 0.76, 0.52),
    "starseed_orion": _color_scheme(
        "Starseed · Orion", "#050814", "#0d1428", "#293d69", "#edf1ff",
        "#929fbe", "#597ee8", "#c59055", "#e56568", "#58b88a",
        "stars", "cinzel", "compact", 6, 0.58, 0.26),
    "starseed_draconian": _color_scheme(
        "Starseed · Draconian", "#0b0506", "#1b0b0e", "#5e2523", "#f3e7d5",
        "#ad8d82", "#b64235", "#c99a4b", "#e4574f", "#678f64",
        "scales", "display", "compact", 4, 0.60, 0.34),
    "starseed_reptilian": _color_scheme(
        "Starseed · Reptilian", "#031009", "#0a2115", "#285f3b", "#e7f5d6",
        "#92ad83", "#59c659", "#b4d53f", "#e16a4f", "#53cf89",
        "scales", "condensed", "cozy", 12, 0.58, 0.54),
    "starseed_zeta": _color_scheme(
        "Starseed · Zeta", "#cfd7d3", "#eef3f0", "#96a8a1", "#25332f",
        "#687a74", "#477d71", "#726796", "#a84d58", "#47765a",
        "grid", "mono", "compact", 2, 0.08, 0.10,
        speaker_colors={
                         }),
    "starseed_andromedan": _color_scheme(
        "Starseed · Andromedan", "#0d0621", "#211044", "#5f3d91", "#faf0ff",
        "#bca5d2", "#c657d8", "#43d5e7", "#f46786", "#55d9a0",
        "aurora", "rounded", "roomy", 26, 0.88, 0.78),
    "starseed_arcturian": _color_scheme(
        "Starseed · Arcturian", "#070729", "#15134d", "#4e42a3", "#f1efff",
        "#aaa4d7", "#8a68ff", "#31d7cd", "#f35d82", "#5ce08d",
        "grid", "geometric", "cozy", 16, 0.92, 0.74),
    "starseed_anunnaki": _color_scheme(
        "Starseed · Anunnaki", "#090d18", "#121d35", "#3f5480", "#f4e8c8",
        "#a8a18e", "#d0a13c", "#376eb4", "#d76552", "#6ca172",
        "stars", "cinzel", "roomy", 8, 0.50, 0.24),
    "starseed_avian": _color_scheme(
        "Starseed · Avian", "#d8ebf4", "#f9fcff", "#9ebfd0", "#243b4b",
        "#677f8d", "#478eb6", "#c39045", "#b8535b", "#43765f",
        "aurora", "humanist", "roomy", 22, 0.22, 0.42,
        speaker_colors={
                         }),
    "starseed_mantid": _color_scheme(
        "Starseed · Mantid", "#040b07", "#0d1c12", "#315438", "#eaf4dd",
        "#98a98d", "#8dbb45", "#d2a34a", "#df664c", "#51b679",
        "scales", "condensed", "compact", 10, 0.48, 0.50),
    "starseed_alpha_centauri": _color_scheme(
        "Starseed · Alpha Centauri", "#090b18", "#171b35", "#4d527c", "#f8f1dc",
        "#aaa7b1", "#e1b557", "#dc756e", "#ee6467", "#63b887",
        "stars", "playfair", "cozy", 14, 0.64, 0.50),
    "starseed_eridanian": _color_scheme(
        "Starseed · Eridanian", "#03131c", "#092b3a", "#22657a", "#e4f6f5",
        "#8cb4b9", "#32b8b2", "#668fd0", "#e66f72", "#55c28a",
        "aurora", "humanist", "cozy", 18, 0.62, 0.44),
    "starseed_vegan": _color_scheme(
        "Starseed · Vegan (Vega)", "#050b22", "#101e48", "#355da3", "#f0f5ff",
        "#9eafd1", "#5f8ff5", "#d687b4", "#ea6173", "#5fc48d",
        "stars", "geometric", "cozy", 16, 0.74, 0.54),
    "starseed_lyran": _color_scheme(
        "Starseed · Lyran", "#150b1c", "#281532", "#654477", "#f8ead7",
        "#b39bad", "#d8a64d", "#a66bc2", "#e46762", "#67a878",
        "stars", "display", "roomy", 18, 0.68, 0.46),

    # Zodiac palettes use seasonal, elemental, and traditional visual motifs
    # without prescribing personality or experience to the person using them.
    "zodiac_aries": _color_scheme(
        "Zodiac · Aries", "#170605", "#32100c", "#812d20", "#fff0da",
        "#d0a08c", "#ed4d2e", "#e9a34a", "#ff5e42", "#70a768",
        "grid", "display", "compact", 8, 0.72, 0.68),
    "zodiac_taurus": _color_scheme(
        "Zodiac · Taurus", "#152018", "#253328", "#5b7056", "#f2ead8",
        "#aaa58e", "#79985f", "#c47f7c", "#cf5e55", "#69a66b",
        "paper", "serif", "roomy", 18, 0.28, 0.14),
    "zodiac_gemini": _color_scheme(
        "Zodiac · Gemini", "#f0d978", "#fff6c7", "#c3a94a", "#403814",
        "#746930", "#187f8b", "#6558aa", "#a9454c", "#417555",
        "grid", "geometric", "cozy", 12, 0.20, 0.46,
        speaker_colors={
                         }),
    "zodiac_cancer": _color_scheme(
        "Zodiac · Cancer", "#dce4e9", "#f8fbfc", "#abbcc8", "#273a47",
        "#697d88", "#5a86a5", "#8a76ab", "#ad5260", "#477761",
        "aurora", "playfair", "roomy", 24, 0.18, 0.18,
        speaker_colors={
                         }),
    "zodiac_leo": _color_scheme(
        "Zodiac · Leo", "#231006", "#44200b", "#9b5b1a", "#fff1c7",
        "#d4a66f", "#ffb21e", "#ed6c2b", "#f15a3e", "#71a45e",
        "stars", "display", "roomy", 18, 0.80, 0.62),
    "zodiac_virgo": _color_scheme(
        "Zodiac · Virgo", "#d9d6b9", "#f2efdc", "#aaa777", "#343a27",
        "#6f7459", "#657c4b", "#a2764e", "#a94f49", "#4e7652",
        "paper", "baskerville", "cozy", 10, 0.08, 0.08,
        speaker_colors={
                         }),
    "zodiac_libra": _color_scheme(
        "Zodiac · Libra", "#efd9dd", "#fff4f1", "#c7a5b0", "#49303d",
        "#7e6670", "#ae6682", "#547fa5", "#b64c58", "#4b7862",
        "paper", "playfair", "roomy", 22, 0.20, 0.16,
        speaker_colors={
                         }),
    "zodiac_scorpio": _color_scheme(
        "Zodiac · Scorpio", "#080407", "#1a0911", "#5f1c36", "#f6e7eb",
        "#ad8995", "#bd3159", "#7650a2", "#ef4c63", "#5fa273",
        "scales", "cinzel", "compact", 6, 0.70, 0.30),
    "zodiac_sagittarius": _color_scheme(
        "Zodiac · Sagittarius", "#100923", "#211343", "#5c3c89", "#f6edff",
        "#b19fc6", "#8958d4", "#4f9bc7", "#e96368", "#5eb684",
        "stars", "display", "cozy", 14, 0.72, 0.66),
    "zodiac_capricorn": _color_scheme(
        "Zodiac · Capricorn", "#101515", "#1d2825", "#4b5b50", "#e9eadf",
        "#989f95", "#78856c", "#a98050", "#cb6256", "#5c9a70",
        "grid", "serif", "compact", 5, 0.22, 0.12),
    "zodiac_aquarius": _color_scheme(
        "Zodiac · Aquarius", "#031024", "#09264a", "#1f6c9b", "#e8f8ff",
        "#8fb8ce", "#28c7e8", "#7c70e8", "#ed6374", "#51cc91",
        "grid", "geometric", "cozy", 12, 0.86, 0.78),
    "zodiac_pisces": _color_scheme(
        "Zodiac · Pisces", "#07151c", "#102d39", "#356b78", "#eaf5ef",
        "#96b4b2", "#4bb7aa", "#a078bd", "#e56d7b", "#55bd86",
        "aurora", "rounded", "roomy", 24, 0.62, 0.48),
})


PRESET_COLLECTIONS = {
    "New Age": ("violet_flame",),
    "Starseed": (
        "starseed_pleiadian", "starseed_sirian", "starseed_orion",
        "starseed_draconian", "starseed_reptilian", "starseed_zeta",
        "starseed_andromedan", "starseed_arcturian", "starseed_anunnaki",
        "starseed_avian", "starseed_mantid", "starseed_alpha_centauri",
        "starseed_eridanian", "starseed_vegan", "starseed_lyran",
    ),
    "Zodiac": (
        "zodiac_aries", "zodiac_taurus", "zodiac_gemini", "zodiac_cancer",
        "zodiac_leo", "zodiac_virgo", "zodiac_libra", "zodiac_scorpio",
        "zodiac_sagittarius", "zodiac_capricorn", "zodiac_aquarius",
        "zodiac_pisces",
    ),
}


DEFAULT_PRESET = "bal_masque"
CUSTOM_PRESETS_FILE = "custom_presets.json"
NEXUS_THEME_FILE = "nexus_theme.json"
NEXUS_PROTECTED_TOKENS = {"speaker_colors", "speaker_icons"}
COLOR_KEYS = {"bg", "panel", "line", "ink", "dim", "accent",
              "accent2", "warn", "good"}
FONT_IDS = {
    "system", "serif", "display", "mono", "humanist", "rounded", "geometric",
    "alegreya", "baskerville", "playfair", "slab", "inter", "lexend",
    "quicksand", "condensed", "handwritten", "marker", "jetbrains", "cinzel",
}
ENUMS = {
    "background": {"none", "grid", "scales", "aurora", "stars", "paper",
                   "image"},
    "conversation_area_background": {"none", "image"},
    "font": FONT_IDS,
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


def _resident_identities(repo: str) -> list[dict]:
    """Read roster-backed model identities without inventing membership."""
    root = os.path.join(repo, "personas")
    identities = []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return identities
    for pid in names:
        path = os.path.join(root, pid, "roster.yaml")
        if pid.startswith(("_", ".")) or not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as handle:
                roster = yaml.safe_load(handle) or {}
        except Exception:
            continue
        if roster.get("kind", "model_persona") != "model_persona":
            continue
        display = str(roster.get("display_name") or pid).strip()
        identities.append({"id": pid, "display_name": display,
                           "icon": str(roster.get("icon") or "").strip()})
    return identities


def _luminance(color: str) -> float:
    channels = [int(color[index:index + 2], 16) / 255.0
                for index in (1, 3, 5)]
    linear = [value / 12.92 if value <= 0.04045 else
              ((value + 0.055) / 1.055) ** 2.4 for value in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(left: str, right: str) -> float:
    high, low = sorted((_luminance(left), _luminance(right)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _resident_color(identity: str, panel: str) -> str:
    """Derive a stable, legible color from identity and the active surface."""
    digest = hashlib.sha256(identity.casefold().encode("utf-8")).digest()
    hue = int.from_bytes(digest[:4], "big") / 0xffffffff
    saturation = 0.56 + (digest[4] / 255.0) * 0.22
    panel_luminance = _luminance(panel)
    lightnesses = ((0.78, 0.70, 0.86, 0.62, 0.92)
                   if panel_luminance < 0.35 else
                   (0.30, 0.23, 0.37, 0.16, 0.08))
    candidates = []
    for lightness in lightnesses:
        rgb = colorsys.hls_to_rgb(hue, lightness, saturation)
        color = "#" + "".join(f"{round(channel * 255):02x}"
                                for channel in rgb)
        candidates.append(color)
        if _contrast(color, panel) >= 4.5:
            return color
    # The sequence normally finds a chromatic answer.  The mathematical
    # endpoint keeps accessibility true on an unusual custom panel.
    endpoints = ("#ffffff", "#000000")
    return max(endpoints, key=lambda value: _contrast(value, panel))


def _has_named(mapping: dict, *names: str) -> bool:
    keys = {str(key).casefold() for key in (mapping or {})}
    return any(str(name).casefold() in keys for name in names)


def _complete_resident_identity(repo: str, tokens: dict,
                                explicit_tokens: dict | None = None,
                                identities: list[dict] | None = None) -> dict:
    """Complete missing roster colors/icons by formula, never a name list."""
    out = deepcopy(tokens or {})
    colors = dict(out.get("speaker_colors") or {})
    icons = dict(out.get("speaker_icons") or {})
    explicit_icons = dict((explicit_tokens or {}).get("speaker_icons") or {})
    panel = str(out.get("panel") or "#131120")
    for resident in (identities if identities is not None
                     else _resident_identities(repo)):
        pid, display = resident["id"], resident["display_name"]
        if not _has_named(colors, display, pid):
            colors[display] = _resident_color(pid, panel)
        if not _has_named(explicit_icons, display, pid):
            icons[display] = resident["icon"] or display[:1].upper()
        elif not _has_named(icons, display, pid):
            icons[display] = resident["icon"] or display[:1].upper()
    out["speaker_colors"] = colors
    out["speaker_icons"] = icons
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


def _preset_collections(presets: dict) -> dict:
    """Return stable built-in families without swallowing local presets."""
    return {
        label: [preset_id for preset_id in preset_ids if preset_id in presets]
        for label, preset_ids in PRESET_COLLECTIONS.items()
    }


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
    identities = _resident_identities(repo)
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
    explicit_tokens = {}
    for layer in layers:
        tokens = _merge(tokens, layer.get("tokens") or {})
        explicit_tokens = _merge(explicit_tokens, layer.get("tokens") or {})
    tokens = _clean_tokens(_complete_resident_identity(
        repo, _with_defaults(tokens), explicit_tokens, identities))
    return {
        "preset": preset,
        "tokens": tokens,
        "layers": {"household": household, "persona": persona_patch,
                   "model": model_patch},
        "presets": {key: value["label"] for key, value in presets.items()},
        "preset_tokens": {key: _complete_resident_identity(
                              repo, _with_defaults(value["tokens"]),
                              identities=identities)
                          for key, value in presets.items()},
        "preset_collections": _preset_collections(presets),
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
    identities = _resident_identities(repo)
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
        "preset_tokens": {key: _complete_resident_identity(
                              repo, _with_defaults(value["tokens"]),
                              identities=identities)
                          for key, value in presets.items()},
        "preset_collections": _preset_collections(presets),
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

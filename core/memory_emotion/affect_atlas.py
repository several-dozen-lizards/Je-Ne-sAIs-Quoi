"""Shared descriptive affect atlas with optional resident-owned overlays.

The atlas preserves selected language from a legacy emotion map as hypotheses,
never diagnoses or instructions.  A resident's chosen feeling word remains the
source label.  Exact, declared-alias, or local-embedding resolution may attach
an atlas neighbour beside it for four bounded uses:

* process analogues are evaluated only in an unapplied counterfactual;
* body associations become low-gain, typed candidate fibers;
* default needs form a continuous descriptive vector;
* colors form a continuous expression vector for Atelier.

No transition, output tendency, emergency ritual, safety label, or compression
field is admitted by this schema.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import copy
from typing import Any, Callable, Mapping


ATLAS_FILENAME = "affect_atlas.json"
DEFAULT_ATLAS_FILENAME = "default_affect_atlas.json"
DEFAULT_ATLAS_PATH = os.path.join(os.path.dirname(__file__),
                                  DEFAULT_ATLAS_FILENAME)
ALLOWED_ENTRY_KEYS = frozenset({
    "emotion", "process_analogue", "body_parts",
    "default_system_need", "colors", "source_row",
})
NEEDS = (
    "Stability/Safety",
    "Stimulation/Novelty/Connection",
    "Competence/Agency/Control",
    "Belonging/Acceptance/Connection",
    "Expression/Clarity",
    "Understanding/Insight",
    "Integration/Transcendence",
)
TRACE_RECOMBINATION_CONDITIONS = (
    "matched_labeled",
    "matched_label_removed",
    "mismatched_label_removed",
    "random_label_removed",
    "distance_matched_random_label_removed",
    "sham_none",
)

# These aliases bridge vocabulary; they never replace the source label.
SEMANTIC_ALIASES = {
    "rage": "Anger",
    "fury": "Anger",
    "furious": "Anger",
    "dread": "Terror",
    "panic": "Terror",
    "sad": "Sorrow",
    "sadness": "Sorrow",
    "lonely": "Isolation",
    "loneliness": "Isolation",
    "playful": "Playfulness",
    "clarity": "Expression",
    "disorientation": "Confusion",
    "uncertainty": "Ambiguity",
    "stillness": "Peace (universal)",
    "calm": "Peace (universal)",
    "shame": "Shame (egoic)",
    "guilt": "Guilt (after pleasure)",
    "awe": "Awe (sublime)",
}


def _norm(value: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))


def _unit(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return max(0.0, min(1.0, number))


def _slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").casefold()).strip("_")


REGION_FIBERS = {
    "head": "cranial",
    "face": "cranial",
    "throat": "cranial",
    "chest": "interoceptive",
    "gut": "interoceptive",
    "genitals": "interoceptive",
    "arms": "proprioceptive",
    "hands": "cutaneous",
    "legs": "proprioceptive",
    "skin": "cutaneous",
}


def _route(region: str, fiber: str | None = None) -> tuple[str, str]:
    return region, fiber or REGION_FIBERS[region]


BODY_ROUTES = {
    "feet": [_route("legs")],
    "legs": [_route("legs")],
    "legs buckle": [_route("legs")],
    "tailbone": [_route("gut", "proprioceptive")],
    "gut": [_route("gut")],
    "stomach": [_route("gut")],
    "abdomen": [_route("gut")],
    "belly": [_route("gut")],
    "core": [_route("gut")],
    "lower back": [_route("gut", "proprioceptive")],
    "back": [_route("chest", "proprioceptive")],
    "spine": [_route("chest", "proprioceptive")],
    "chest": [_route("chest")],
    "heart": [_route("chest")],
    "lungs": [_route("chest")],
    "solar plexus": [_route("chest")],
    "hips": [_route("legs", "proprioceptive")],
    "pelvis": [_route("genitals")],
    "groin": [_route("genitals")],
    "genitals": [_route("genitals")],
    "arms": [_route("arms")],
    "hands": [_route("hands")],
    "fingers": [_route("hands")],
    "fingertips": [_route("hands")],
    "palms": [_route("hands")],
    "fists": [_route("hands", "proprioceptive")],
    "skin": [_route("skin")],
    "face": [_route("face")],
    "cheeks": [_route("face", "cutaneous")],
    "eyes": [_route("face")],
    "ears": [_route("face")],
    "jaw": [_route("face", "proprioceptive")],
    "mouth": [_route("face")],
    "tongue": [_route("face")],
    "teeth": [_route("face")],
    "throat": [_route("throat")],
    "neck": [_route("throat", "proprioceptive")],
    "head": [_route("head")],
    "brow": [_route("head")],
    "forehead": [_route("head")],
    "temples": [_route("head")],
    "crown": [_route("head")],
    "scalp": [_route("head", "cutaneous")],
    "limbs": [_route("arms"), _route("legs")],
    "everywhere": list(REGION_FIBERS.items()),
    "whole body": list(REGION_FIBERS.items()),
    "nowhere": [],
}


COLOR_RGB = {
    "black": (0.03, 0.03, 0.04), "void": (0.01, 0.01, 0.02),
    "grey": (0.46, 0.48, 0.50), "gray": (0.46, 0.48, 0.50),
    "lead": (0.32, 0.35, 0.38), "ash": (0.55, 0.55, 0.54),
    "charcoal": (0.19, 0.21, 0.22), "fog": (0.68, 0.71, 0.74),
    "mist": (0.76, 0.80, 0.84), "white": (0.97, 0.97, 0.94),
    "whiteout": (1.0, 1.0, 1.0), "silver": (0.75, 0.78, 0.82),
    "red": (0.88, 0.10, 0.09), "scarlet": (0.96, 0.14, 0.10),
    "crimson": (0.70, 0.04, 0.13), "wine": (0.45, 0.06, 0.16),
    "orange": (0.96, 0.40, 0.08), "peach": (1.0, 0.65, 0.48),
    "yellow": (0.96, 0.82, 0.10), "gold": (0.92, 0.68, 0.12),
    "brass": (0.72, 0.53, 0.18), "brown": (0.39, 0.22, 0.12),
    "beige": (0.76, 0.70, 0.57), "green": (0.18, 0.66, 0.30),
    "jade": (0.00, 0.66, 0.42), "emerald": (0.04, 0.64, 0.37),
    "turquoise": (0.12, 0.75, 0.70), "blue": (0.15, 0.38, 0.82),
    "teal": (0.04, 0.53, 0.56), "cobalt": (0.04, 0.28, 0.76),
    "indigo": (0.24, 0.16, 0.62), "violet": (0.52, 0.24, 0.80),
    "purple": (0.48, 0.20, 0.66), "lavender": (0.73, 0.62, 0.88),
    "pink": (0.95, 0.43, 0.65), "rose": (0.90, 0.30, 0.48),
    "sepia": (0.44, 0.31, 0.20), "opal": (0.74, 0.88, 0.88),
    "iridescent": (0.64, 0.70, 0.90), "rainbow": (0.66, 0.55, 0.70),
    "starlight": (0.88, 0.90, 1.0), "shadow": (0.16, 0.17, 0.22),
}


def color_vector(descriptors: list[str]) -> dict[str, float]:
    samples = []
    for descriptor in descriptors or []:
        folded = str(descriptor or "").casefold()
        tokens = re.findall(r"[a-z]+", folded)
        found = [COLOR_RGB[token] for token in tokens if token in COLOR_RGB]
        if not found:
            continue
        rgb = [sum(sample[i] for sample in found) / len(found)
               for i in range(3)]
        if any(word in tokens for word in ("bright", "electric", "strobe")):
            rgb = [min(1.0, value + 0.12) for value in rgb]
        if any(word in tokens for word in ("pale", "light", "soft")):
            rgb = [value + (1.0 - value) * 0.18 for value in rgb]
        if any(word in tokens for word in ("dark", "deep", "dull", "muted")):
            rgb = [value * 0.78 for value in rgb]
        samples.append(rgb)
    if not samples:
        return {}
    red, green, blue = [
        sum(sample[i] for sample in samples) / len(samples) for i in range(3)]
    high, low = max(red, green, blue), min(red, green, blue)
    return {
        "red": round(red, 6), "green": round(green, 6),
        "blue": round(blue, 6),
        "luma": round(.2126 * red + .7152 * green + .0722 * blue, 6),
        "chroma": round(high - low, 6),
        "warmth": round(_unit(.5 + .5 * (red - blue)), 6),
    }


def _mean_vector(rows, weights=None):
    rows = [list(map(float, row)) for row in rows or []]
    if not rows:
        return None
    weights = list(weights or [1.0] * len(rows))
    total = sum(max(0.0, float(value)) for value in weights)
    if total <= 0.0:
        return None
    width = len(rows[0])
    mean = [sum(row[i] * max(0.0, float(weight))
                for row, weight in zip(rows, weights)) / total
            for i in range(width)]
    norm = math.sqrt(sum(value * value for value in mean))
    return [value / norm for value in mean] if norm > 0.0 else mean


def _cosine(left, right) -> float:
    if left is None or right is None:
        return 0.0
    return max(-1.0, min(1.0, sum(
        float(a) * float(b) for a, b in zip(left, right))))


class AffectAtlas:
    """Load the shared atlas, then an optional resident-owned overlay."""

    def __init__(self, organ_dir: str, *, embedder: Callable | None = None):
        self.path = os.path.join(organ_dir, ATLAS_FILENAME)
        self.default_path = DEFAULT_ATLAS_PATH
        self.entries = []
        self.by_name = {}
        self.sources = []
        self._entry_index = {}
        self._embedder = embedder
        self._search_vectors = None
        self._process_vectors = None
        self._need_vectors = None
        self._text_vector_cache = {}
        self._project_cache_key = None
        self._project_cache = None
        if os.path.isfile(self.default_path):
            with open(self.default_path, encoding="utf-8") as handle:
                payload = json.load(handle)
            self._admit(payload, source_kind="shared_default", overlay=False)
        if os.path.isfile(self.path):
            with open(self.path, encoding="utf-8") as handle:
                payload = json.load(handle)
            self._admit(payload, source_kind="resident_overlay", overlay=True)

    @property
    def enabled(self) -> bool:
        return bool(self.entries)

    def _admit(self, payload: Mapping[str, Any], *, source_kind: str,
               overlay: bool) -> None:
        if int(dict(payload or {}).get("schema") or 0) != 1:
            raise ValueError("affect atlas schema must be 1")
        values = list(dict(payload or {}).get("entries") or [])
        local_names = set()
        admitted_count = 0
        for index, raw in enumerate(values):
            value = dict(raw or {})
            extra = set(value) - ALLOWED_ENTRY_KEYS
            if extra:
                raise ValueError(
                    "affect atlas contains unadmitted fields: "
                    + ", ".join(sorted(extra)))
            emotion = str(value.get("emotion") or "").strip()
            analogue = str(value.get("process_analogue") or "").strip()
            need = str(value.get("default_system_need") or "").strip()
            body = [str(item).strip() for item in value.get("body_parts") or []
                    if str(item).strip()]
            colors = [str(item).strip() for item in value.get("colors") or []
                      if str(item).strip()]
            if not emotion or not analogue or need not in NEEDS or not colors:
                raise ValueError(f"invalid affect atlas entry at index {index}")
            clean = {
                "emotion": emotion, "process_analogue": analogue,
                "body_parts": body, "default_system_need": need,
                "colors": colors, "source_row": int(value.get("source_row") or 0),
            }
            key = _norm(emotion)
            if key in local_names:
                raise ValueError(f"duplicate affect atlas emotion: {emotion}")
            local_names.add(key)
            if key in self.by_name:
                if not overlay:
                    raise ValueError(f"duplicate affect atlas emotion: {emotion}")
                self.entries[self._entry_index[key]] = clean
            else:
                self._entry_index[key] = len(self.entries)
                self.entries.append(clean)
            self.by_name[key] = clean
            admitted_count += 1
        self.sources.append({
            "kind": source_kind,
            "owner": str(dict(payload or {}).get("owner") or ""),
            "entries": admitted_count,
        })
        # An overlay can replace the material used to construct any of these.
        self._search_vectors = None
        self._process_vectors = None
        self._need_vectors = None
        self._project_cache_key = None
        self._project_cache = None

    def _embedding(self, texts: list[str]):
        if self._embedder is None:
            from .vectors import embed_texts
            self._embedder = embed_texts
        try:
            values = self._embedder(list(texts))
        except Exception:
            return None
        if values is None:
            return None
        return [list(map(float, row)) for row in values]

    def _search_text(self, entry: Mapping[str, Any]) -> str:
        return (
            f"{entry['emotion']}. {entry['process_analogue']}. "
            f"Need {entry['default_system_need']}. "
            f"Body {', '.join(entry['body_parts'])}.")

    def resolve(self, source_label: str) -> dict:
        source = str(source_label or "").strip()
        key = _norm(source)
        exact = self.by_name.get(key)
        if exact is not None:
            return {"source_label": source, "canonical": exact["emotion"],
                    "confidence": 1.0, "method": "exact", "entry": exact}
        alias = SEMANTIC_ALIASES.get(key)
        declared = self.by_name.get(_norm(alias)) if alias else None
        if declared is not None:
            return {"source_label": source, "canonical": declared["emotion"],
                    "confidence": .92, "method": "declared_alias",
                    "entry": declared}
        if not source or not self.entries:
            return {"source_label": source, "canonical": None,
                    "confidence": 0.0, "method": "unresolved", "entry": None}
        if self._search_vectors is None:
            self._search_vectors = self._embedding(
                [self._search_text(entry) for entry in self.entries])
        query = self._embedding([source])
        if not query or not self._search_vectors:
            return {"source_label": source, "canonical": None,
                    "confidence": 0.0, "method": "unresolved", "entry": None}
        scores = [_cosine(query[0], row) for row in self._search_vectors]
        order = sorted(range(len(scores)), key=lambda i: (-scores[i], i))
        best = order[0]
        runner = scores[order[1]] if len(order) > 1 else 0.0
        score = scores[best]
        if score < .42 or score - runner < .025:
            return {"source_label": source, "canonical": None,
                    "confidence": round(max(0.0, score), 6),
                    "method": "unresolved", "entry": None}
        entry = self.entries[best]
        return {"source_label": source, "canonical": entry["emotion"],
                "confidence": round(_unit(score), 6),
                "method": "local_embedding", "entry": entry}

    @staticmethod
    def _fibers(resolution: Mapping[str, Any], intensity: float) -> list[dict]:
        entry = resolution.get("entry")
        if not entry:
            return []
        routes = []
        for body_part in entry.get("body_parts") or []:
            for region, fiber in BODY_ROUTES.get(_norm(body_part), []):
                routes.append((body_part, region, fiber))
        unique = list(dict.fromkeys(routes))
        if not unique:
            return []
        # Distribute a low-gain candidate signal so a long body list does not
        # automatically dominate a short one.
        gain = .36 / math.sqrt(len(unique))
        activation = _unit(intensity) * _unit(resolution.get("confidence")) * gain
        return [{
            "source_label": resolution.get("source_label"),
            "atlas_emotion": entry["emotion"],
            "body_part": body_part, "region": region,
            "fiber_type": fiber, "activation": round(activation, 6),
            "confidence": round(_unit(resolution.get("confidence")), 6),
            "mode": "descriptive_candidate",
        } for body_part, region, fiber in unique]

    def project(self, cocktail: Mapping[str, Any]) -> dict:
        cache_key = tuple(sorted(
            (str(key), round(_unit(value), 6))
            for key, value in dict(cocktail or {}).items()))
        if cache_key == self._project_cache_key \
                and self._project_cache is not None:
            return copy.deepcopy(self._project_cache)
        resolutions, fibers = [], []
        needs = {need: 0.0 for need in NEEDS}
        color_rows, color_weights = [], []
        for source_label, raw_intensity in dict(cocktail or {}).items():
            intensity = _unit(raw_intensity)
            if intensity <= 0.0:
                continue
            resolution = self.resolve(str(source_label))
            public = {key: resolution.get(key) for key in (
                "source_label", "canonical", "confidence", "method")}
            resolutions.append(public)
            entry = resolution.get("entry")
            if not entry:
                continue
            weight = intensity * _unit(resolution.get("confidence"))
            need = entry["default_system_need"]
            needs[need] = 1.0 - (1.0 - needs[need]) * (1.0 - weight)
            vector = color_vector(entry.get("colors") or [])
            if vector:
                color_rows.append([vector[key] for key in (
                    "red", "green", "blue", "luma", "chroma", "warmth")])
                color_weights.append(weight)
            fibers.extend(self._fibers(resolution, intensity))
        color = {}
        if color_rows:
            total = sum(color_weights)
            keys = ("red", "green", "blue", "luma", "chroma", "warmth")
            color = {key: round(sum(row[i] * weight
                                    for row, weight in zip(
                                        color_rows, color_weights)) / total, 6)
                     for i, key in enumerate(keys)}
            color["present"] = round(1.0 - math.prod(
                1.0 - _unit(weight) for weight in color_weights), 6)
        result = {
            "schema": 1, "enabled": self.enabled,
            "resolutions": resolutions, "fibers": fibers,
            "needs": {need: round(value, 6) for need, value in needs.items()},
            "color": color,
        }
        self._project_cache_key = cache_key
        self._project_cache = copy.deepcopy(result)
        return result

    def intention_need_affinity(self, text: str,
                                cocktail: Mapping[str, Any]) -> float:
        """Semantic fit between an existing intention and current need vector."""
        projected = self.project(cocktail)
        active = [(need, value) for need, value in projected["needs"].items()
                  if value > 0.0]
        text = str(text or "").strip()
        if not text or not active:
            return 0.0
        cache_key = hashlib.sha256(text.encode("utf-8")).hexdigest()
        text_vector = self._text_vector_cache.get(cache_key)
        if text_vector is None:
            rows = self._embedding([text])
            text_vector = rows[0] if rows else False
            self._text_vector_cache[cache_key] = text_vector
        if self._need_vectors is None:
            self._need_vectors = self._embedding(list(NEEDS))
        if text_vector and self._need_vectors:
            scores = {need: max(0.0, _cosine(
                text_vector, self._need_vectors[NEEDS.index(need)]))
                for need, _value in active}
        else:
            tokens = set(_norm(text).split())
            scores = {need: len(tokens & set(_norm(need).split()))
                      / max(1, len(set(_norm(need).split())))
                      for need, _value in active}
        total = sum(value for _need, value in active)
        return round(_unit(sum(value * scores[need]
                               for need, value in active) / total), 6)

    @staticmethod
    def _observed_text(observed: Mapping[str, Any]) -> str:
        def level(name, default=.5):
            value = _unit(observed.get(name), default)
            return "low" if value < .34 else "high" if value > .66 else "moderate"
        success = "completed" if bool(observed.get("model_success", True)) \
            else "failed"
        return (
            f"Model call {success}. Oscillator coherence {level('coherence')}. "
            f"Novelty pressure {level('novelty')}. Affect recurrence "
            f"{level('recurrence')}. Social coupling {level('social')}. "
            f"Somatic activation {level('body_activation')}. Action capacity "
            f"{level('capacity')}.")

    def counterfactual(self, felt: Mapping[str, Any],
                       observed: Mapping[str, Any]) -> dict:
        """Compare analogue fit with mismatched and label-removed controls.

        This method is read-only.  Its result is intended for a private shadow
        observer and contains no raw conversation or analogue text.
        """
        resolved = []
        for label, raw_intensity in dict(felt or {}).items():
            intensity = _unit(raw_intensity)
            value = self.resolve(label)
            if intensity > 0.0 and value.get("entry"):
                resolved.append((value, intensity))
        base = {
            "schema": 1, "mode": "shadow", "applied": False,
            "downstream_channels_touched": [], "external_effects": False,
            "resolved_count": len(resolved),
        }
        if not resolved:
            return {**base, "status": "no_resolved_affect"}
        if self._process_vectors is None:
            self._process_vectors = self._embedding([
                entry["process_analogue"] for entry in self.entries])
        observed_rows = self._embedding([self._observed_text(observed)])
        if not self._process_vectors or not observed_rows:
            return {**base, "status": "embedder_unavailable"}
        matched_rows, control_rows, weights = [], [], []
        controls = []
        for resolution, intensity in resolved:
            entry = resolution["entry"]
            index = self.entries.index(entry)
            matched_rows.append(self._process_vectors[index])
            weights.append(intensity * _unit(resolution.get("confidence")))
            pool = [i for i, candidate in enumerate(self.entries)
                    if candidate["default_system_need"]
                    != entry["default_system_need"]]
            digest = hashlib.sha256((
                str(resolution.get("source_label")) + "\0" + entry["emotion"]
            ).encode("utf-8")).digest()
            control_index = pool[int.from_bytes(digest[:4], "big") % len(pool)]
            controls.append(control_index)
            control_rows.append(self._process_vectors[control_index])
        matched = _mean_vector(matched_rows, weights)
        mismatched = _mean_vector(control_rows, weights)
        unlabeled = _mean_vector(self._process_vectors)
        observed_vector = observed_rows[0]
        matched_score = _cosine(observed_vector, matched)
        mismatch_score = _cosine(observed_vector, mismatched)
        unlabeled_score = _cosine(observed_vector, unlabeled)
        return {
            **base, "status": "ready",
            "embedding_model": "all-MiniLM-L6-v2",
            "matched_similarity": round(matched_score, 6),
            "mismatched_similarity": round(mismatch_score, 6),
            "label_removed_similarity": round(unlabeled_score, 6),
            "matched_minus_mismatched": round(
                matched_score - mismatch_score, 6),
            "matched_minus_label_removed": round(
                matched_score - unlabeled_score, 6),
            "control_count": len(controls),
        }

    @staticmethod
    def _seeded_index(seed: str, condition: str, offset: int,
                      width: int) -> int:
        if width <= 0:
            return 0
        digest = hashlib.sha256((
            str(seed or "") + "\0" + str(condition) + "\0" + str(offset)
        ).encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") % width

    def trace_recombination_probe(self, source_records,
                                  revision_seed: str) -> dict:
        """Build one blinded process-space arm for a real trace candidate.

        The private ``prompt_text`` is returned to the caller but must never be
        copied into a receipt.  Everything else is content-free experiment
        metadata.  This method neither changes atlas state nor creates work.
        """
        records = [dict(record or {}) for record in (source_records or [])]
        base = {
            "schema": 1,
            "mode": "controlled_private_prompt_probe",
            "status": "unavailable",
            "applied": False,
            "external_effects": False,
            "downstream_channels_touched": [],
            "source_count": len(records),
            "resolved_count": 0,
            "process_count": 0,
            "condition": None,
            "probe_digest": None,
            "prompt_text": "",
        }
        if not records or not str(revision_seed or "").strip():
            return {**base, "status": "source_evidence_unavailable"}

        aggregate = {}
        for record in records:
            snapshot = dict(record.get("emotional_snapshot") or {})
            if not snapshot:
                snapshot = dict((record.get(
                    "context_at_encoding") or {}).get("cocktail") or {})
            for label, raw_intensity in snapshot.items():
                intensity = _unit(raw_intensity)
                if intensity > 0.0:
                    aggregate[str(label)] = aggregate.get(
                        str(label), 0.0) + intensity / len(records)

        resolved = []
        seen = set()
        for label, intensity in sorted(
                aggregate.items(), key=lambda item: (-item[1], _norm(item[0]))):
            resolution = self.resolve(label)
            entry = resolution.get("entry")
            if not entry:
                continue
            index = self.entries.index(entry)
            if index in seen:
                continue
            seen.add(index)
            weight = intensity * _unit(resolution.get("confidence"))
            if weight > 0.0:
                resolved.append((index, weight))
            if len(resolved) >= 3:
                break
        if not resolved:
            return {**base, "status": "no_resolved_source_affect"}

        if self._process_vectors is None:
            self._process_vectors = self._embedding([
                entry["process_analogue"] for entry in self.entries])
        if not self._process_vectors:
            return {**base, "status": "embedder_unavailable",
                    "resolved_count": len(resolved)}

        arm_index = self._seeded_index(
            revision_seed, "condition", 0,
            len(TRACE_RECOMBINATION_CONDITIONS))
        condition = TRACE_RECOMBINATION_CONDITIONS[arm_index]
        centroid = _mean_vector(self._process_vectors)
        centrality = [1.0 - _cosine(row, centroid)
                      for row in self._process_vectors]
        selected = []
        for offset, (matched_index, _weight) in enumerate(resolved):
            matched_entry = self.entries[matched_index]
            if condition in {"matched_labeled", "matched_label_removed"}:
                selected_index = matched_index
            elif condition == "mismatched_label_removed":
                pool = [
                    index for index, entry in enumerate(self.entries)
                    if index != matched_index
                    and entry["default_system_need"] !=
                    matched_entry["default_system_need"]
                ]
                selected_index = pool[self._seeded_index(
                    revision_seed, condition, offset, len(pool))]
            elif condition == "random_label_removed":
                pool = [index for index in range(len(self.entries))
                        if index != matched_index]
                selected_index = pool[self._seeded_index(
                    revision_seed, condition, offset, len(pool))]
            elif condition == "distance_matched_random_label_removed":
                pool = [
                    index for index, entry in enumerate(self.entries)
                    if index != matched_index
                    and entry["default_system_need"] !=
                    matched_entry["default_system_need"]
                ]
                pool.sort(key=lambda index: (
                    abs(centrality[index] - centrality[matched_index]), index))
                nearest_width = max(1, int(math.sqrt(len(pool))))
                nearest = pool[:nearest_width]
                selected_index = nearest[self._seeded_index(
                    revision_seed, condition, offset, len(nearest))]
            else:
                continue
            selected.append(selected_index)

        if condition == "sham_none":
            prompt_text = ""
        else:
            lines = []
            for index in selected:
                entry = self.entries[index]
                if condition == "matched_labeled":
                    lines.append(
                        f"{entry['emotion']}: {entry['process_analogue']}")
                else:
                    lines.append(entry["process_analogue"])
            prompt_text = "\n".join(dict.fromkeys(lines))[:1800]
        probe_digest = (hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
                        if prompt_text else None)
        applied = bool(prompt_text)
        return {
            **base,
            "status": "ready",
            "condition": condition,
            "resolved_count": len(resolved),
            "process_count": len(set(selected)),
            "probe_digest": probe_digest,
            "prompt_text": prompt_text,
            "applied": applied,
            "downstream_channels_touched": (
                ["memory.narrative_appraisal_prompt"] if applied else []),
        }

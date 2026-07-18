"""Pure encode-time substrate context validation and copying."""
from __future__ import annotations

import math
from collections.abc import Mapping

import numpy as np


BAND_KEYS = ("delta", "theta", "alpha", "beta", "gamma")
CONTEXT_KEYS = frozenset({
    "schema", "bands", "coherence", "cocktail", "warmth_keys",
})


def _unit(value, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a finite number in 0..1")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a finite number in 0..1")
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"{label} must be a finite number in 0..1")
    return number


def normalize_context(value: Mapping | None) -> dict | None:
    """Validate one observed context and return a recursively detached copy."""
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TypeError("context_at_encoding must be a mapping")
    unknown = set(value) - CONTEXT_KEYS
    if unknown:
        raise ValueError(
            "unknown context_at_encoding fields: "
            + ", ".join(sorted(str(key) for key in unknown)))
    if type(value.get("schema")) is not int or value.get("schema") != 1:
        raise ValueError("context_at_encoding schema must be 1")
    result = {"schema": 1}

    if "bands" in value:
        bands = value["bands"]
        if not isinstance(bands, Mapping):
            raise TypeError("context_at_encoding bands must be a mapping")
        if set(bands) != set(BAND_KEYS):
            raise ValueError(
                "context_at_encoding bands require exactly "
                + ", ".join(BAND_KEYS))
        result["bands"] = {
            key: _unit(bands[key], f"context band {key}")
            for key in BAND_KEYS
        }

    if "coherence" in value:
        result["coherence"] = _unit(
            value["coherence"], "context coherence")

    if "cocktail" in value:
        cocktail = value["cocktail"]
        if not isinstance(cocktail, Mapping):
            raise TypeError("context_at_encoding cocktail must be a mapping")
        copied = {}
        for raw_name, raw_level in cocktail.items():
            name = str(raw_name or "").strip()
            if not name:
                raise ValueError("context cocktail keys must not be empty")
            copied[name] = _unit(
                raw_level, f"context cocktail {name}")
        result["cocktail"] = copied

    if "warmth_keys" in value:
        raw_keys = value["warmth_keys"]
        if isinstance(raw_keys, (str, bytes)) \
                or not isinstance(raw_keys, (list, tuple)):
            raise TypeError(
                "context_at_encoding warmth_keys must be a sequence")
        keys = []
        seen = set()
        for raw_key in raw_keys:
            key = str(raw_key or "").strip()
            if not key:
                raise ValueError("context warmth keys must not be empty")
            if key not in seen:
                seen.add(key)
                keys.append(key)
        result["warmth_keys"] = keys

    return result


def _observed_vector(value, keys) -> dict | None:
    """Read a stored numeric component without repairing or inventing it."""
    if not isinstance(value, Mapping) or not all(key in value for key in keys):
        return None
    observed = {}
    try:
        for key in keys:
            observed[key] = _unit(value[key], f"context component {key}")
    except (TypeError, ValueError):
        return None
    return observed


def memory_context(memory: Mapping) -> dict:
    """Project only observed recall context, with honest legacy cocktail data."""
    bound = memory.get("context_at_encoding")
    projected = dict(bound) if isinstance(bound, Mapping) else {}
    if "cocktail" not in projected:
        legacy = memory.get("emotional_snapshot")
        if isinstance(legacy, Mapping):
            projected["cocktail"] = dict(legacy)
    return projected


def context_similarity(current: Mapping, stored: Mapping) -> float | None:
    """Mean of comparable mechanical context coordinates, or no channel.

    Missing components contribute neither zero nor a fabricated match. Numeric
    state never becomes prose and never enters the semantic embedding space.
    """
    if not isinstance(current, Mapping) or not isinstance(stored, Mapping):
        return None
    similarities = []

    current_bands = _observed_vector(current.get("bands"), BAND_KEYS)
    stored_bands = _observed_vector(stored.get("bands"), BAND_KEYS)
    if current_bands is not None and stored_bands is not None:
        distance = 0.5 * sum(
            abs(current_bands[key] - stored_bands[key])
            for key in BAND_KEYS)
        similarities.append(max(0.0, min(1.0, 1.0 - distance)))

    current_coherence = current.get("coherence")
    stored_coherence = stored.get("coherence")
    try:
        if current_coherence is not None and stored_coherence is not None:
            left = _unit(current_coherence, "current coherence")
            right = _unit(stored_coherence, "stored coherence")
            similarities.append(1.0 - abs(left - right))
    except (TypeError, ValueError):
        pass

    current_cocktail = current.get("cocktail")
    stored_cocktail = stored.get("cocktail")
    if isinstance(current_cocktail, Mapping) \
            and isinstance(stored_cocktail, Mapping):
        names = set(current_cocktail) | set(stored_cocktail)
        try:
            left = {name: _unit(current_cocktail.get(name, 0.0),
                                f"current cocktail {name}")
                    for name in names}
            right = {name: _unit(stored_cocktail.get(name, 0.0),
                                 f"stored cocktail {name}")
                     for name in names}
            denominator = sum(max(left[name], right[name]) for name in names)
            if denominator > 0.0:
                similarities.append(
                    sum(min(left[name], right[name]) for name in names)
                    / denominator)
        except (TypeError, ValueError):
            pass

    current_warmth = current.get("warmth_keys")
    stored_warmth = stored.get("warmth_keys")
    if isinstance(current_warmth, (list, tuple)) \
            and isinstance(stored_warmth, (list, tuple)):
        left = {key for key in current_warmth
                if isinstance(key, str) and key}
        right = {key for key in stored_warmth
                 if isinstance(key, str) and key}
        union = left | right
        if union:
            similarities.append(len(left & right) / len(union))

    if not similarities:
        return None
    return sum(similarities) / len(similarities)


def _valid_unit_or_none(value) -> float | None:
    try:
        return _unit(value, "context index value")
    except (TypeError, ValueError):
        return None


def _valid_cocktail(value) -> dict | None:
    if not isinstance(value, Mapping):
        return None
    result = {}
    for raw_name, raw_level in value.items():
        name = str(raw_name or "").strip()
        level = _valid_unit_or_none(raw_level)
        if not name or level is None:
            return None
        result[name] = level
    return result


class ContextCueIndex:
    """Derived numeric projection of stored context for bounded top-K cueing.

    This is not a second embedding or source of truth. It preserves the exact
    component formulas in ``context_similarity`` and is rebuilt from memory
    records at organ construction. New encodes enter a small pending tail so
    encode remains a copy-only boundary rather than rebuilding an N-row
    matrix during a turn.
    """

    def __init__(self, memories):
        self._base_ids = [memory["id"] for memory in memories]
        self._row = {memory_id: row
                     for row, memory_id in enumerate(self._base_ids)}
        self._pending = []
        contexts = [memory_context(memory) for memory in memories]
        cocktail_keys = set()
        valid_cocktails = []
        for context in contexts:
            cocktail = _valid_cocktail(context.get("cocktail"))
            valid_cocktails.append(cocktail)
            if cocktail is not None:
                cocktail_keys.update(cocktail)
        self._cocktail_keys = tuple(sorted(cocktail_keys))
        self._cocktail_column = {
            key: column for column, key in enumerate(self._cocktail_keys)}

        count = len(contexts)
        self._bands = np.zeros((count, len(BAND_KEYS)), dtype=np.float32)
        self._bands_mask = np.zeros(count, dtype=bool)
        self._coherence = np.zeros(count, dtype=np.float32)
        self._coherence_mask = np.zeros(count, dtype=bool)
        self._cocktail = np.zeros(
            (count, len(self._cocktail_keys)), dtype=np.float32)
        self._cocktail_mask = np.zeros(count, dtype=bool)
        self._warmth = []

        for row, context in enumerate(contexts):
            bands = _observed_vector(context.get("bands"), BAND_KEYS)
            if bands is not None:
                self._bands[row] = [bands[key] for key in BAND_KEYS]
                self._bands_mask[row] = True

            coherence = _valid_unit_or_none(context.get("coherence"))
            if coherence is not None:
                self._coherence[row] = coherence
                self._coherence_mask[row] = True

            cocktail = valid_cocktails[row]
            if cocktail is not None:
                for key, value in cocktail.items():
                    self._cocktail[row, self._cocktail_column[key]] = value
                self._cocktail_mask[row] = True

            raw_warmth = context.get("warmth_keys")
            if isinstance(raw_warmth, (list, tuple)):
                warmth = frozenset(
                    key for key in raw_warmth
                    if isinstance(key, str) and key)
            else:
                warmth = None
            self._warmth.append(warmth)

    @property
    def size(self) -> int:
        return len(self._base_ids) + len(self._pending)

    def add(self, memory) -> None:
        """Admit one new record without O(n) encode-time rebuilding."""
        self._pending.append((memory["id"], memory_context(memory)))

    def checkpoint(self) -> int:
        """Mark the reversible pending tail before a canonical transaction."""
        return len(self._pending)

    def rollback_pending(self, checkpoint: int) -> None:
        """Forget only rows appended after a failed canonical transaction."""
        checkpoint = int(checkpoint)
        if checkpoint < 0 or checkpoint > len(self._pending):
            raise ValueError("invalid context pending checkpoint")
        del self._pending[checkpoint:]

    def _base_similarities(self, current: Mapping) -> np.ndarray:
        count = len(self._base_ids)
        totals = np.zeros(count, dtype=np.float32)
        components = np.zeros(count, dtype=np.uint8)

        current_bands = _observed_vector(current.get("bands"), BAND_KEYS)
        if current_bands is not None and count:
            vector = np.asarray(
                [current_bands[key] for key in BAND_KEYS], dtype=np.float32)
            similarity = 1.0 - 0.5 * np.abs(self._bands - vector).sum(axis=1)
            np.clip(similarity, 0.0, 1.0, out=similarity)
            totals[self._bands_mask] += similarity[self._bands_mask]
            components[self._bands_mask] += 1

        current_coherence = _valid_unit_or_none(current.get("coherence"))
        if current_coherence is not None and count:
            similarity = 1.0 - np.abs(self._coherence - current_coherence)
            totals[self._coherence_mask] += similarity[self._coherence_mask]
            components[self._coherence_mask] += 1

        current_cocktail = _valid_cocktail(current.get("cocktail"))
        if current_cocktail is not None and count:
            vector = np.zeros(len(self._cocktail_keys), dtype=np.float32)
            unknown_total = 0.0
            for key, value in current_cocktail.items():
                column = self._cocktail_column.get(key)
                if column is None:
                    unknown_total += value
                else:
                    vector[column] = value
            numerator = np.minimum(self._cocktail, vector).sum(axis=1)
            denominator = (
                np.maximum(self._cocktail, vector).sum(axis=1)
                + unknown_total)
            mask = self._cocktail_mask & (denominator > 0.0)
            totals[mask] += numerator[mask] / denominator[mask]
            components[mask] += 1

        raw_current_warmth = current.get("warmth_keys")
        if isinstance(raw_current_warmth, (list, tuple)):
            current_warmth = {
                key for key in raw_current_warmth
                if isinstance(key, str) and key}
            for row, stored_warmth in enumerate(self._warmth):
                if stored_warmth is None:
                    continue
                union = current_warmth | stored_warmth
                if union:
                    totals[row] += len(current_warmth & stored_warmth) \
                        / len(union)
                    components[row] += 1

        result = np.full(count, np.nan, dtype=np.float32)
        mask = components > 0
        result[mask] = totals[mask] / components[mask]
        return result

    def top_k_with_coverage(
            self, current: Mapping, eligible_ids, k: int) -> tuple[list[str], int]:
        """Return deterministic top-K IDs and comparable-record coverage."""
        if k <= 0:
            return [], 0
        base_scores = self._base_similarities(current)
        pending = {memory_id: context
                   for memory_id, context in self._pending}
        ranked = []
        for order, memory_id in enumerate(eligible_ids):
            row = self._row.get(memory_id)
            if row is not None:
                score = float(base_scores[row])
                if math.isnan(score):
                    continue
            elif memory_id in pending:
                score = context_similarity(current, pending[memory_id])
                if score is None:
                    continue
            else:
                continue
            ranked.append((score, order, memory_id))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return [item[2] for item in ranked[:k]], len(ranked)

    def top_k(self, current: Mapping, eligible_ids, k: int) -> list[str]:
        """Return deterministic top-K IDs among the already-admitted set."""
        return self.top_k_with_coverage(current, eligible_ids, k)[0]

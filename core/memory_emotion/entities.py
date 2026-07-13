"""core/memory_emotion/entities.py — entity cards (2026-07-12).
v1 parity: 'who is X' is a LOOKUP, not a recall auction. Cards are
a curated port of v1's entity_graph (the lossless graph stays in the
migration snapshot); this module is pure — load, detect mentions,
render ground-truth cards. The contract gates rendering on company
clearance (cards carry household-private facts; discretion law).

Short-alias law: aliases of <= 3 chars match CASE-SENSITIVELY on
word boundaries ('Re' must not match \"you're\"); longer aliases
match case-insensitively."""
import json
import math
import os
import re


class EntityCards:
    # A referent estimate must be supported by more than a bare plurality.
    # The estimate below blends recency, source reliability, topic
    # prominence, recurrence, and candidate ambiguity before it reaches
    # this floor.  No polling or elapsed-time trigger is involved.
    REFERENT_CONFIDENCE_FLOOR = 0.50
    _REFERENTIAL = re.compile(
        r"\b(?:she|her|hers|herself|he|him|his|himself|"
        r"they|them|their|theirs|themself|themselves)\b",
        re.IGNORECASE)

    def __init__(self, organ_dir: str):
        self.path = os.path.join(organ_dir, "entities.json")
        self.cards = {}
        self._alias = []          # (compiled_regex, name)
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    self.cards = json.load(f)
            except Exception as e:
                print(f"[entities] load failed ({e}) — cards off")
                self.cards = {}
        for name, c in self.cards.items():
            for a in c.get("aliases") or [name]:
                a = (a or "").strip()
                if not a:
                    continue
                flags = 0 if len(a) <= 3 else re.IGNORECASE
                self._alias.append(
                    (re.compile(rf"\b{re.escape(a)}\b", flags), name))

    def mentioned(self, text: str) -> list:
        """Card names mentioned in text, first-mention order."""
        if not text or not self.cards:
            return []
        found = []
        for rx, name in self._alias:
            m = rx.search(text)
            if m and name not in [n for n, _p in found]:
                found.append((name, m.start()))
        return [n for n, _p in sorted(found, key=lambda x: x[1])]

    @staticmethod
    def _band(value: float, radius: float):
        """Approximate confidence as a range, rounded to 5% bands."""
        low = max(0.0, value - radius)
        high = min(0.99, value + radius)
        return [round(low * 20) / 20, round(high * 20) / 20]

    def _referent_estimate(self, window: list, exclude_names=None):
        """Return a weighted referent estimate from the working window.

        Evidence is a vector, not a last-name switch:

          contribution = recency * source_reliability * topic_prominence

        Contributions recur across the whole supplied window.  Candidate
        ambiguity and total evidence strength then temper the normalized
        lead.  The window length supplies the recency half-life, so the
        formula scales with the continuity system instead of introducing a
        second arbitrary clock.
        """
        window = list(window or [])
        if not window:
            return None
        excluded = {str(name).lower() for name in (exclude_names or [])}
        half_life = max(1.0, len(window) / 2.0)
        scores = {}
        traces = {}

        def add(text, *, source, reliability, recency):
            names = self.mentioned(text)
            for topic_rank, name in enumerate(names):
                if name.lower() in excluded:
                    continue
                prominence = 1.0 / (1.0 + topic_rank)
                value = recency * reliability * prominence
                scores[name] = scores.get(name, 0.0) + value
                trace = traces.setdefault(name, {})
                trace[source] = trace.get(source, 0.0) + value

        newest = len(window) - 1
        for index, mem in enumerate(window):
            distance = newest - index
            recency = math.pow(0.5, distance / half_life)
            fields = mem.get("fields") or {}

            # A resolution produced by the previous cycle is structured
            # evidence.  User language is next-most reliable; model language
            # remains useful for topic continuity but cannot dominate alone.
            structured = fields.get("resolved_entities") or []
            for topic_rank, name in enumerate(structured):
                if name not in self.cards or name.lower() in excluded:
                    continue
                prominence = 1.0 / (1.0 + topic_rank)
                value = recency * 1.25 * prominence
                scores[name] = scores.get(name, 0.0) + value
                trace = traces.setdefault(name, {})
                trace["structured"] = trace.get("structured", 0.0) + value

            add(fields.get("message_full"), source="user",
                reliability=1.0, recency=recency)
            add(fields.get("reply_full"), source="model",
                reliability=0.70, recency=recency)
            if not fields.get("message_full") \
                    and not fields.get("reply_full"):
                add(mem.get("content"), source="legacy",
                    reliability=0.55, recency=recency)

        if not scores:
            return None
        ranked = sorted(scores.items(), key=lambda item: -item[1])
        name, top = ranked[0]
        total = sum(scores.values())
        share = top / total
        strength = 1.0 - math.exp(-top)
        confidence = share * strength
        radius = 0.05 + 0.15 * (1.0 - strength) \
            + 0.10 * (1.0 - share)
        return {
            "name": name,
            "confidence_estimate": round(confidence, 3),
            "confidence_range": self._band(confidence, radius),
            "threshold": self.REFERENT_CONFIDENCE_FLOOR,
            "candidate_scores": {
                n: round(score, 3) for n, score in ranked
            },
            "evidence": {
                source: round(value, 3)
                for source, value in traces.get(name, {}).items()
            },
        }

    def resolve(self, text: str, window=None, max_cards: int = 2,
                exclude_names=None):
        """Resolve entity cards for this turn.

        Literal names in the current message always win.  If there is no
        literal name and the message contains a third-person reference,
        inherit the topic entity from the immediate conversation window.
        This is intentionally narrow: ordinary messages never acquire a
        card merely because somebody happened to be discussed recently.

        Returns ``(names, inferred_names, estimate)``.  At most one name is
        inherited; a bare pronoun cannot safely refer to two people at once.
        """
        explicit = self.mentioned(text)[:max_cards]
        if explicit:
            return explicit, [], None
        if not text or not self._REFERENTIAL.search(text):
            return [], [], None

        estimate = self._referent_estimate(window, exclude_names)
        if not estimate or estimate["confidence_estimate"] \
                < self.REFERENT_CONFIDENCE_FLOOR:
            return [], [], estimate
        inferred = [estimate["name"]]
        return inferred, inferred, estimate

    @staticmethod
    def _card_line(c: dict) -> str:
        bits = [f"{c['name']} — {c.get('type', 'entity')}"]
        at = c.get("attributes") or {}
        # Identity relations are present-tense record facts.  Everything
        # else came from a historical snapshot and stays explicitly framed
        # as such; it does not silently become current state.
        for k in ("relation_to_Re", "species"):
            if k in at:
                bits.append(f"{k.replace('_', ' ')}: {at[k]['value']}")
        line = ". ".join(bits) + "."
        snapshot = []
        for k, v in at.items():
            if k not in ("relation_to_Re", "species") \
                    and len(snapshot) < 4:
                snapshot.append(f"{k.replace('_', ' ')}: {v['value']}")
        if snapshot:
            line += (" Recorded snapshot (may have changed): "
                     + "; ".join(snapshot) + ".")
        edges = [e.replace("::", " ") for e in
                 (c.get("edges") or [])[:3]]
        if edges:
            line += " Recorded relational history: " \
                + "; ".join(edges) + "."
        return "- " + line

    def _render_names(self, names: list, estimate=None):
        if not names:
            return ""
        lines = [
            "Who's who — the household record. Identity relations below "
            "are established facts. Snapshot attributes and relational "
            "edges are documented history, not guaranteed present state. "
            "A conflicting category claim in conversation remains "
            "historical error, not an alternate identity fact."
        ]
        if estimate:
            low, high = estimate["confidence_range"]
            lines.append(
                f"The current referent estimate is {estimate['name']} "
                f"(approximate confidence range: {low:.0%}–{high:.0%}), "
                "from the recent conversation's recency, source, topic "
                "prominence, recurrence, and ambiguity.")
        lines.extend(self._card_line(self.cards[n]) for n in names)
        return "\n".join(lines)

    def render(self, text: str, max_cards: int = 2):
        """(block, names) — ground-truth cards for entities the text
        names. Empty block when nothing matches; caller receipts."""
        names = self.mentioned(text)[:max_cards]
        return self._render_names(names), names

    def render_context(self, text: str, window=None, max_cards: int = 2,
                       exclude_names=None):
        """(block, names, inferred_names, estimate) for this turn."""
        names, inferred, estimate = self.resolve(
            text, window, max_cards=max_cards,
            exclude_names=exclude_names)
        return self._render_names(names, estimate), names, inferred, estimate

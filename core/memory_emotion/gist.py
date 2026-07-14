"""gist — the rolling middle-distance memory (v1 RollingSummarizer, ported).

The three-layer continuity stack, middle layer: working window (verbatim,
perception) -> THIS (compressed, story) -> episodic recall (scored, emotional).

v1 lessons kept: absolute cursor so nothing can desync; fold-forward
("PREVIOUS RUNNING MEMORY + NEW TURNS -> UPDATED"); honest failure (a dead
judge call never eats the existing gist).
v1 lessons FIXED: the gist PERSISTS (v1's died with the session — v2 runs
as one constant life, STOP_NEXUS is a nap, not a death); speaker-aware
rendering (no hardcoded speaker-name bake-in);
the fold source is the organ's own turn records (ONE store, no side buffer
to drift — the cursor is an index into an append-only sequence, slide-safe
because nothing slides).
Cost law: one judge call per fold, folds every `update_every` turns —
an API-cost organ, opt-in like `feel` (par 2.6)."""
import json
import os
import sys
import time

_SYSTEM = (
    "You maintain a persona's running memory of an ongoing life — one "
    "continuous session across restarts. Fold the NEW TURNS into the "
    "PREVIOUS RUNNING MEMORY. Keep: facts learned, names, decisions, "
    "promises, open threads, emotional beats and how they resolved. "
    "Drop: pleasantries, repetition, play-by-play. Write in plain "
    "third person, dense, chronological where it matters, about "
    "{target_words} words. Output ONLY the updated running memory — "
    "no preamble, no headers.")


def _log(message: str) -> None:
    """Write diagnostics without letting a Windows codepage kill the organ."""
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    safe = str(message).encode(encoding, errors="backslashreplace").decode(
        encoding)
    print(safe)


def render_turn(mem: dict) -> str:
    """One turn record -> transcript lines. fields carries FULL text and
    real speaker names; content is the recall-facing fallback."""
    f = mem.get("fields") or {}
    if f.get("message_full") or f.get("reply_full"):
        spk = f.get("speaker", "someone")
        who = f.get("persona", "persona")
        ch = f" [{f['channel']}]" if f.get("channel") else ""
        lines = []
        if f.get("message_full"):
            lines.append(f"{spk}{ch}: {f['message_full']}")
        if f.get("reply_full"):
            lines.append(f"{who}: {f['reply_full']}")
        return "\n".join(lines)
    return mem.get("content", "")


class RollingGist:
    """Owns rolling_gist.json in the persona's memory_emotion dir.
    Cursor `upto` = how many turn-records have been folded (an index
    into the organ's append-only turn sequence)."""

    def __init__(self, persona_dir: str, judge=None, *,
                 verbatim_window: int = 6, update_every: int = 4,
                 target_words: int = 350, max_tokens: int = 700,
                 source_char_budget: int = None):
        self.dir = os.path.join(persona_dir, "body", "memory_emotion")
        os.makedirs(self.dir, exist_ok=True)
        self.path = os.path.join(self.dir, "rolling_gist.json")
        self.judge = judge
        self.verbatim_window = int(verbatim_window)
        self.update_every = int(update_every)
        self.target_words = int(target_words)
        self.max_tokens = int(max_tokens)
        # Approximate 4 chars/token and an 8:1 source-to-summary fold. The
        # budget therefore moves with the requested output rather than being
        # an unrelated page-size constant.
        self.source_char_budget = int(
            source_char_budget if source_char_budget is not None
            else self.max_tokens * 4 * 8)
        self.last_error = None
        st = {}
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    st = json.load(f)
            except Exception as e:
                # unreadable state must not kill a boot; start empty,
                # say so loudly
                _log(f"[gist] state unreadable ({e}); starting empty")
        self.gist = st.get("gist", "")
        self.upto = int(st.get("upto", 0))
        self.idle_ids = list(st.get("idle_ids", []))

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"gist": self.gist, "upto": self.upto,
                       "idle_ids": self.idle_ids[-500:],
                       "updated": time.strftime("%Y-%m-%dT%H:%M:%S")},
                      f, indent=1, ensure_ascii=False)

    def should_update(self, n_turns: int) -> bool:
        """True when enough turns have aged past the verbatim window
        since the last fold. n_turns = total turn-records in the organ."""
        eligible = n_turns - self.verbatim_window
        return (eligible - self.upto) >= self.update_every

    def _batch(self, records: list, renderer) -> tuple[str, int]:
        """Take the next contiguous fold that fits the compression budget.

        The cursor advances only by the returned count. A single oversized
        record is represented by its beginning and end; the full record stays
        untouched in memory.
        """
        parts = []
        used = 0
        marker = "\n...[middle omitted from this gist fold]...\n"
        for record in records:
            rendered = renderer(record)
            separator = 1 if parts else 0
            remaining = self.source_char_budget - used - separator
            if remaining <= 0:
                break
            if len(rendered) > remaining:
                if parts:
                    break
                room = max(0, remaining - len(marker))
                head = room // 2
                tail = room - head
                rendered = (rendered[:head] + marker
                            + (rendered[-tail:] if tail else ""))
            parts.append(rendered)
            used += separator + len(rendered)
            if len(rendered) >= remaining:
                break
        return "\n".join(parts), len(parts)

    def update(self, turn_records: list, force: bool = False) -> bool:
        """Fold newly-aged-out turns into the gist. turn_records is the
        organ's FULL chronological turn sequence (append-only).
        Returns True if the gist changed. A failed judge call NEVER
        eats the existing gist — cursor and text both stand."""
        n = len(turn_records)
        fold_upto = n - self.verbatim_window     # exclusive index
        if fold_upto <= self.upto:
            return False
        if not force and (fold_upto - self.upto) < self.update_every:
            return False
        if self.judge is None:
            return False
        eligible = turn_records[self.upto:fold_upto]
        rendered, consumed = self._batch(eligible, render_turn)
        if not consumed:
            return False
        batch_upto = self.upto + consumed
        try:
            raw = self.judge.chat(
                _SYSTEM.format(target_words=self.target_words),
                f"PREVIOUS RUNNING MEMORY:\n"
                f"{self.gist or '(nothing yet — this is the start)'}\n\n"
                f"NEW TURNS:\n{rendered}\n\n"
                f"UPDATED RUNNING MEMORY:",
                max_tokens=self.max_tokens, temperature=0.0)
            text = (raw or "").strip()
            if not text:
                self.last_error = "empty gist from judge; kept prior"
                _log(f"[gist] {self.last_error}")
                return False
            self.gist = text
            self.upto = batch_upto
            self.last_error = None
            self.save()
            return True
        except Exception as e:
            self.last_error = f"fold failed: {e}"
            _log(f"[gist] {self.last_error}; prior gist stands")
            return False

    def update_idle(self, records: list) -> bool:
        """Fold new gist-eligible idle experiences into the same life story.

        A separate id cursor preserves the existing absolute turn cursor.  A
        failed fold consumes nothing, exactly like update().
        """
        seen = set(self.idle_ids)
        pending = [m for m in records
                   if m.get("id") not in seen
                   and (m.get("fields") or {}).get("gist_eligible")]
        if not pending or self.judge is None:
            return False
        rendered, consumed = self._batch(
            pending,
            lambda m: (f"Private {m.get('type', 'idle')} experience: "
                       f"{m.get('content', '')}"))
        if not consumed:
            return False
        batch = pending[:consumed]
        try:
            raw = self.judge.chat(
                _SYSTEM.format(target_words=self.target_words),
                f"PREVIOUS RUNNING MEMORY:\n"
                f"{self.gist or '(nothing yet — this is the start)'}\n\n"
                f"NEW PRIVATE EXPERIENCES:\n{rendered}\n\n"
                "UPDATED RUNNING MEMORY:",
                max_tokens=self.max_tokens, temperature=0.0)
            text = (raw or "").strip()
            if not text:
                self.last_error = "empty idle gist from judge; kept prior"
                return False
            self.gist = text
            self.idle_ids.extend(m["id"] for m in batch)
            self.last_error = None
            self.save()
            return True
        except Exception as e:
            self.last_error = f"idle fold failed: {e}"
            _log(f"[gist] {self.last_error}; prior gist stands")
            return False

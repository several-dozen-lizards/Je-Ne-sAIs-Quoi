"""core/room_actions.py — volitional room action parsing (the <face> tag
pattern, generalized: the persona ACTS by emitting tags inline; we parse
post-reply, execute, and the consequences arrive as tomorrow's percepts.
Walking is an event — you act, then the world answers, next turn).

Grammar (tiny, fine-tune-inheritable):
  <act>move_to OBJECT</act>
  <act>contact OBJECT</act>
  <act>read OBJECT</act>
  <act>travel ROOM</act>
  <act>write OBJECT :: free text to write</act>

Pure module: parse + strip only. Execution lives with the RoomClient
caller. Unknown verbs parse as {"verb": "?", ...} and execute as errors —
the world refuses, the refusal is a percept, that's honest too."""
import re

ACT_RE = re.compile(r"<act>(.*?)</act>", re.DOTALL)
VERBS = {"move_to", "contact", "read", "travel", "write"}


def parse_actions(reply: str) -> list:
    """Extract action dicts in order of appearance."""
    out = []
    for raw in ACT_RE.findall(reply or ""):
        body = raw.strip()
        if "::" in body:
            head, text = body.split("::", 1)
            parts = head.strip().split(None, 1)
            verb = parts[0] if parts else "?"
            target = parts[1].strip() if len(parts) > 1 else ""
            out.append({"verb": verb, "target": target,
                        "text": text.strip()})
        else:
            parts = body.split(None, 1)
            verb = parts[0] if parts else "?"
            target = parts[1].strip() if len(parts) > 1 else ""
            out.append({"verb": verb, "target": target, "text": None})
    return out


def strip_actions(reply: str) -> str:
    """Remove act tags; collapse the whitespace they leave behind."""
    s = ACT_RE.sub("", reply or "")
    return re.sub(r"[ \t]*\n{3,}", "\n\n", s).strip()

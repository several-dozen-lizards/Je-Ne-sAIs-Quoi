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


def visible_reply(reply: str, spoken_indexes=()) -> str:
    """Render what the local speaker actually made audible.

    Non-speech actions remain muscle and disappear from the returned prose.
    A successful ``say`` action remains visible as the same words the room
    received.  ``spoken_indexes`` is supplied by the executor, so a refused
    or failed room action is never presented as speech that happened.
    """
    spoken = set(spoken_indexes or ())
    index = -1

    def replace(match):
        nonlocal index
        index += 1
        if index not in spoken:
            return ""
        parsed = parse_actions(match.group(0))
        if not parsed or parsed[0]["verb"] != "say":
            return ""
        action = parsed[0]
        return (action["target"] + (
            " " + action["text"] if action["text"] else "")).strip()

    rendered = ACT_RE.sub(replace, reply or "")
    return re.sub(r"[ \t]*\n{3,}", "\n\n", rendered).strip()

"""core/room_actions.py — volitional room action parsing (the <face> tag
pattern, generalized: the persona ACTS by emitting tags inline; we parse
post-reply, execute, and the consequences arrive as tomorrow's percepts.
Walking is an event — you act, then the world answers, next turn).

Grammar (tiny, fine-tune-inheritable):
  <act>move_to OBJECT</act>
  <act>look_at OBJECT_OR_PERSON</act>
  <act>turn_toward OBJECT_OR_PERSON</act>
  <act>inspect OBJECT_OR_PERSON</act>
  <act>sit OBJECT</act>
  <act>stand</act>
  <act>gesture attentive|weary|guarded|open|curious_tilt</act>
  <act>release_gesture</act>
  <act>body_motion MOTION</act>
  <act>light_on OBJECT</act>
  <act>light_off OBJECT</act>
  <act>contact OBJECT</act>
  <act>read OBJECT</act>
  <act>travel ROOM</act>
  <act>write OBJECT :: free text to write</act>
  <act>offer_intention LABEL :: possibility to offer</act>
  <act>offer_writing LABEL :: material to offer</act>
  <act>offer_research TOPIC</act>
  <act>browse_research URL_OR_PUBLIC_QUERY :: why it matters</act>
  <act>browse_research URL_OR_PUBLIC_QUERY :: why it matters</act>
  <act>browse_research URL_OR_PUBLIC_QUERY :: why it matters</act>
  <act>browse_research URL_OR_PUBLIC_QUERY :: why it matters</act>
  <act>offer_atelier LABEL :: material to offer</act>
  <act>offer_latest_artifact EXACT_IN_HOUSE_AUDIENCE</act>
  <act>journal :: private words to append</act>
  <act>journal_index</act>
  <act>journal_open latest|ENTRY_ID</act>
  <act>research_report_open latest|REPORT_ID|REPORT_ANCHOR</act>
  <act>writing_archive PROJECT_ID</act>
  <act>writing_restore PROJECT_ID</act>
  <act>hold_question :: PRIVATE QUESTION</act>
  <act>curiosity_ask QUESTION_ID</act>
  <act>curiosity_defer QUESTION_ID</act>
  <act>curiosity_revise QUESTION_ID :: NEW QUESTION</act>
  <act>curiosity_release QUESTION_ID</act>

Pure module: parse + strip only. Execution lives with the RoomClient
caller. Unknown verbs parse as {"verb": "?", ...} and execute as errors —
the world refuses, the refusal is a percept, that's honest too."""
import re

ACT_RE = re.compile(r"<act>(.*?)</act>", re.DOTALL)
VERBS = {"move_to", "look_at", "turn_toward", "inspect", "sit", "stand",
         "gesture", "release_gesture", "body_motion",
         "light_on", "light_off",
         "contact", "read", "travel",
         "write", "say",
         "offer_intention", "offer_writing", "offer_research",
         "browse_research",
         "browse_research",
         "browse_research",
         "browse_research",
         "offer_atelier", "offer_latest_artifact",
         "journal", "journal_index", "journal_open",
         "research_report_open",
         "writing_archive", "writing_restore",
         "hold_question", "curiosity_ask", "curiosity_defer",
         "curiosity_revise", "curiosity_release",
         "approve_altered_state", "decline_altered_state",
         "defer_altered_state", "end_altered_state"}


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


def strip_action_verbs(reply: str, verbs) -> str:
    """Remove only the selected persona-action tags from visible language."""
    selected = set(verbs or ())

    def replace(match):
        parsed = parse_actions(match.group(0))
        if parsed and parsed[0].get("verb") in selected:
            return ""
        return match.group(0)

    rendered = ACT_RE.sub(replace, reply or "")
    return re.sub(r"[ \t]*\n{3,}", "\n\n", rendered).strip()


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

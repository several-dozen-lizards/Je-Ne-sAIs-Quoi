"""core/room_actions.py — volitional room action parsing (the <face> tag
pattern, generalized: the persona ACTS by emitting tags inline; we parse
post-reply, execute, and the consequences arrive as tomorrow's percepts.
Walking is an event — you act, then the world answers, next turn).

Grammar (tiny, fine-tune-inheritable):
  <act>move_to OBJECT</act>
  <act>walk X Y</act>
  <act>look_at OBJECT_OR_PERSON</act>
  <act>turn_toward OBJECT_OR_PERSON</act>
  <act>look_around</act>
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
  <act>board_post OBJECT :: exact freeform words to leave</act>
  <act>board_read OBJECT</act>
  <act>board_retract OBJECT :: POST_ID</act>
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
  <act>legacy_evidence_search PRIVATE_QUERY</act>
  <act>legacy_evidence_open EVIDENCE_ANCHOR</act>
  <act>legacy_evidence_previous</act>
  <act>legacy_evidence_next</act>
  <act>anthropic_conversation_search PRIVATE_QUERY</act>
  <act>anthropic_conversation_open CONVERSATION_ANCHOR</act>
  <act>anthropic_conversation_previous</act>
  <act>anthropic_conversation_next</act>
  <act>research_report_open latest|REPORT_ID|REPORT_ANCHOR</act>
  <act>research_source_read SOURCE_ID</act>
  <act>writing_archive PROJECT_ID</act>
  <act>writing_restore PROJECT_ID</act>
  <act>hold_question :: PRIVATE QUESTION</act>
  <act>curiosity_ask QUESTION_ID</act>
  <act>curiosity_defer QUESTION_ID</act>
  <act>curiosity_revise QUESTION_ID :: NEW QUESTION</act>
   <act>curiosity_release QUESTION_ID</act>
   <act>outcome_surface OUTCOME_ID</act>
   <act>outcome_hold OUTCOME_ID</act>
   <act>outcome_private OUTCOME_ID</act>
  <act>time_mark WHEN|START..END :: PRIVATE LABEL</act>
  <act>time_release MARK_ID</act>
  <act>observe_world DOMAIN :: OPTIONAL FOCUS</act>
  <act>awareness_release EPISODE_ID</act>
  <act>quiet_release</act>
  <act>memory_retain MEMORY_ID :: optional reason</act>
  <act>memory_withdraw MEMORY_ID :: optional reason</act>
  <act>memory_summarize MEMORY_ID :: replacement summary</act>
  <act>memory_restore MEMORY_ID :: optional reason</act>

Pure module: parse + strip only. Execution lives with the RoomClient
caller. Unknown verbs parse as {"verb": "?", ...} and execute as errors —
the world refuses, the refusal is a percept, that's honest too."""
import math
import re

ACT_RE = re.compile(r"<act>(.*?)</act>", re.DOTALL)
VERBS = {"move_to", "go", "walk", "look_at", "turn_toward", "look_around",
         "inspect",
         "sit", "stand",
         "gesture", "release_gesture", "body_motion",
         "light_on", "light_off",
         "contact", "read", "travel",
         "write", "say", "board_post", "board_read", "board_retract",
         "offer_intention", "offer_writing", "offer_research",
         "browse_research",
         "browse_research",
         "browse_research",
         "browse_research",
         "offer_atelier", "offer_latest_artifact",
         "journal", "journal_index", "journal_open",
         "legacy_evidence_search", "legacy_evidence_open",
         "legacy_evidence_previous", "legacy_evidence_next",
         "anthropic_conversation_search", "anthropic_conversation_open",
         "anthropic_conversation_previous", "anthropic_conversation_next",
         "research_report_open", "research_source_read",
         "writing_archive", "writing_restore",
         "hold_question", "curiosity_ask", "curiosity_defer",
         "curiosity_revise", "curiosity_release",
         "outcome_surface", "outcome_hold", "outcome_private",
         "time_mark", "time_release",
         "startup_handoff", "startup_handoff_clear",
         "observe_world", "awareness_release",
         "quiet_release",
         "memory_retain", "memory_withdraw", "memory_summarize",
         "memory_restore",
         "approve_altered_state", "decline_altered_state",
         "defer_altered_state", "end_altered_state"}


def parse_walk_target(target: str) -> tuple:
    """Parse a resident-authored absolute room vector.

    ``X Y`` chooses position and lets heading follow travel.  An optional
    third number chooses the arrival heading.  The room remains authoritative
    over support, collision, and the position that actually results.
    """
    parts = str(target or "").replace(",", " ").split()
    if len(parts) not in (2, 3):
        raise ValueError("walk needs X Y meters, optionally HEADING_DEG")
    try:
        values = tuple(float(value) for value in parts)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "walk coordinates and heading must be numeric") from exc
    if not all(math.isfinite(value) for value in values):
        raise ValueError("walk coordinates and heading must be finite")
    return values


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


def action_receipt(action: dict) -> dict:
    """Return a receipt-safe action shape for persona-private payloads."""
    value = dict(action or {})
    if (value.get("verb") == "startup_handoff"
            or value.get("verb") in {
                "legacy_evidence_search", "anthropic_conversation_search"}
            or str(value.get("verb") or "").startswith("memory_")):
        if value.get("verb") in {
                "legacy_evidence_search", "anthropic_conversation_search"}:
            value["target"] = None
        value["text"] = None
    return value


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

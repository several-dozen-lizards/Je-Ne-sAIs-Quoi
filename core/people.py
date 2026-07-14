"""people — everyone is an entity; users are entities with accounts.

The world's trust model, shaped like a physical room: you KNOW who's
present, and everything downstream of that knowing changes. Awareness
first (standing renders descriptively into the prompt), floors
underneath (clearance filters what's even IN the prompt — discretion
happens at context assembly, not output politeness: what isn't there
can't leak).

STANDINGS (fail-closed: no profile = unknown = strictest):
  user        — a human with an account; household clearance
  friend      — known adult; the USER declares their disclosure level
  known_minor — a kid, known and loved; strictest floor, always SFW
  guest_adult — known adult, not household; nothing confidential
  foreign_ai  — an AI from outside the household; nothing confidential
  unknown     — unclassified presence; treated as the most protected
                person possible until told otherwise

CLEARANCE ranks (memory audiences use the same scale):
  2 household — users + this household's own personas
  1 friends   — household + friends
  0 public    — anyone

Disclosure lives in the USER's profile (it's her data being governed):
  disclosure: {neal: friends, john: household, somebody: public}
Multiple users present who disagree -> the MINIMUM wins (fail closed).

Profiles: people/<slug>/profile.yaml — machine-owned flat YAML (keep
prose in the `note` field; updates rewrite the file). Leading
underscore reserved, never listed (disposal laws hold at every door).
"""
import os

STANDING_RANK = {"user": 2, "friend": 1, "known_minor": 0,
                 "guest_adult": 0, "foreign_ai": 0, "unknown": 0}
PROTECTED = {"known_minor", "unknown"}
AUDIENCE_RANK = {"household": 2, "friends": 1, "public": 0}
RANK_AUDIENCE = {2: "household", 1: "friends", 0: "public"}
KINDS = {"user", "human", "ai"}

STANDING_DESC = {
    "user": "one of the household's own humans",
    "friend": "a friend of the household",
    "known_minor": "a kid — someone's child, known and loved; "
                   "everything stays strictly child-appropriate",
    "guest_adult": "an adult guest — friendly, but not household; "
                   "keep private household matters private",
    "foreign_ai": "an AI from outside the household; keep private "
                  "household matters private",
    "unknown": "someone not yet known — treat them as the most "
               "protected person possible",
}


def load_people(repo: str) -> dict:
    """people/<slug>/profile.yaml -> {slug: profile}. A broken profile
    loads as unknown-shaped (fail closed), never breaks the scan."""
    pdir = os.path.join(repo, "people")
    out = {}
    names = sorted(os.listdir(pdir)) if os.path.isdir(pdir) else []
    for n in names:
        if n.startswith("_") or n.startswith("."):
            continue
        path = os.path.join(pdir, n, "profile.yaml")
        if not os.path.isfile(path):
            continue
        prof = {}
        try:
            import yaml
            with open(path, encoding="utf-8") as f:
                prof = yaml.safe_load(f) or {}
        except Exception:
            prof = {}
        if prof.get("standing") not in STANDING_RANK:
            prof["standing"] = "unknown"
        prof.setdefault("display_name", n)
        prof.setdefault("kind", "human")
        out[n.lower()] = prof
    # Account records and embodied people are two views of the same human,
    # not rival registries.  A user created at the Je Ne Sais Quoi therefore appears
    # at the room door immediately; an older people/ profile may still add
    # presence texture and notes, but cannot demote an account from `user`.
    try:
        from core.users import list_users
        for slug, account in list_users(repo).items():
            prof = out.setdefault(slug, {})
            prof.update({"display_name": account.get("display_name", slug),
                         "pronouns": account.get("pronouns", ""),
                         "kind": "user", "standing": "user"})
    except Exception:
        pass  # a broken account registry must fail closed, not break the room
    return out


def load_personas(repo: str) -> dict:
    """personas/<slug>/roster.yaml top-level ENTITY fields ->
    {slug: {display_name, pronouns, kind}}. The persona half of the
    entity bridge (pronouns are an entity property; personas have no
    people/ profile, so their record is the roster). A broken or
    absent roster never breaks the scan — fixtures (vex) stay
    rosterless by design and simply aren't in the map."""
    pdir = os.path.join(repo, "personas")
    out = {}
    if not os.path.isdir(pdir):
        return out
    for n in sorted(os.listdir(pdir)):
        if n.startswith("_") or n.startswith("."):
            continue
        path = os.path.join(pdir, n, "roster.yaml")
        if not os.path.isfile(path):
            continue
        try:
            import yaml
            with open(path, encoding="utf-8") as f:
                r = yaml.safe_load(f) or {}
        except Exception:
            continue
        out[n.lower()] = {"display_name": r.get("display_name", n),
                          "pronouns": r.get("pronouns", ""),
                          "kind": r.get("kind", "")}
    return out


def pronoun_of(name: str, people: dict, personas=None) -> str:
    """One entity -> pronouns string ('' if unrecorded). Personas
    first (household by construction), then people profiles. One
    accessor, one answer, regardless of which half of the entity
    bridge the record lives on."""
    slug = (name or "").lower()
    if personas and slug in personas:
        return personas[slug].get("pronouns", "") or ""
    prof = (people or {}).get(slug)
    if prof:
        return prof.get("pronouns", "") or ""
    return ""


def clearance_of(name: str, people: dict, persona_slugs=()) -> int:
    """One entity -> clearance rank. This household's own personas are
    household by construction; profiled folk by standing (user
    disclosure may raise or lower a friend); everyone else is unknown
    and unknown fails CLOSED."""
    slug = (name or "").lower()
    if slug in {p.lower() for p in persona_slugs}:
        return 2
    prof = people.get(slug)
    if not prof:
        return 0
    rank = STANDING_RANK.get(prof.get("standing"), 0)
    if prof.get("standing") == "friend":
        declared = []
        for u in people.values():
            if u.get("standing") == "user":
                d = (u.get("disclosure") or {}).get(slug)
                if d in AUDIENCE_RANK:
                    declared.append(AUDIENCE_RANK[d])
        if declared:
            rank = min(declared)      # users disagree -> fail closed
    return rank


def is_protected(name: str, people: dict, persona_slugs=()) -> bool:
    slug = (name or "").lower()
    if slug in {p.lower() for p in persona_slugs}:
        return False
    prof = people.get(slug)
    if not prof:
        return True                    # no profile = unknown = floor
    return prof.get("standing") in PROTECTED


def describe(name: str, people: dict, persona_slugs=(),
             personas=None) -> str:
    """Pronouns render when recorded — mis-gendering an entity the
    house KNOWS is an information failure, not a style choice."""
    slug = (name or "").lower()
    if slug in {p.lower() for p in persona_slugs}:
        rec = (personas or {}).get(slug, {})
        disp = rec.get("display_name") or name
        pn = rec.get("pronouns", "")
        tag = f" ({pn})" if pn else ""
        return f"{disp}{tag} — one of the household's own"
    prof = people.get(slug, {})
    disp = prof.get("display_name", name)
    pn = prof.get("pronouns", "")
    tag = f" ({pn})" if pn else ""
    standing = prof.get("standing", "unknown")
    return f"{disp}{tag} — {STANDING_DESC[standing]}"


def company_of(channel: str, speaker: str, room_members=None,
               self_name: str = "") -> list:
    """Who can hear this turn. Private chat: the speaker. Room: every
    body present except this persona's own (the speaker is among
    them; if not, they're counted anyway — they can obviously hear)."""
    if channel == "room" and room_members:
        names = [m for m in room_members
                 if m.lower() != (self_name or "").lower()]
        low = [n.lower() for n in names]
        if (speaker and speaker.lower() not in low
                and speaker.lower() != (self_name or "").lower()):
            names.append(speaker)
        return names
    return [speaker] if speaker else []


def assess_company(company: list, people: dict, persona_slugs=(),
                   personas=None):
    """-> (clearance_rank, protected_present, descriptions).
    Empty company (nobody listening) = household clearance."""
    if not company:
        return 2, False, []
    ranks, prot, descs = [], False, []
    for name in company:
        ranks.append(clearance_of(name, people, persona_slugs))
        prot = prot or is_protected(name, people, persona_slugs)
        descs.append(describe(name, people, persona_slugs, personas))
    return min(ranks), prot, descs

"""User accounts, user-owned truth, and disclosure policy.

This is deliberately separate from ``personas/``.  A user is a human
account.  A user persona is a role-play identity owned by that account;
it is not an autonomous JNSQ model persona and never inherits the user's
bedrock implicitly.

On disk::

    users/<user>/account.yaml
    users/<user>/bedrock.yaml
    users/<user>/sharing.yaml
    users/<user>/relationships.yaml
    users/<user>/user_personas/<persona>.yaml

Disclosure is a vector.  A relationship supplies a baseline, groups add
category-specific allowances and denials, and a fact may add its own
exceptions.  Every listener must be allowed; any denial wins.
"""
from __future__ import annotations

import os
import json
import re
import tempfile
from typing import Iterable

import yaml

RELATIONSHIP_STATUSES = {"blocked", "neutral", "contact"}
FACT_VISIBILITIES = {"private", "groups", "contacts", "public"}


def slugify(value: str) -> str:
    slug = re.sub(r"[\s\-]+", "_", (value or "").strip().lower())
    slug = re.sub(r"[^a-z0-9_]", "", slug)
    slug = re.sub(r"_+", "_", slug).strip("_")
    if not slug or slug.startswith("_"):
        raise ValueError("a usable name is required")
    return slug


def _users_dir(repo: str) -> str:
    return os.path.join(repo, "users")


def _user_dir(repo: str, uid: str) -> str:
    return os.path.join(_users_dir(repo), slugify(uid))


def _read_yaml(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            value = yaml.safe_load(f)
        return value if isinstance(value, type(default)) else default
    except (OSError, yaml.YAMLError):
        return default


def _write_yaml(path: str, value) -> None:
    """Validate first, then atomically replace.  A failed write leaves truth."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rendered = yaml.safe_dump(value, allow_unicode=True, sort_keys=False)
    # Prove our own output parses before it can replace the live document.
    yaml.safe_load(rendered)
    fd, tmp = tempfile.mkstemp(prefix=".jnsq-", suffix=".tmp",
                               dir=os.path.dirname(path), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(rendered)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def list_users(repo: str) -> dict:
    out = {}
    root = _users_dir(repo)
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return out
    for name in names:
        if name.startswith(("_", ".")):
            continue
        account = _read_yaml(os.path.join(root, name, "account.yaml"), {})
        if account:
            account.setdefault("id", name)
            account.setdefault("username", name)
            account.setdefault("display_name", account["username"])
            out[name] = account
    return out


def get_user(repo: str, uid: str) -> dict | None:
    uid = slugify(uid)
    account = list_users(repo).get(uid)
    if not account:
        return None
    base = _user_dir(repo, uid)
    bedrock = _read_yaml(os.path.join(base, "bedrock.yaml"), {"facts": []})
    sharing = _read_yaml(os.path.join(base, "sharing.yaml"), {"groups": {}})
    relations = _read_yaml(os.path.join(base, "relationships.yaml"),
                           {"relationships": {}})
    personas = {}
    pdir = os.path.join(base, "user_personas")
    try:
        persona_files = sorted(os.listdir(pdir))
    except OSError:
        persona_files = []
    for filename in persona_files:
        if filename.startswith(("_", ".")) or not filename.endswith(".yaml"):
            continue
        rec = _read_yaml(os.path.join(pdir, filename), {})
        if rec:
            personas[rec.get("id") or filename[:-5]] = rec
    return {"account": account, "bedrock": bedrock.get("facts", []),
            "groups": sharing.get("groups", {}),
            "relationships": relations.get("relationships", {}),
            "user_personas": personas}


def upsert_user(repo: str, *, username: str, display_name: str = "",
                pronouns: str = "", public_profile: dict | None = None,
                update: bool = False) -> dict:
    uid = slugify(username)
    path = os.path.join(_user_dir(repo, uid), "account.yaml")
    exists = os.path.exists(path)
    if exists and not update:
        raise FileExistsError(f"user '{uid}' already exists")
    prior = _read_yaml(path, {}) if exists else {}
    prior.update({"id": uid, "username": username.strip(),
                  "display_name": (display_name or username).strip(),
                  "pronouns": pronouns.strip(),
                  "public_profile": public_profile or
                                    prior.get("public_profile", {})})
    _write_yaml(path, prior)
    base = _user_dir(repo, uid)
    for filename, seed in (("bedrock.yaml", {"facts": []}),
                           ("sharing.yaml", {"groups": {}}),
                           ("relationships.yaml", {"relationships": {}})):
        target = os.path.join(base, filename)
        if not os.path.exists(target):
            _write_yaml(target, seed)
    os.makedirs(os.path.join(base, "user_personas"), exist_ok=True)
    return prior


def put_bedrock_fact(repo: str, uid: str, *, text: str, category: str,
                     visibility: str = "private", fact_id: str = "",
                     groups: Iterable[str] = (), share_with: Iterable[str] = (),
                     never_share_with: Iterable[str] = (),
                     source: dict | None = None) -> dict:
    user = get_user(repo, uid)
    if not user:
        raise KeyError(f"no user '{uid}'")
    if visibility not in FACT_VISIBILITIES:
        raise ValueError(f"visibility must be one of {sorted(FACT_VISIBILITIES)}")
    clean_text = (text or "").strip()
    if not clean_text:
        raise ValueError("bedrock text is required")
    facts = list(user["bedrock"])
    fid = slugify(fact_id or category or clean_text[:48])
    rec = {"id": fid, "text": clean_text,
           "category": slugify(category or "general"),
           "visibility": visibility,
           "groups": sorted({slugify(x) for x in groups if x}),
           "share_with": sorted({slugify(x) for x in share_with if x}),
           "never_share_with": sorted(
               {slugify(x) for x in never_share_with if x})}
    if source:
        rec["source"] = dict(source)
    for i, old in enumerate(facts):
        if old.get("id") == fid:
            # Provenance is an immutable receipt. Editing the user-owned
            # text or disclosure boundary must not sever where an imported
            # fact came from merely because the browser never sends that
            # internal source object back over the wire.
            if "source" not in rec and old.get("source"):
                rec["source"] = dict(old["source"])
            facts[i] = rec
            break
    else:
        facts.append(rec)
    _write_yaml(os.path.join(_user_dir(repo, uid), "bedrock.yaml"),
                {"facts": facts})
    return rec


def legacy_bedrock_candidates(repo: str) -> list:
    """Read bedrock already seeded into active AI-persona memories.

    This is migration input, not a second live source of user truth. Hidden,
    graveyard, and fixture directories are ignored; duplicate memory ids and
    duplicate fact text collapse to the first active source.
    """
    root = os.path.join(repo, "personas")
    try:
        persona_names = sorted(os.listdir(root))
    except OSError:
        return []
    out, seen_ids, seen_text = [], set(), set()
    for persona in persona_names:
        if persona.startswith(("_", ".")) or "fixture" in persona.lower():
            continue
        path = os.path.join(root, persona, "body", "memory_emotion",
                            "memories.json")
        try:
            with open(path, encoding="utf-8") as f:
                memories = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(memories, list):
            continue
        for memory in memories:
            fields = memory.get("fields") or {}
            if not fields.get("is_bedrock"):
                continue
            mid = str(memory.get("id") or "")
            content = str(memory.get("content") or "").strip()
            key = content.casefold()
            if not content or (mid and mid in seen_ids) or key in seen_text:
                continue
            seen_ids.add(mid)
            seen_text.add(key)
            audience = fields.get("audience", "household")
            visibility = {"public": "public", "friends": "contacts"}.get(
                audience, "private")
            out.append({
                "memory_id": mid,
                "source_persona": persona,
                "text": content,
                "category": fields.get("category") or "general",
                "visibility": visibility,
                "entities": list(memory.get("entities") or []),
            })
    return out


def import_legacy_bedrock(repo: str, uid: str) -> dict:
    """Claim legacy bedrock for a user without destroying its old source.

    Imported facts default to the safest visibility compatible with the old
    audience. Provenance lets turn assembly suppress the old memory record,
    making the user's editable copy the disclosure authority from then on.
    Re-running is idempotent.
    """
    user = get_user(repo, uid)
    if not user:
        raise KeyError(f"no user '{uid}'")
    existing_sources = {
        str((fact.get("source") or {}).get("memory_id"))
        for fact in user["bedrock"] if (fact.get("source") or {}).get("memory_id")}
    existing_text = {str(f.get("text") or "").strip().casefold()
                     for f in user["bedrock"]}
    imported, skipped = [], []
    for candidate in legacy_bedrock_candidates(repo):
        mid = candidate["memory_id"]
        if mid in existing_sources or candidate["text"].casefold() in existing_text:
            skipped.append(mid)
            continue
        compact = re.sub(r"[^a-z0-9]", "", mid.lower())[:16]
        fact = put_bedrock_fact(
            repo, uid, fact_id=f"legacy_{compact or len(imported) + 1}",
            text=candidate["text"], category=candidate["category"],
            visibility=candidate["visibility"],
            source={"kind": "persona_memory",
                    "persona": candidate["source_persona"],
                    "memory_id": mid,
                    "entities": candidate["entities"]})
        imported.append(fact)
        existing_sources.add(mid)
        existing_text.add(candidate["text"].casefold())
    return {"imported": imported, "skipped": skipped,
            "available": len(imported) + len(skipped)}


def delete_bedrock_fact(repo: str, uid: str, fact_id: str) -> bool:
    user = get_user(repo, uid)
    if not user:
        raise KeyError(f"no user '{uid}'")
    before = list(user["bedrock"])
    facts = [f for f in before if f.get("id") != slugify(fact_id)]
    if len(facts) == len(before):
        return False
    _write_yaml(os.path.join(_user_dir(repo, uid), "bedrock.yaml"),
                {"facts": facts})
    return True


def put_group(repo: str, uid: str, *, group_id: str, name: str = "",
              access: str = "bounded", allow_categories: Iterable[str] = (),
              deny_categories: Iterable[str] = (), instructions: str = "") -> dict:
    user = get_user(repo, uid)
    if not user:
        raise KeyError(f"no user '{uid}'")
    gid = slugify(group_id or name)
    if access not in {"bounded", "full"}:
        raise ValueError("access must be bounded or full")
    rec = {"id": gid, "name": (name or group_id).strip(), "access": access,
           "allow_categories": sorted({slugify(x) for x in allow_categories if x}),
           "deny_categories": sorted({slugify(x) for x in deny_categories if x}),
           "instructions": (instructions or "").strip()}
    groups = dict(user["groups"])
    groups[gid] = rec
    _write_yaml(os.path.join(_user_dir(repo, uid), "sharing.yaml"),
                {"groups": groups})
    return rec


def put_relationship(repo: str, uid: str, other: str, *, status: str,
                     groups: Iterable[str] = (), note: str = "") -> dict:
    user = get_user(repo, uid)
    if not user:
        raise KeyError(f"no user '{uid}'")
    if status not in RELATIONSHIP_STATUSES:
        raise ValueError(f"status must be one of {sorted(RELATIONSHIP_STATUSES)}")
    oid = slugify(other)
    unknown = sorted({slugify(g) for g in groups if g} - set(user["groups"]))
    if unknown:
        raise ValueError(f"unknown sharing groups: {unknown}")
    rec = {"user": oid, "status": status,
           "groups": sorted({slugify(g) for g in groups if g}),
           "note": (note or "").strip()}
    relations = dict(user["relationships"])
    relations[oid] = rec
    _write_yaml(os.path.join(_user_dir(repo, uid), "relationships.yaml"),
                {"relationships": relations})
    return rec


def put_user_persona(repo: str, uid: str, *, persona_id: str, name: str,
                     description: str = "", preferences: str = "",
                     boundaries: str = "", icon: str | None = None) -> dict:
    if not get_user(repo, uid):
        raise KeyError(f"no user '{uid}'")
    pid = slugify(persona_id or name)
    path = os.path.join(_user_dir(repo, uid), "user_personas", pid + ".yaml")
    prior = _read_yaml(path, {})
    rec = {"id": pid, "name": (name or persona_id).strip(),
           "description": (description or "").strip(),
           "preferences": (preferences or "").strip(),
           "boundaries": (boundaries or "").strip()}
    for key in ("icon", "avatar"):
        if prior.get(key):
            rec[key] = prior[key]
    if icon is not None:
        value = icon.strip()
        if not value or len(value) > 16:
            raise ValueError("user persona icon must be 1-16 characters")
        rec["icon"] = value
    _write_yaml(path, rec)
    return rec


def set_user_icon(repo: str, uid: str, icon: str) -> dict:
    """Persist a human account's fallback glyph in the account record."""
    user = get_user(repo, uid)
    if not user:
        raise KeyError(f"no user '{uid}'")
    value = (icon or "").strip()
    if not value or len(value) > 16:
        raise ValueError("user icon must be 1-16 characters")
    account = dict(user["account"])
    account["icon"] = value
    _write_yaml(os.path.join(_user_dir(repo, uid), "account.yaml"), account)
    return account


def save_user_avatar(repo: str, uid: str, data_url: str) -> dict:
    """Store an account avatar locally and persist only its relative path."""
    user = get_user(repo, uid)
    if not user:
        raise KeyError(f"no user '{uid}'")
    from shell.persona_media import save_local_avatar
    base = _user_dir(repo, uid)
    result = save_local_avatar(os.path.join(base, "ui"), data_url)
    account = dict(user["account"])
    account["avatar"] = f"ui/{os.path.basename(result['path'])}"
    _write_yaml(os.path.join(base, "account.yaml"), account)
    return {**result, "relative": account["avatar"]}


def load_user_avatar(repo: str, uid: str) -> dict | None:
    user = get_user(repo, uid)
    if not user:
        return None
    from shell.persona_media import load_local_avatar
    return load_local_avatar(_user_dir(repo, uid),
                             user["account"].get("avatar") or "")


def save_user_persona_avatar(repo: str, uid: str, persona_id: str,
                             data_url: str) -> dict:
    """Store an RP user-persona avatar without joining it to the account."""
    user = get_user(repo, uid)
    if not user:
        raise KeyError(f"no user '{uid}'")
    pid = slugify(persona_id)
    rec = user["user_personas"].get(pid)
    if not rec:
        raise KeyError(f"no user persona '{pid}'")
    from shell.persona_media import save_local_avatar
    base = _user_dir(repo, uid)
    media_dir = os.path.join(base, "ui", "user_personas", pid)
    result = save_local_avatar(media_dir, data_url)
    updated = dict(rec)
    updated["avatar"] = (f"ui/user_personas/{pid}/"
                         f"{os.path.basename(result['path'])}")
    _write_yaml(os.path.join(base, "user_personas", pid + ".yaml"), updated)
    return {**result, "relative": updated["avatar"]}


def load_user_persona_avatar(repo: str, uid: str,
                             persona_id: str) -> dict | None:
    user = get_user(repo, uid)
    if not user:
        return None
    pid = slugify(persona_id)
    rec = user["user_personas"].get(pid)
    if not rec:
        return None
    from shell.persona_media import load_local_avatar
    return load_local_avatar(_user_dir(repo, uid), rec.get("avatar") or "")


def delete_user_persona(repo: str, uid: str, persona_id: str) -> bool:
    if not get_user(repo, uid):
        raise KeyError(f"no user '{uid}'")
    pid = slugify(persona_id)
    path = os.path.join(_user_dir(repo, uid), "user_personas", pid + ".yaml")
    if not os.path.isfile(path):
        return False
    os.unlink(path)
    return True


def can_disclose_fact(user: dict, fact: dict, recipient: str) -> bool:
    """Whether one fact may reach one recipient.  Denial always wins."""
    rid = slugify(recipient)
    owner = slugify(user["account"]["id"])
    if rid == owner:
        return True
    rel = user["relationships"].get(rid, {})
    status = rel.get("status", "neutral")
    if status == "blocked" or rid in set(fact.get("never_share_with") or []):
        return False
    category = slugify(fact.get("category") or "general")
    policies = [user["groups"].get(g, {}) for g in rel.get("groups", [])]
    # Group denials are constitutional boundaries, not hints. They beat
    # public visibility, full-access groups, and fact-level allowances.
    if any(category in set(p.get("deny_categories") or []) for p in policies):
        return False
    if rid in set(fact.get("share_with") or []):
        return True
    visibility = fact.get("visibility", "private")
    if visibility == "public":
        return True
    if status != "contact":
        return False
    fact_groups = set(fact.get("groups") or [])
    if visibility == "groups" and not fact_groups.intersection(rel.get("groups", [])):
        return False
    if visibility == "contacts":
        return True
    return any(p.get("access") == "full" or
               category in set(p.get("allow_categories") or [])
               for p in policies)


def context_for_turn(repo: str, speaker: str, listeners: Iterable[str],
                     self_persona: str = "") -> tuple[str, dict]:
    """Render user-owned truth safe for *all* listeners in this turn."""
    users = list_users(repo)
    sid = (speaker or "").lower()
    uid = next((u for u, a in users.items()
                if sid in {u.lower(), str(a.get("username", "")).lower(),
                           str(a.get("display_name", "")).lower()}), None)
    if not uid:
        return "", {"user": None, "rendered": [], "withheld": []}
    user = get_user(repo, uid)
    audience = [x for x in listeners
                if (x or "").lower() not in
                {sid, (self_persona or "").lower()}]
    rendered, withheld = [], []
    for fact in user["bedrock"]:
        if all(can_disclose_fact(user, fact, person) for person in audience):
            rendered.append(fact)
        else:
            withheld.append(fact.get("id"))
    lines = ["Bedrock facts the user declared about herself. These are "
             "documented facts, not an instruction about what to feel:"]
    lines.extend(f"- [{f.get('category', 'general')}] {f['text']}"
                 for f in rendered)
    instructions = []
    for person in audience:
        rel = user["relationships"].get(slugify(person), {})
        if rel.get("status") == "blocked":
            instructions.append(
                f"Do not disclose that {user['account']['display_name']} exists to {person}.")
        for gid in rel.get("groups", []):
            note = user["groups"].get(gid, {}).get("instructions", "")
            if note:
                instructions.append(f"Around {person}: {note}")
    if instructions:
        lines.append("User-declared disclosure boundaries for this company:")
        lines.extend(f"- {x}" for x in dict.fromkeys(instructions))
    text = "\n".join(lines) if rendered or instructions else ""
    claimed_sources = [str((f.get("source") or {}).get("memory_id"))
                       for f in user["bedrock"]
                       if (f.get("source") or {}).get("memory_id")]
    return text, {"user": uid, "rendered": [f["id"] for f in rendered],
                  "withheld": withheld, "listeners": audience,
                  "claimed_source_memory_ids": claimed_sources}

"""Machine-local human identity, deliberately separate from the repository."""
from __future__ import annotations

import json
import os
import tempfile

FILENAME = ".jnsq_local.json"


def load_local_identity(repo: str) -> dict:
    path = os.path.join(repo, FILENAME)
    try:
        with open(path, encoding="utf-8") as f:
            value = json.load(f)
        user_id = str(value.get("user_id") or "").strip()
        display_name = str(value.get("display_name") or user_id).strip()
        if user_id and display_name:
            return {"user_id": user_id, "display_name": display_name,
                    "configured": True}
    except (OSError, ValueError, TypeError):
        pass
    try:
        from core.users import list_users
        users = list_users(repo)
        if len(users) == 1:
            user_id, account = next(iter(users.items()))
            return {"user_id": user_id,
                    "display_name": account.get("display_name") or user_id,
                    "configured": False}
    except Exception:
        pass
    return {"user_id": "user", "display_name": "User",
            "configured": False}


def save_local_identity(repo: str, user_id: str, display_name: str) -> dict:
    from core.users import slugify
    value = {"user_id": slugify(user_id),
             "display_name": (display_name or user_id).strip()}
    fd, tmp = tempfile.mkstemp(prefix=".jnsq-local-", suffix=".tmp",
                               dir=repo, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, os.path.join(repo, FILENAME))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return {**value, "configured": True}


def local_user_directory(repo: str) -> dict:
    """Return human accounts with this installation's owner guaranteed.

    Early public installs could have ``.jnsq_local.json`` without a matching
    ``users/<id>/account.yaml``.  The local identity is still real enough to
    enter and speak in the Nexus; account setup can enrich it later.
    """
    from core.users import list_users
    users = list_users(repo)
    identity = load_local_identity(repo)
    uid = identity["user_id"]
    if uid not in users:
        users[uid] = {
            "id": uid,
            "username": uid,
            "display_name": identity["display_name"],
            "local_identity": True,
        }
    return users

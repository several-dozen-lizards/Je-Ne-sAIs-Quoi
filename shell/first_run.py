"""Create the human account belonging to this local JNSQ installation."""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.users import list_users, slugify, upsert_user
from shell.local_identity import save_local_identity


def configure(username: str, display_name: str = "", repo: str = ROOT) -> dict:
    username = (username or "").strip()
    if not username:
        raise ValueError("a username is required")
    uid = slugify(username)
    display_name = (display_name or username).strip()
    account = upsert_user(repo, username=username, display_name=display_name,
                          update=uid in list_users(repo))
    identity = save_local_identity(repo, uid, display_name)
    return {"account": account, "identity": identity}


def main():
    ap = argparse.ArgumentParser(description="Set up this local JNSQ home")
    ap.add_argument("--username")
    ap.add_argument("--display-name", default="")
    ap.add_argument("--root", default=ROOT, help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.username:
        username, display = args.username, args.display_name
    else:
        print("\nWho owns this JNSQ home?")
        username = input("Username: ").strip()
        display = input("Display name (Enter to use username): ").strip()
    result = configure(username, display, args.root)
    who = result["identity"]["display_name"]
    print(f"\nThis JNSQ home now belongs to {who}.")
    print("Start it with START_NEXUS.bat, then create a persona from the "
          "chat workspace. Closing its JNSQ window stops the household "
          "cleanly.")


if __name__ == "__main__":
    main()

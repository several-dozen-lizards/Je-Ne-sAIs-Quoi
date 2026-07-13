"""Offline smoke test for a clean JNSQ starter tree."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))


def main():
    for name in ("users", "personas", "people", "logs"):
        files = [p for p in (ROOT / name).rglob("*")
                 if p.is_file() and p.name != ".gitkeep"]
        assert not files, f"{name} is not empty: {files}"
    assert not (ROOT / "godot-room").exists(), "public build contains 3D assets"
    shell = (ROOT / "shell" / "fangwall.html").read_text(encoding="utf-8")
    assert "Je Ne <strong>sAI</strong>s Quoi" in shell
    assert "data-visible" in shell
    assert "Yurt" not in shell and ">World<" not in shell
    assert not list(ROOT.rglob("test_*.py")), "public build contains dev tests"
    assert not (ROOT / "core" / "bench.py").exists()
    assert not (ROOT / "core" / "first_turn.py").exists()
    assert not (ROOT / "tools" / "build_distribution.py").exists()

    from room.host import build_app as build_room_app
    room_app = build_room_app()
    assert set(room_app.state.rooms) == {"nexus"}

    from shell.router import build_app as build_router_app
    router_app = build_router_app()
    assert router_app.state.registry == {}
    assert router_app.state.local_identity["display_name"] == "User"

    text_suffixes = {".py", ".html", ".yaml", ".yml", ".json", ".md",
                     ".txt", ".bat"}
    private_markers = ("D:" + "/Wrappers", "D:" + "\\Wrappers",
                       "K" + "ay", "Re" + "ed", "Eury" + "ale",
                       "Testy " + "McPrototype",
                       "testy_" + "mcprototype")
    for path in ROOT.rglob("*"):
        if path.is_file() and path.suffix.lower() in text_suffixes:
            text = path.read_text(encoding="utf-8")
            for marker in private_markers:
                assert marker.lower() not in text.lower(), \
                    f"private marker {marker!r} remains in {path}"

    from room.layout import build_persona_den
    den = build_persona_den("ember_fox", "Ember Fox")
    assert den.id == "ember_fox_den"
    assert den.objects["ember_fox_desk"].owner == "ember_fox"

    from shell.first_run import configure
    from shell.local_identity import load_local_identity
    from shell.factory import scaffold
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        configure("smoke_user", "Smoke User", str(home))
        assert load_local_identity(str(home))["display_name"] == "Smoke User"
        made = scaffold("Ember Fox", root=str(home / "personas"))
        assert made["model"] == "llama3-1-8b"
        roster_path = home / "personas" / "ember_fox" / "roster.yaml"
        assert roster_path.is_file()
        import yaml
        roster = yaml.safe_load(roster_path.read_text(encoding="utf-8"))
        assert roster["room"]["id"] == "nexus"
    print("JNSQ starter smoke test: PASS")


if __name__ == "__main__":
    main()

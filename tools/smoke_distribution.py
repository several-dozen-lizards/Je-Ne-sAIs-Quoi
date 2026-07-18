"""Offline smoke test for a clean JNSQ starter tree."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import hashlib
import os
from pathlib import Path
import sys
import tempfile
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))


def main():
    for name in ("users", "personas", "people", "logs"):
        files = [p for p in (ROOT / name).rglob("*")
                 if p.is_file() and p.name != ".gitkeep"]
        assert not files, f"{name} is not empty: {files}"
    assert not (ROOT / "godot-room").exists(), "public build contains 3D assets"
    start = (ROOT / "START_NEXUS.bat").read_text(encoding="utf-8")
    assert "shell\\boot.py --session" in start
    boot = (ROOT / "shell" / "boot.py").read_text(encoding="utf-8")
    assert "def run_session()" in boot and "browser.wait()" in boot
    assert "session_browser_pid" in boot
    shell = (ROOT / "shell" / "fangwall.html").read_text(encoding="utf-8")
    assert 'Je Ne S<span class="ai">ai</span>s Quoi' in shell
    assert 'id="personaHome"' in shell and 'id="panelTabs"' in shell
    assert "openPanel" in shell and "renderPanelTabs" in shell
    assert "personas().map" in shell and "jnsq.public.visible" in shell
    assert 'className="panel-resizer"' in shell
    assert "jnsq.public.widths" in shell and "wirePanelResizers" in shell
    assert "data-icon" in shell and "openPersonaLook" in shell
    assert 'id="lookDialog"' in shell and "speaker_colors" in shell
    assert "/assets/hex_color.js" in shell
    assert "data-avatar" not in shell and "choosePersonaAvatar" not in shell
    assert 'class="home-heading">The household' in shell
    assert "data-switch" in shell and "switchPersona" in shell
    assert "data-add-model" in shell and "openRoster" in shell
    assert "Yurt" not in shell and ">World<" not in shell
    assert 'data-top-page="personas"' in shell
    assert 'data-top-page="settings"' in shell
    assert 'id="page-settings"' in shell and 'src="/settings"' in shell
    assert 'id="openWorld"' not in shell
    assert 'id="installModel"' in shell and 'id="modelDialog"' in shell
    assert 'id="interiorHelp"' in shell and "one additional model call per turn" in shell
    assert "/api/models/create" in shell and "/api/models/discover" in shell
    assert "Ollama · local" in shell and "LM Studio · local" in shell
    assert "The Nexus" in shell
    assert 'data-top-page="nexus"' in shell
    assert shell.index("<span>Household</span>") < shell.index("<span>Chat</span>") < shell.index("<span>Settings</span>") < shell.index("<span>About</span>")
    assert shell.count('class="nav-icon"') == 4
    assert 'stroke="currentColor"' in shell
    assert "function nexusIcon()" in shell and 'class="nexus-icon"' in shell
    assert "🌍 The Nexus" not in shell
    assert "function openNexus()" in shell
    assert "/assets/jnsq_favicon.svg" in shell
    assert "a local home for persistent AI personas" not in shell
    assert "scrollbar-color:var(--mint)" in shell
    assert "--panel2:color-mix(in srgb,var(--panel) 82%,var(--mint))" in shell
    assert 'class="on" type="button" data-top-page="personas"' in shell
    assert "background:color-mix(in srgb,var(--mint) 20%,var(--panel))" in shell
    cockpit = (ROOT / "shell" / "cockpit.html").read_text(encoding="utf-8")
    assert "JNSQ cockpit" not in cockpit and 'class="brand-mark"' not in cockpit
    assert "Conversation · Je Ne Sais Quoi" in cockpit
    assert "jnsq_icon_animated_128.apng" in cockpit
    assert "setThinking(true)" in cockpit and "setThinking(false)" in cockpit
    assert "setInterval" not in cockpit
    assert "thought-label" not in cockpit
    assert "scrollConversationToBottom()" in cockpit
    assert "requestAnimationFrame" in cockpit
    assert 'fetch("/api/turn/stream"' in cockpit
    assert "res.body.getReader()" in cockpit
    assert "const turnQueue = []" in cockpit
    assert "turnQueue.push({text,sentImages})" in cockpit
    assert "const item=turnQueue.shift()" in cockpit
    assert "repaintQueuedTurns()" in cockpit
    contract = (ROOT / "shell" / "contract.py").read_text(encoding="utf-8")
    cockpit_server = (ROOT / "shell" / "cockpit.py").read_text(
        encoding="utf-8")
    assert '@app.post("/api/turn/stream")' in cockpit_server, (
        "cockpit frontend requests /api/turn/stream but backend route is missing")
    assert 'working_window(self.window_k, channel="chat")' in contract
    assert "app.state.turn_lock.acquire()" in cockpit_server
    assert "human_turn_arrived" in cockpit_server
    assert 'id="atelier"' in cockpit
    assert 'id="atelier-submit"' in cockpit
    assert "function renderAtelier" in cockpit
    assert "function perceiveAtelierArtifact" in cockpit
    assert '@app.get("/api/atelier")' in cockpit_server
    assert '@app.post("/api/atelier/seeds")' in cockpit_server
    assert '@app.get("/api/atelier/artifacts/{artifact_id}")' in cockpit_server
    assert '@app.post("/api/atelier/artifacts/{artifact_id}/perceive")' in cockpit_server
    assert (ROOT / "core" / "atelier.py").is_file()
    assert (ROOT / "shell" / "atelier_runtime.py").is_file()
    assert (ROOT / "specs" / "organ_instructions" / "atelier.yaml").is_file()
    assert "CONFIG.persona_avatar" in cockpit
    assert 'id="column-resizer"' in cockpit
    assert 'id="bodyToggle"' in cockpit and 'id="receiptsToggle"' in cockpit
    assert 'id="cockpit-main" class="inspector-collapsed"' in cockpit
    assert 'class="panel collapsed" id="receipts-panel"' in cockpit
    assert 'localStorage.getItem(key) !== "open"' in cockpit
    assert "scrollbar-color:var(--accent)" in cockpit
    assert cockpit.count('class="sensory-control"') == 3
    assert "#composer .sensory-control" in cockpit
    for font in ("display", "humanist", "rounded", "geometric"):
        assert f'<option value="{font}">' in cockpit
    assert "themeFontStack(tokens.font)" in cockpit
    assert 'id="themeFontScale"' in cockpit and '"font_scale"' in cockpit
    assert 'id="themeBackgroundFile"' in cockpit
    assert 'id="themeBackgroundUpload"' in cockpit
    assert 'id="themeBackgroundRemove"' in cockpit
    assert '@app.post("/api/ui/conversation-background")' in cockpit_server
    assert '@app.delete("/api/ui/conversation-background")' in cockpit_server
    settings = (ROOT / "shell" / "settings.html").read_text(encoding="utf-8")
    users = (ROOT / "shell" / "users.html").read_text(encoding="utf-8")
    assert "scrollbar-color:var(--accent)" in settings
    assert "scrollbar-color:var(--accent)" in users
    assert settings.count('class="ui-icon"') == 6
    assert '<span>Account &amp; privacy</span>' in settings
    assert '<span>Updates</span>' in settings
    assert 'class="ui-icon"' in users and "👤" not in users
    assert '<option value="humanist">Atkinson Hyperlegible</option>' in settings
    assert 'id="houseFontScale"' in settings and "--theme-glow-alpha" in settings
    assert 'id="housePresetCreate"' in settings
    assert 'id="housePresetUpdate"' in settings
    assert 'id="housePresetDelete"' in settings
    assert "themeFontStack(t.font)" in users
    assert "saveAccountLook" in users and "uploadPersonaAvatar" in users
    nexus = (ROOT / "room" / "viewer.html").read_text(encoding="utf-8")
    assert 'id="nexusResizer"' in nexus
    assert 'data-nexus-section="invite"' in nexus
    assert 'data-nexus-section="present" open' in nexus
    assert 'id="sidebarToggle"' in nexus and 'sidebarCollapsed' in nexus
    assert 'Nexus appearance' in nexus and 'id="saveNexusAppearance"' in nexus
    assert 'id="resetNexusAppearance"' in nexus
    assert '/assets/hex_color.js' in nexus
    assert 'class="speaker-choice"' in nexus
    assert 'jnsq.nexus.presenceWidth' in nexus
    assert 'class="speaker-mark"' in nexus
    assert "function speakerProfile" in nexus
    assert "function fallbackColor" in nexus
    assert "avatar_url" in nexus and "--speaker-color" in nexus
    assert '<header><div><h1>The Nexus</h1>' in nexus
    assert 'jnsq_favicon.svg' not in nexus
    assert "const fonts={system:" in nexus and "humanist:" in nexus
    assert 't.font_scale' in nexus and '--theme-motion-duration' in nexus
    assert 'id="organScope"' in cockpit
    assert 'id="saveOrgans"' in cockpit
    assert 'JSON.stringify({enabled, scope})' in cockpit
    for name in ("favicon.ico", "jnsq_favicon.svg",
                 "jnsq_icon_animated_128.apng", "favicon-180.png",
                 "hex_color.js"):
        assert (ROOT / "assets" / "jnsq" / name).is_file(), name
    assert (ROOT / "assets" / "jnsq" /
            "jnsq-venetian-mask-space.png").is_file()
    import yaml
    glm_spec = yaml.safe_load((ROOT / "specs" / "models" /
                               "glm-5.yaml").read_text(encoding="utf-8"))
    glm_temperature = glm_spec["sampling"]["temperature"]
    assert glm_temperature["max"] == 1.0
    assert glm_temperature["precision"] == 2
    gpt_spec = yaml.safe_load((ROOT / "specs" / "models" /
                               "gpt-5-6.yaml").read_text(encoding="utf-8"))
    assert gpt_spec["sampling"]["temperature"]["mode"] == "omit"
    assert gpt_spec["reasoning"]["effort"] == "low"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "jnsq_favicon.svg" in readme
    assert "jnsq-venetian-mask-space.png" in readme
    assert "Ambient camera and microphone" in readme
    assert "body/perception/images/" in readme
    assert "body/atelier/" in readme
    assert "no publishing or" in readme
    assert "spoken-turn" in readme and "checkbox is off by default" in readme
    assert "Reply speech is also off by default" in readme
    assert "browser/operating system speech" in readme
    assert "no fixed barge-in delay" in readme
    assert "linguistic clause boundary" in readme
    assert "public builds never contain it" in readme
    installer = (ROOT / "INSTALL_JNSQ.bat").read_text(encoding="utf-8")
    setup = (ROOT / "SETUP_JNSQ.ps1").read_text(encoding="utf-8")
    assert "SETUP_JNSQ.ps1" in installer
    assert "Python.Python.3.12" in setup
    assert 'Join-Path $Root ".venv"' in setup
    assert "pip\", \"install\", \"--requirement" in setup
    assert "Existing local owner found" in setup
    assert "Start Je Ne Sais Quoi now?" in setup
    requirements = (ROOT / "requirements.txt").read_text(
        encoding="utf-8").splitlines()
    assert requirements.count("pydantic-ai-slim==2.8.0") == 1
    updater = (ROOT / "UPDATE_JNSQ.ps1").read_text(encoding="utf-8")
    update_launcher = (ROOT / "UPDATE_JNSQ.bat").read_text(encoding="utf-8")
    assert "UPDATE_JNSQ.ps1" in update_launcher
    assert "managed_files" in updater and "Get-FileHash" in updater
    assert "requirementsChanged" in updater
    assert "Previous managed files were restored" in updater
    assert updater.index("Checking patched source files") < updater.index(
        "Copy-Item -LiteralPath $packageManifestPath")
    assert "local-life data" in updater
    for relative in (
            "harness/anthropic_events.py",
            "harness/openai_compat_events.py",
            "harness/model_call_receipts.py"):
        assert (ROOT / relative).is_file(), \
            f"public runtime transport is missing: {relative}"
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    settings = (ROOT / "shell" / "settings.html").read_text(encoding="utf-8")
    for page in ("account", "appearance", "keys", "vision", "prompts",
                 "updates"):
        assert f'data-page="{page}"' in settings
    assert 'src="/users"' in settings
    assert "/api/ui/theme" in settings and "/api/env" in settings
    assert "data-vision-select" in settings and "/vision/test" in settings
    assert "public JNSQ" in settings and "may incur" in settings
    assert "cheap + reliable recommendation" in settings
    assert "organ_prompts" in settings and "/api/version/check" in settings
    assert not list(ROOT.rglob("test_*.py")), "public build contains dev tests"
    assert not (ROOT / "core" / "bench.py").exists()
    assert not (ROOT / "core" / "first_turn.py").exists()
    assert not (ROOT / "tools" / "build_distribution.py").exists()

    from room.host import build_app as build_room_app
    room_app = build_room_app()
    assert set(room_app.state.rooms) == {"nexus"}
    room_routes = {route.path for route in room_app.routes}
    assert "/api/rooms/{rid}/events/wait" in room_routes
    assert {"/api/users", "/api/join", "/api/leave", "/api/act"} <= room_routes
    viewer = (ROOT / "room" / "viewer.html").read_text(encoding="utf-8")
    assert "events/wait" in viewer
    assert 'id="joinMember"' in viewer and 'id="speaker"' in viewer
    assert all(path in viewer for path in
               ("/api/users", "/api/join", "/api/leave", "/api/act"))
    assert "No one is present yet" in viewer
    assert "no room viewer" not in viewer
    host_source = (ROOT / "room" / "host.py").read_text(encoding="utf-8")
    assert 'p.endswith("/events/wait")' in host_source

    def room_endpoint(path, method):
        return next(route.endpoint for route in room_app.routes
                    if route.path == path and method in route.methods)

    from room.host import JoinReq, LeaveReq, ActionReq
    room_users = room_endpoint("/api/users", "GET")()["users"]
    assert room_users and room_users[0]["id"] == "user"
    joined = room_endpoint("/api/join", "POST")(
        JoinReq(member="smoke_user", room="nexus"))
    assert joined["ok"] and "smoke_user" in joined["room"]["members"]
    spoken = room_endpoint("/api/act", "POST")(
        ActionReq(member="smoke_user", action="say", text="hello"))
    assert spoken["ok"]
    left = room_endpoint("/api/leave", "POST")(
        LeaveReq(member="smoke_user"))
    assert left["ok"] and "smoke_user" not in room_app.state.where

    from room.state import Room
    threshold_room = Room("threshold", "threshold room", 4.0)
    with ThreadPoolExecutor(max_workers=1) as pool:
        waiting = pool.submit(threshold_room.wait_for_events, 0, 2.0)
        threshold_room.emit("smoke", "arrive", {})
        advanced = waiting.result(timeout=3)
    assert advanced and advanced[0]["seq"] == 1

    from shell.router import build_app as build_router_app
    router_app = build_router_app()
    assert router_app.state.registry == {}
    assert router_app.state.local_identity["display_name"] == "User"
    routes = {route.path for route in router_app.routes}
    assert {"/settings", "/api/version", "/api/version/check"} <= routes

    # A brand-new public home has no personas. Its live router therefore
    # returns {}, which is healthy and must still complete boot/write the
    # runfile instead of being mistaken for a liveness failure.
    from shell import boot as household_boot
    with tempfile.TemporaryDirectory() as tmp:
        runfile = Path(tmp) / "jnsq_running.json"
        with mock.patch.object(household_boot, "RUNFILE", str(runfile)), \
                mock.patch.object(household_boot, "_free_port",
                                  side_effect=(43101, 43102)), \
                mock.patch.object(household_boot, "_spawn",
                                  side_effect=(50101, 50102)), \
                mock.patch.object(household_boot, "_wait",
                                  side_effect=({"rooms": ["nexus"]}, {})), \
                mock.patch.object(household_boot.webbrowser, "open") as opened:
            household_boot.boot()
        assert runfile.is_file(), "empty healthy router did not finish boot"
        run = json.loads(runfile.read_text(encoding="utf-8"))
        assert run["router_port"] == 43102
        opened.assert_called_once_with("http://127.0.0.1:43102/")

    text_suffixes = {".py", ".html", ".yaml", ".yml", ".json", ".md",
                     ".txt", ".bat", ".ps1"}
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

    manifest = json.loads((ROOT / "DISTRIBUTION_MANIFEST.json").read_text(
        encoding="utf-8"))
    assert manifest["format"] == 2
    assert manifest["version"] == (ROOT / "VERSION").read_text(
        encoding="utf-8").strip()
    assert manifest["managed_files"]
    local_roots = {"personas", "users", "people", "logs", "exports"}
    for relative, expected in manifest["managed_files"].items():
        assert relative.split("/", 1)[0] not in local_roots
        path = ROOT / relative
        assert path.is_file(), f"managed file is missing: {relative}"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
        if path.suffix.lower() in {".py", ".html", ".js", ".css", ".json",
                                    ".yaml", ".yml", ".md", ".txt", ".bat",
                                    ".ps1"} or path.name in {
                                        ".gitignore", ".gitattributes", "VERSION"}:
            assert b"\r\n" not in path.read_bytes(), \
                f"public text is not canonical LF: {relative}"
    assert (ROOT / ".gitattributes").read_text(encoding="utf-8") == \
        "* text=auto eol=lf\n"

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
        made = scaffold("Ember Fox", organs="nexus",
                        root=str(home / "personas"))
        assert made["model"] == "llama3-1-8b"
        roster_path = home / "personas" / "ember_fox" / "roster.yaml"
        assert roster_path.is_file()
        roster = yaml.safe_load(roster_path.read_text(encoding="utf-8"))
        assert roster["icon"] == "🦋"
        assert roster["avatar"] == ""
        assert roster["room"]["id"] == "nexus"
        assert {"room_sense", "room_actions", "afferents", "tropism",
                "social"} <= set(roster["enabled_organs"])
        assert roster["perception"]["vision_model"] is None
        assert roster["enabled_organs"]
        assert "enabled_organs" not in roster["entries"][0]
    print("JNSQ starter smoke test: PASS")


if __name__ == "__main__":
    main()

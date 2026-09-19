"""shell/boot.py — household boot and browser-session lifecycle.
Brings up room host + router (which spawns all roster'd personas with
bodies), on FRESH OS-assigned ports every time (10048 law: never fight
a lingering socket). Liveness verified via API, never stdout. PIDs and
ports recorded to jnaiq_running.json so re-runs detect the live stack
instead of spawning a rival household. --stop reads the runfile and
takes it all down.

START_NEXUS uses --session: a dedicated browser window owns the household.
Firefox is preferred when it is installed; Chromium browsers remain the
fallback. The launcher waits on that real process handle; closing the window
flows directly into stop(). Refreshes and inner pane changes do not resemble
a session ending and cannot kill the household.

Usage:  python shell\\boot.py --session (or double-click START_NEXUS.bat)
        python shell\\boot.py           (boot without an owned session)
        python shell\\boot.py --stop    (or STOP_NEXUS.bat)"""
import argparse
from contextlib import contextmanager
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import uuid
import webbrowser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNFILE = os.path.join(ROOT, "jnaiq_running.json")
LEGACY_RUNFILES = (
    os.path.join(ROOT, "jnsq_running.json"),
    os.path.join(ROOT, ".jnsq_running.json"),
)
_legacy_boot_lock = os.path.join(ROOT, ".jnsq_boot.lock")
BOOT_LOCKFILE = (_legacy_boot_lock if any(os.path.exists(path)
                                          for path in LEGACY_RUNFILES)
                 else os.path.join(ROOT, ".jnaiq_boot.lock"))
LOGDIR = os.path.join(ROOT, "logs")
FIREFOX_SESSION_PROFILE = os.path.join(LOGDIR, "browser-session-firefox")
CHROMIUM_SESSION_PROFILE = os.path.join(LOGDIR, "browser-session")


@contextmanager
def _boot_lock(timeout: float = 180.0):
    """Serialize stop/boot ownership across double-clicks and callers."""
    os.makedirs(os.path.dirname(BOOT_LOCKFILE), exist_ok=True)
    handle = open(BOOT_LOCKFILE, "a+b")
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    deadline = time.monotonic() + max(1.0, float(timeout))
    locked = False
    try:
        while not locked:
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(),
                                fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except (OSError, IOError):
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        "another JNAIQ stop/boot transaction is still active")
                time.sleep(.1)
        yield
    finally:
        if locked:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _read_runfile():
    for path in (RUNFILE, *LEGACY_RUNFILES):
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                value = json.load(f)
        except (OSError, TypeError, ValueError):
            continue
        if isinstance(value, dict):
            return value
    return None


def _write_runfile(run: dict):
    """Atomically publish the one authoritative household receipt."""
    directory = os.path.dirname(RUNFILE)
    os.makedirs(directory, exist_ok=True)
    temporary = RUNFILE + "." + uuid.uuid4().hex + ".tmp"
    try:
        with open(temporary, "x", encoding="utf-8", newline="\n") as f:
            json.dump(dict(run), f, indent=1)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, RUNFILE)
    finally:
        try:
            os.remove(temporary)
        except FileNotFoundError:
            pass
    for legacy in LEGACY_RUNFILES:
        try:
            os.remove(legacy)
        except FileNotFoundError:
            pass


def _pid_alive(pid) -> bool:
    """Read process state without signalling or modifying the process."""
    try:
        pid = int(pid)
    except (OSError, TypeError, ValueError):
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    import ctypes
    query_limited_information = 0x1000
    still_active = 259
    kernel = ctypes.windll.kernel32
    handle = kernel.OpenProcess(query_limited_information, False, pid)
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        return bool(kernel.GetExitCodeProcess(
            handle, ctypes.byref(exit_code))) and exit_code.value == still_active
    finally:
        kernel.CloseHandle(handle)


def _session_browser():
    """Find a browser that can give the session its own process handle."""
    if sys.platform == "darwin":
        candidates = (
            ("firefox", "/Applications/Firefox.app/Contents/MacOS/firefox"),
            ("chromium", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            ("chromium", "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
            ("chromium", "/Applications/Chromium.app/Contents/MacOS/Chromium"),
        )
        return next(((family, path) for family, path in candidates
                     if os.path.isfile(path)), (None, None))
    roots = [os.environ.get("PROGRAMFILES(X86)"),
             os.environ.get("PROGRAMFILES"),
             os.environ.get("LOCALAPPDATA")]

    firefox_candidates = [shutil.which("firefox")]
    firefox_candidates.extend(
        os.path.join(root, "Mozilla Firefox", "firefox.exe")
        for root in roots if root)
    firefox = next((path for path in firefox_candidates
                    if path and os.path.isfile(path)), None)
    if firefox:
        return "firefox", firefox

    chromium_candidates = [shutil.which("msedge"), shutil.which("chrome")]
    suffixes = [
        os.path.join("Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join("Google", "Chrome", "Application", "chrome.exe"),
        os.path.join("BraveSoftware", "Brave-Browser", "Application",
                     "brave.exe"),
    ]
    chromium_candidates.extend(os.path.join(root, suffix)
                               for root in roots if root
                               for suffix in suffixes)
    chromium = next((path for path in chromium_candidates
                     if path and os.path.isfile(path)), None)
    return ("chromium", chromium) if chromium else (None, None)


def _launch_session_browser(url: str):
    """Open one isolated browser window and return its real process handle."""
    family, executable = _session_browser()
    if not executable:
        return None
    if family == "firefox":
        os.makedirs(FIREFOX_SESSION_PROFILE, exist_ok=True)
        command = [
            executable,
            "--wait-for-browser",
            "--new-instance",
            "--profile", FIREFOX_SESSION_PROFILE,
            "--new-window", url,
        ]
    else:
        os.makedirs(CHROMIUM_SESSION_PROFILE, exist_ok=True)
        command = [
            executable,
            f"--app={url}",
            f"--user-data-dir={CHROMIUM_SESSION_PROFILE}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-mode",
            "--disable-extensions",
            "--disable-sync",
        ]
    return subprocess.Popen(command, **_new_process_group_kwargs())


def _new_process_group_kwargs() -> dict:
    """Give each owned child a tree boundary on Windows and POSIX."""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _alive(url: str, timeout=2.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def _wait(url: str, seconds: float, label: str):
    print(f"  waiting for {label} ...", end="", flush=True)
    t0 = time.time()
    while time.time() - t0 < seconds:
        r = _alive(url)
        if r is not None:
            print(" ALIVE")
            return r
        print(".", end="", flush=True)
        time.sleep(1.5)
    print(" TIMED OUT")
    return None


def _spawn(args, logname: str) -> int:
    os.makedirs(LOGDIR, exist_ok=True)
    log = open(os.path.join(LOGDIR, logname), "a", encoding="utf-8")
    log.write(f"\n=== boot {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    p = subprocess.Popen(
        [sys.executable, "-X", "utf8"] + args, cwd=ROOT,
        stdout=log, stderr=subprocess.STDOUT,
        **_new_process_group_kwargs())
    return p.pid


def _stop_process_tree(pid) -> bool:
    """Stop one process boundary without assuming a particular desktop OS."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if os.name == "nt":
        return subprocess.call(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL) == 0
    try:
        group = os.getpgid(pid)
        if group == pid:
            os.killpg(group, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def _checkpoint_household(run: dict) -> dict:
    """Ask the router for positive resident receipts before force cleanup."""
    port = run.get("router_port") if isinstance(run, dict) else None
    if not port:
        return {"verdict": "unknown", "reason": "router_port_absent"}
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/shutdown/checkpoint",
        data=b"{}", headers={"Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(request, timeout=35.0) as response:
            return json.loads(response.read())
    except Exception as exc:
        return {
            "verdict": "unknown",
            "reason": f"router_checkpoint_unavailable:{type(exc).__name__}",
        }


def _stop_unlocked(*, expected_generation: str | None = None,
                   expected_browser_pid: int | None = None):
    run = _read_runfile()
    if not run:
        print("No runfile — nothing recorded as running.")
        return
    if (expected_generation is not None
            and run.get("generation") != expected_generation):
        print("Session close belongs to an older household generation; "
              "the current household remains up.")
        return {"skipped": "generation_mismatch"}
    if (expected_browser_pid is not None
            and run.get("session_browser_pid") != expected_browser_pid):
        print("Session close no longer owns the current household; "
              "the current household remains up.")
        return {"skipped": "browser_owner_mismatch"}
    checkpoint = _checkpoint_household(run)
    print("  shutdown checkpoint: "
          f"{checkpoint.get('verdict', 'unknown')}"
          + (f" ({checkpoint.get('reason')})"
             if checkpoint.get("reason") else ""))
    # Close the owned window first; router next (it owns persona
    # subprocesses), then the room. Session watchers pass an expected boot
    # generation, revalidated under this same lock, so an old window cannot
    # stop a replacement household after losing the race.
    for name in ("session_browser_pid", "router_pid", "room_pid",
                 "tts_pid", "chatterbox_pid", "comfy_pid"):
        pid = run.get(name)
        if pid:
            _stop_process_tree(pid)
            print(f"  stopped {name.split('_')[0]} (pid {pid}, tree)")
    try:
        os.remove(RUNFILE)
    except FileNotFoundError:
        pass
    for legacy in LEGACY_RUNFILES:
        try:
            os.remove(legacy)
        except FileNotFoundError:
            pass
    print("Household down. Bodies persist in journals; positions reset "
          "on next boot (known v0).")


def stop(*, expected_generation: str | None = None,
         expected_browser_pid: int | None = None):
    with _boot_lock():
        return _stop_unlocked(
            expected_generation=expected_generation,
            expected_browser_pid=expected_browser_pid)


def _boot_unlocked(open_browser: bool = True):
    # already up? Report and open the door instead of double-spawning.
    run = _read_runfile()
    if run:
        router_port = run.get("router_port") if run else None
        if router_port and _alive(
                f"http://127.0.0.1:{router_port}/api/personas") \
                is not None:
            # Optional services can die without taking the household down.
            # Re-entering the canonical launcher is a real lifecycle edge:
            # reclaim a missing private renderer here instead of preserving a
            # stale PID and an Atelier that can never select PNG.
            try:
                from shell.comfyui_service import (
                    installed as comfy_installed,
                    start as start_comfyui,
                )
                if comfy_installed():
                    comfy_run = start_comfyui(wait_seconds=120.0)
                    if comfy_run.get("owned") and comfy_run.get("pid"):
                        run["comfy_pid"] = comfy_run["pid"]
                        run["comfy_endpoint"] = comfy_run.get("endpoint")
                    elif comfy_run.get("reachable"):
                        run.pop("comfy_pid", None)
                        run["comfy_endpoint"] = comfy_run.get(
                            "endpoint", "http://127.0.0.1:8188")
                    _write_runfile(run)
                    print(f"  Atelier GPU: {comfy_run.get('reason')}")
            except Exception as exc:
                print(f"  Atelier GPU held closed ({type(exc).__name__}); "
                      "the live household remains available")
            print(f"Household is ALREADY UP — router on {router_port}.")
            if open_browser:
                webbrowser.open(f"http://127.0.0.1:{router_port}/")
            return run
        print("Stale or interrupted boot receipt — reclaiming its exact "
              "process tree before booting fresh.")
        _stop_unlocked()

    room_port, router_port = _free_port(), _free_port()
    print(f"JNAIQ household boot — room:{room_port} router:{router_port}")

    comfy_run = {}
    try:
        from shell.comfyui_service import installed as comfy_installed
        from shell.comfyui_service import start as start_comfyui
        if comfy_installed():
            print("  starting private Atelier GPU renderer ...", flush=True)
            comfy_run = start_comfyui(wait_seconds=120.0)
            print(f"  Atelier GPU: {comfy_run.get('reason')}")
    except Exception as exc:
        print(f"  Atelier GPU held closed ({type(exc).__name__}); "
              "text/SVG household boot continues")

    tts_run = {}
    try:
        from shell.qwen_tts_service import installed as tts_installed
        from shell.qwen_tts_service import start as start_tts
        if tts_installed():
            print("  starting private Qwen3-TTS voice ...", flush=True)
            tts_run = start_tts(wait_seconds=20.0)
            print(f"  Qwen3-TTS: {tts_run.get('reason')}")
    except Exception as exc:
        print(f"  Qwen3-TTS held closed ({type(exc).__name__}); "
              "browser voice remains available")

    chatterbox_run = {}
    try:
        from shell.chatterbox_tts_service import installed as chatterbox_installed
        from shell.chatterbox_tts_service import start as start_chatterbox
        if chatterbox_installed():
            print("  starting private Chatterbox Turbo voice ...", flush=True)
            chatterbox_run = start_chatterbox(wait_seconds=20.0)
            print(f"  Chatterbox: {chatterbox_run.get('reason')}")
    except Exception as exc:
        print(f"  Chatterbox held closed ({type(exc).__name__}); "
              "other voices remain available")

    run = {"room_port": room_port, "router_port": router_port,
           "booted": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "generation": uuid.uuid4().hex,
           "booting": True}
    if comfy_run.get("owned") and comfy_run.get("pid"):
        run["comfy_pid"] = comfy_run["pid"]
        run["comfy_endpoint"] = comfy_run.get("endpoint")
    if tts_run.get("owned") and tts_run.get("pid"):
        run["tts_pid"] = tts_run["pid"]
        run["tts_endpoint"] = tts_run.get("endpoint")
    if chatterbox_run.get("owned") and chatterbox_run.get("pid"):
        run["chatterbox_pid"] = chatterbox_run["pid"]
        run["chatterbox_endpoint"] = chatterbox_run.get("endpoint")

    room_pid = _spawn([os.path.join("room", "host.py"),
                       "--port", str(room_port)],
                      "room_host.log")
    run["room_pid"] = room_pid
    _write_runfile(run)
    if not _wait(f"http://127.0.0.1:{room_port}/api/world", 25, "room host"):
        print("Room host failed — see logs\\room_host.log")
        _stop_unlocked()
        return None
    router_pid = _spawn([os.path.join("shell", "router.py"),
                         "--port", str(router_port),
                         "--room-url", f"http://127.0.0.1:{room_port}"],
                        "router.log")
    run["router_pid"] = router_pid
    _write_runfile(run)
    tenants = _wait(f"http://127.0.0.1:{router_port}/api/personas", 60,
                    "router")
    # An empty mapping is the healthy first-run state: the router is alive,
    # but this new home has not created its first persona yet. Only None means
    # the liveness request never succeeded.
    if tenants is None:
        print("Router failed — see logs\\router.log")
        _stop_unlocked()
        return None

    run.pop("booting", None)
    _write_runfile(run)

    print("\n  THE HOUSEHOLD IS UP\n  " + "=" * 40)
    print(f"  Je Ne Sais Quoi (status): http://127.0.0.1:{router_port}/")
    if not tenants:
        print("  No personas yet — create the first one from the workspace.")
    for pid_, info in tenants.items():
        lifecycle = info.get("lifecycle") or (
            "ready" if info.get("alive") else "stopped")
        address = (f"http://127.0.0.1:{info['port']}/"
                   if info.get("port") else "—")
        print(f"  {pid_:>6}: {address}   "
              f"[{info['model']}] {lifecycle}")
    print(f"  world:  http://127.0.0.1:{room_port}/api/world")
    if open_browser:
        webbrowser.open(f"http://127.0.0.1:{router_port}/")
    return run


def boot(open_browser: bool = True):
    with _boot_lock():
        return _boot_unlocked(open_browser=open_browser)


def run_session() -> int:
    """Own the household for exactly the life of its dedicated window."""
    run = boot(open_browser=False)
    if not run:
        return 1
    with _boot_lock():
        current = _read_runfile()
        if current and current.get("router_port") == run.get("router_port"):
            run = current
        owner = run.get("session_browser_pid")
        if owner and _pid_alive(owner):
            print("A JNAIQ session window already owns this household.")
            return 0
        url = f"http://127.0.0.1:{run['router_port']}/"
        browser = _launch_session_browser(url)
        if browser is not None:
            run["session_browser_pid"] = browser.pid
            _write_runfile(run)
    if browser is None:
        print("No supported owned session browser was found (Firefox, Edge, "
              "Chrome, Brave, or Chromium).")
        print("Opening the normal browser. Return here and press Enter "
              "when the session is over.")
        webbrowser.open(url)
        try:
            input()
        finally:
            stop(expected_generation=run.get("generation"))
        return 0

    print("\n  SESSION WINDOW OWNS THE HOUSEHOLD")
    print("  Close that window when you are done; JNAIQ will stop cleanly.")
    try:
        browser.wait()
    except KeyboardInterrupt:
        print("\nSession interrupted — stopping the household cleanly.")
    finally:
        stop(expected_generation=run.get("generation"),
             expected_browser_pid=browser.pid)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stop", action="store_true")
    ap.add_argument("--session", action="store_true")
    a = ap.parse_args()
    if a.stop:
        stop()
    elif a.session:
        raise SystemExit(run_session())
    else:
        boot()

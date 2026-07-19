"""shell/boot.py — household boot and browser-session lifecycle.
Brings up room host + router (which spawns all roster'd personas with
bodies), on FRESH OS-assigned ports every time (10048 law: never fight
a lingering socket). Liveness verified via API, never stdout. PIDs and
ports recorded to jnsq_running.json so re-runs detect the live stack
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
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNFILE = os.path.join(ROOT, "jnsq_running.json")
LOGDIR = os.path.join(ROOT, "logs")
FIREFOX_SESSION_PROFILE = os.path.join(LOGDIR, "browser-session-firefox")
CHROMIUM_SESSION_PROFILE = os.path.join(LOGDIR, "browser-session")


def _read_runfile():
    if not os.path.exists(RUNFILE):
        return None
    with open(RUNFILE, encoding="utf-8") as f:
        return json.load(f)


def _write_runfile(run: dict):
    with open(RUNFILE, "w", encoding="utf-8") as f:
        json.dump(run, f, indent=1)


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
    return subprocess.Popen(
        command, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)


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
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    return p.pid


def stop():
    run = _read_runfile()
    if not run:
        print("No runfile — nothing recorded as running.")
        return
    # Close the owned window first; router next (it owns persona
    # subprocesses), then the room. A browser-watcher racing this manual
    # stop is harmless because runfile removal is idempotent below.
    for name in ("session_browser_pid", "router_pid", "room_pid",
                 "comfy_pid"):
        pid = run.get(name)
        if pid:
            subprocess.call(["taskkill", "/F", "/T", "/PID", str(pid)],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
            print(f"  stopped {name.split('_')[0]} (pid {pid}, tree)")
    try:
        os.remove(RUNFILE)
    except FileNotFoundError:
        pass
    print("Household down. Bodies persist in journals; positions reset "
          "on next boot (known v0).")


def boot(open_browser: bool = True):
    # already up? Report and open the door instead of double-spawning.
    if os.path.exists(RUNFILE):
        run = _read_runfile()
        if _alive(f"http://127.0.0.1:{run['router_port']}/api/personas") \
                is not None:
            print(f"Household is ALREADY UP — router on {run['router_port']}.")
            if open_browser:
                webbrowser.open(f"http://127.0.0.1:{run['router_port']}/")
            return run
        print("Stale runfile (stack died) — booting fresh.")

    room_port, router_port = _free_port(), _free_port()
    print(f"JNSQ household boot — room:{room_port} router:{router_port}")

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

    room_pid = _spawn(["room\\host.py", "--port", str(room_port)],
                      "room_host.log")
    if not _wait(f"http://127.0.0.1:{room_port}/api/world", 25, "room host"):
        print("Room host failed — see logs\\room_host.log")
        return None
    router_pid = _spawn(["shell\\router.py", "--port", str(router_port),
                         "--room-url", f"http://127.0.0.1:{room_port}"],
                        "router.log")
    tenants = _wait(f"http://127.0.0.1:{router_port}/api/personas", 60,
                    "router")
    # An empty mapping is the healthy first-run state: the router is alive,
    # but this new home has not created its first persona yet. Only None means
    # the liveness request never succeeded.
    if tenants is None:
        print("Router failed — see logs\\router.log")
        return None

    run = {"room_pid": room_pid, "room_port": room_port,
           "router_pid": router_pid, "router_port": router_port,
           "booted": time.strftime("%Y-%m-%dT%H:%M:%S")}
    if comfy_run.get("owned") and comfy_run.get("pid"):
        run["comfy_pid"] = comfy_run["pid"]
        run["comfy_endpoint"] = comfy_run.get("endpoint")
    _write_runfile(run)

    print("\n  THE HOUSEHOLD IS UP\n  " + "=" * 40)
    print(f"  Je Ne Sais Quoi (status): http://127.0.0.1:{router_port}/")
    if not tenants:
        print("  No personas yet — create the first one from the workspace.")
    for pid_, info in tenants.items():
        mark = "alive" if info.get("alive") else "DOWN"
        print(f"  {pid_:>6}: http://127.0.0.1:{info['port']}/   "
              f"[{info['model']}] {mark}")
    print(f"  world:  http://127.0.0.1:{room_port}/api/world")
    if open_browser:
        webbrowser.open(f"http://127.0.0.1:{router_port}/")
    return run


def run_session() -> int:
    """Own the household for exactly the life of its dedicated window."""
    run = boot(open_browser=False)
    if not run:
        return 1
    owner = run.get("session_browser_pid")
    if owner and _pid_alive(owner):
        print("A JNSQ session window already owns this household.")
        return 0

    url = f"http://127.0.0.1:{run['router_port']}/"
    browser = _launch_session_browser(url)
    if browser is None:
        print("No supported session browser was found (Firefox, Edge, "
              "Chrome, or Brave).")
        print("Opening the normal browser. Return here and press Enter "
              "when the session is over.")
        webbrowser.open(url)
        try:
            input()
        finally:
            stop()
        return 0

    run["session_browser_pid"] = browser.pid
    _write_runfile(run)
    print("\n  SESSION WINDOW OWNS THE HOUSEHOLD")
    print("  Close that window when you are done; JNSQ will stop cleanly.")
    try:
        browser.wait()
    except KeyboardInterrupt:
        print("\nSession interrupted — stopping the household cleanly.")
    finally:
        current = _read_runfile()
        if current and current.get("session_browser_pid") == browser.pid:
            stop()
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

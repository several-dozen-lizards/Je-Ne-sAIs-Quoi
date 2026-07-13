"""shell/boot.py — one-shot household boot.
Brings up room host + router (which spawns all roster'd personas with
bodies), on FRESH OS-assigned ports every time (10048 law: never fight
a lingering socket). Liveness verified via API, never stdout. PIDs and
ports recorded to jnsq_running.json so re-runs detect the live stack
instead of spawning a rival household. --stop reads the runfile and
takes it all down.

Usage:  python shell\\boot.py          (or double-click START_NEXUS.bat)
        python shell\\boot.py --stop   (or STOP_NEXUS.bat)"""
import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNFILE = os.path.join(ROOT, "jnsq_running.json")
LOGDIR = os.path.join(ROOT, "logs")


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
    run = None
    if os.path.exists(RUNFILE):
        with open(RUNFILE, encoding="utf-8") as f:
            run = json.load(f)
    if not run:
        print("No runfile — nothing recorded as running.")
        return
    # router first (it owns the persona subprocesses), then the room
    for name in ("router_pid", "room_pid"):
        pid = run.get(name)
        if pid:
            subprocess.call(["taskkill", "/F", "/T", "/PID", str(pid)],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
            print(f"  stopped {name.split('_')[0]} (pid {pid}, tree)")
    os.remove(RUNFILE)
    print("Household down. Bodies persist in journals; positions reset "
          "on next boot (known v0).")


def boot():
    # already up? Report and open the door instead of double-spawning.
    if os.path.exists(RUNFILE):
        with open(RUNFILE, encoding="utf-8") as f:
            run = json.load(f)
        if _alive(f"http://127.0.0.1:{run['router_port']}/api/personas"):
            print(f"Household is ALREADY UP — router on {run['router_port']}.")
            webbrowser.open(f"http://127.0.0.1:{run['router_port']}/")
            return
        print("Stale runfile (stack died) — booting fresh.")

    room_port, router_port = _free_port(), _free_port()
    print(f"JNSQ household boot — room:{room_port} router:{router_port}")

    room_pid = _spawn(["room\\host.py", "--port", str(room_port)],
                      "room_host.log")
    if not _wait(f"http://127.0.0.1:{room_port}/api/world", 25, "room host"):
        print("Room host failed — see logs\\room_host.log")
        return
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
        return

    with open(RUNFILE, "w", encoding="utf-8") as f:
        json.dump({"room_pid": room_pid, "room_port": room_port,
                   "router_pid": router_pid, "router_port": router_port,
                   "booted": time.strftime("%Y-%m-%dT%H:%M:%S")}, f, indent=1)

    print("\n  THE HOUSEHOLD IS UP\n  " + "=" * 40)
    print(f"  Je Ne sAIs Quoi (status): http://127.0.0.1:{router_port}/")
    if not tenants:
        print("  No personas yet — create the first one from the workspace.")
    for pid_, info in tenants.items():
        mark = "alive" if info.get("alive") else "DOWN"
        print(f"  {pid_:>6}: http://127.0.0.1:{info['port']}/   "
              f"[{info['model']}] {mark}")
    print(f"  world:  http://127.0.0.1:{room_port}/api/world")
    webbrowser.open(f"http://127.0.0.1:{router_port}/")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stop", action="store_true")
    a = ap.parse_args()
    stop() if a.stop else boot()

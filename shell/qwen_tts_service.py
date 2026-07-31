"""Lifecycle boundary for JNSQ's optional private Qwen3-TTS runtime."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
HOME = ROOT / "local_services" / "qwen_tts"
PYTHON = HOME / ".venv" / "Scripts" / "python.exe"
ENDPOINT = "http://127.0.0.1:8191"
RUNFILE = HOME / "running.json"
LOGFILE = ROOT / "logs" / "qwen_tts.log"


def health(timeout=2.0):
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(ENDPOINT + "/health", timeout=float(timeout)) as response:
            value = json.loads(response.read().decode("utf-8"))
            return value if isinstance(value, dict) else None
    except Exception:
        return None


def installed() -> bool:
    return PYTHON.is_file()


def _read_runfile() -> dict:
    try:
        value = json.loads(RUNFILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def start(wait_seconds=20.0) -> dict:
    existing = health()
    if existing is not None:
        return {"started": False, "reachable": True, "owned": False,
                "endpoint": ENDPOINT,
                "reason": "loopback Qwen3-TTS is already alive"}
    if not installed():
        return {"started": False, "reachable": False, "owned": False,
                "endpoint": ENDPOINT,
                "reason": "isolated Qwen3-TTS runtime is not installed"}
    LOGFILE.parent.mkdir(parents=True, exist_ok=True)
    HOME.mkdir(parents=True, exist_ok=True)
    log = LOGFILE.open("a", encoding="utf-8")
    log.write(f"\n=== Qwen3-TTS start {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    creation = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | \
        getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        [str(PYTHON), "-X", "utf8", "-m", "shell.qwen_tts_server"],
        cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT,
        creationflags=creation)
    record = {"pid": process.pid, "endpoint": ENDPOINT, "owned": True,
              "started_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    RUNFILE.write_text(json.dumps(record, indent=2), encoding="utf-8")
    deadline = time.monotonic() + max(1.0, float(wait_seconds))
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return {**record, "reachable": False, "started": False,
                    "reason": f"Qwen3-TTS exited with {process.returncode}"}
        if health(1.0) is not None:
            return {**record, "reachable": True, "started": True,
                    "reason": "private Qwen3-TTS service is alive; model loads on first speech"}
        time.sleep(.25)
    return {**record, "reachable": False, "started": True,
            "reason": "Qwen3-TTS is still starting; see logs/qwen_tts.log"}


def stop() -> dict:
    record = _read_runfile()
    pid = record.get("pid") if record.get("owned") else None
    stopped = False
    if pid and os.name == "nt":
        stopped = subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(int(pid))],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            check=False).returncode == 0
    try:
        RUNFILE.unlink()
    except FileNotFoundError:
        pass
    return {"stopped": stopped, "pid": pid, "reachable": health() is not None}


def status() -> dict:
    return {"installed": installed(), "endpoint": ENDPOINT,
            "reachable": health() is not None, "runtime": str(HOME),
            "owned_run": _read_runfile()}


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--start", action="store_true")
    group.add_argument("--stop", action="store_true")
    group.add_argument("--status", action="store_true")
    args = parser.parse_args()
    value = start() if args.start else stop() if args.stop else status()
    print(json.dumps(value, indent=2))
    return 0 if args.status or args.stop or value.get("reachable") else 1


if __name__ == "__main__":
    raise SystemExit(main())

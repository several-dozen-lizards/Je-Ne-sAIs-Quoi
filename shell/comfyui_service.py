"""Lifecycle boundary for JNSQ's optional private ComfyUI portable runtime."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HOME = ROOT / "local_services" / "ComfyUI_windows_portable"
DEFAULT_ENDPOINT = "http://127.0.0.1:8188"
RUNFILE = ROOT / "local_services" / "comfyui_running.json"
LOGFILE = ROOT / "logs" / "comfyui.log"


def home() -> Path:
    return Path(os.environ.get("JNSQ_COMFY_HOME") or DEFAULT_HOME).resolve()


def health(endpoint: str = DEFAULT_ENDPOINT, timeout=2.0) -> dict | None:
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(endpoint.rstrip("/") + "/system_stats",
                         timeout=float(timeout)) as response:
            value = json.loads(response.read().decode("utf-8"))
            return value if isinstance(value, dict) else None
    except Exception:
        return None


def installed() -> bool:
    base = home()
    return (base / "python_embeded" / "python.exe").is_file() and \
        (base / "ComfyUI" / "main.py").is_file()


def _pid_is_owned_python(pid) -> bool:
    """Prove a recorded Windows PID still names this portable Python."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        query_limited_information = 0x1000
        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(
            query_limited_information, False, int(pid))
        if not handle:
            return False
        try:
            size = ctypes.c_ulong(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not kernel.QueryFullProcessImageNameW(
                    handle, 0, buffer, ctypes.byref(size)):
                return False
            expected = (home() / "python_embeded" / "python.exe").resolve()
            return Path(buffer.value).resolve() == expected
        finally:
            kernel.CloseHandle(handle)
    except (OSError, TypeError, ValueError):
        return False


def _read_runfile() -> dict:
    if not RUNFILE.is_file():
        return {}
    try:
        value = json.loads(RUNFILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def start(*, wait_seconds=120.0) -> dict:
    existing = health()
    if existing is not None:
        record = _read_runfile()
        if record.get("owned") and record.get("pid") \
                and _pid_is_owned_python(record["pid"]):
            return {**record, "started": False, "reachable": True,
                    "reason": "JNSQ's loopback ComfyUI is already alive"}
        return {"started": False, "owned": False, "reachable": True,
                "reason": "an external loopback ComfyUI is already alive"}
    if not installed():
        return {"started": False, "owned": False, "reachable": False,
                "reason": "portable ComfyUI is not installed"}
    base = home()
    python = base / "python_embeded" / "python.exe"
    main = base / "ComfyUI" / "main.py"
    LOGFILE.parent.mkdir(parents=True, exist_ok=True)
    RUNFILE.parent.mkdir(parents=True, exist_ok=True)
    log = LOGFILE.open("a", encoding="utf-8")
    log.write(f"\n=== atelier GPU start {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    command = [
        str(python), "-s", str(main),
        "--listen", "127.0.0.1", "--port", "8188",
        "--disable-auto-launch", "--disable-api-nodes",
    ]
    creation = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | \
        getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        command, cwd=str(base / "ComfyUI"), stdout=log,
        stderr=subprocess.STDOUT, creationflags=creation)
    record = {
        "pid": process.pid, "endpoint": DEFAULT_ENDPOINT,
        "home": str(base), "owned": True,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "command_policy": ["loopback", "disable_api_nodes",
                           "disable_auto_launch"],
    }
    RUNFILE.write_text(json.dumps(record, indent=2), encoding="utf-8")
    deadline = time.monotonic() + max(1.0, float(wait_seconds))
    pause = .2
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return {**record, "started": False, "reachable": False,
                    "reason": f"ComfyUI exited with {process.returncode}"}
        if health(timeout=1.0) is not None:
            return {**record, "started": True, "reachable": True,
                    "reason": "loopback ComfyUI is alive"}
        time.sleep(pause)
        pause = min(1.5, pause * 1.6)
    return {**record, "started": True, "reachable": False,
            "reason": "ComfyUI is still starting; see logs/comfyui.log"}


def stop() -> dict:
    record = _read_runfile()
    pid = (record.get("pid") if record.get("owned")
           and _pid_is_owned_python(record.get("pid")) else None)
    stopped = False
    if pid and os.name == "nt":
        result = subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(int(pid))],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            check=False)
        stopped = result.returncode == 0
    try:
        RUNFILE.unlink()
    except FileNotFoundError:
        pass
    return {"stopped": stopped, "pid": pid,
            "reachable": health() is not None}


def status() -> dict:
    return {
        "installed": installed(), "home": str(home()),
        "endpoint": DEFAULT_ENDPOINT, "reachable": health() is not None,
        "owned_run": _read_runfile(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--start", action="store_true")
    action.add_argument("--stop", action="store_true")
    action.add_argument("--status", action="store_true")
    args = parser.parse_args()
    result = start() if args.start else stop() if args.stop else status()
    print(json.dumps(result, indent=2))
    return 0 if args.status or args.stop or result.get("reachable") else 1


if __name__ == "__main__":
    raise SystemExit(main())

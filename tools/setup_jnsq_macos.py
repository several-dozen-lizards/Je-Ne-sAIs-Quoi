"""macOS setup for the public JNSQ distribution."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"
VENV_PYTHON = VENV / "bin" / "python"
IDENTITY = ROOT / ".jnsq_local.json"


def checked(label: str, command: list[str]) -> None:
    print(f"  > {label}", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-launch", action="store_true")
    parser.add_argument("--skip-identity", action="store_true")
    parser.add_argument("--non-interactive", action="store_true")
    args = parser.parse_args()

    if sys.platform != "darwin":
        print("This installer is for macOS. On Windows, run INSTALL_JNSQ.bat.")
        return 1
    if sys.version_info < (3, 10) or sys.version_info >= (3, 13):
        print("JNSQ currently supports Python 3.10 through 3.12.")
        print("Install Python 3.12 from https://www.python.org/downloads/macos/")
        return 1

    print("\n  Je Ne Sais Quoi setup for macOS")
    print("  --------------------------------")
    try:
        if not VENV_PYTHON.is_file():
            checked("Creating JNSQ's private Python environment",
                    [sys.executable, "-m", "venv", str(VENV)])
        else:
            print("  Reusing the existing .venv")
        checked("Updating the environment installer",
                [str(VENV_PYTHON), "-m", "pip", "install", "--upgrade", "pip"])
        checked("Installing JNSQ dependencies",
                [str(VENV_PYTHON), "-m", "pip", "install", "--requirement",
                 str(ROOT / "requirements.txt")])
        checked("Checking required libraries",
                [str(VENV_PYTHON), "-c",
                 "import fastapi,pydantic,requests,uvicorn,yaml;print('  Required libraries: OK')"])
        checked("Checking JNSQ source files",
                [str(VENV_PYTHON), "-m", "compileall", "-q", "adapters",
                 "core", "harness", "room", "shell"])
        for name in ("INSTALL_JNSQ.command", "START_NEXUS.command",
                     "STOP_NEXUS.command", "UPDATE_JNSQ.command"):
            path = ROOT / name
            if path.exists():
                path.chmod(path.stat().st_mode | 0o111)
        if not args.skip_identity and not IDENTITY.exists() \
                and not args.non_interactive:
            checked("Creating this installation's local owner",
                    [str(VENV_PYTHON), "-X", "utf8", "shell/first_run.py"])
    except subprocess.CalledProcessError as exc:
        print(f"\n  SETUP STOPPED: {exc}")
        print("  Nothing personal was uploaded. It is safe to run setup again.")
        return 1

    print("\n  SETUP COMPLETE")
    print("  User accounts, personas, histories, and API keys stay local.")
    if not args.no_launch and not args.non_interactive:
        answer = input("  Start Je Ne Sais Quoi now? [Y/n] ").strip().casefold()
        if answer in {"", "y", "yes"}:
            return subprocess.call(
                ["/bin/bash", str(ROOT / "START_NEXUS.command")], cwd=ROOT)
    print("  Start later by opening START_NEXUS.command.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

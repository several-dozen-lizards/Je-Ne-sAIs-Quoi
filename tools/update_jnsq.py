"""Transactional cross-platform updater used by the macOS public launcher."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_NAME = "DISTRIBUTION_MANIFEST.json"
DEFAULT_MANIFEST_URL = (
    "https://raw.githubusercontent.com/several-dozen-lizards/"
    "Je-Ne-sAIs-Quoi/main/DISTRIBUTION_MANIFEST.json")
DEFAULT_ARCHIVE_URL = (
    "https://github.com/several-dozen-lizards/"
    "Je-Ne-sAIs-Quoi/archive/refs/heads/main.zip")
LOCAL_LIFE_ROOTS = {"users", "personas", "people", "logs", "exports",
                    ".venv", ".git"}
PRIVATE_RUNTIME_NAMES = {
    ".env", ".jnsq_local.json", "jnsq_running.json", "room_world.json",
    "household_theme.json", "nexus_theme.json", "custom_presets.json",
    "conversation_background.json", "conversation_area_background.json",
    "nexus_background.json", "conversation_background.bin",
    "conversation_area_background.bin", "nexus_background.bin",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def managed(manifest: dict) -> dict[str, str]:
    value = manifest.get("managed_files") or {}
    return {str(key): str(fingerprint).casefold()
            for key, fingerprint in value.items()}


def safe_relative(value: str) -> Path:
    portable = value.replace("\\", "/")
    pure = PurePosixPath(portable)
    if not portable or pure.is_absolute() or ".." in pure.parts:
        raise ValueError(f"unsafe update path: {value}")
    parts = tuple(part for part in pure.parts if part not in {"", "."})
    if not parts:
        raise ValueError(f"unsafe update path: {value}")
    if parts[0].casefold() in LOCAL_LIFE_ROOTS:
        raise ValueError(f"update tried to manage local-life data: {value}")
    if parts[-1].casefold() in PRIVATE_RUNTIME_NAMES:
        raise ValueError(f"update tried to manage private runtime data: {value}")
    return Path(*parts)


def download_json(url: str) -> dict:
    request = urllib.request.Request(
        url, headers={"User-Agent": "JNSQ-Updater", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(request, timeout=30) as response:
        value = json.loads(response.read().decode("utf-8"))
    return value if isinstance(value, dict) else {}


def download(url: str, destination: Path) -> None:
    request = urllib.request.Request(
        url, headers={"User-Agent": "JNSQ-Updater", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(request, timeout=120) as response, \
            destination.open("wb") as handle:
        shutil.copyfileobj(response, handle)


def extract_checked(archive: Path, destination: Path) -> None:
    destination_resolved = destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            target = (destination / info.filename).resolve()
            if target != destination_resolved \
                    and destination_resolved not in target.parents:
                raise ValueError(f"archive path escapes extraction root: {info.filename}")
        bundle.extractall(destination)


def package_root(expanded: Path) -> Path:
    matches = [path.parent for path in expanded.rglob(MANIFEST_NAME)
               if path.is_file()]
    if len(matches) != 1:
        raise ValueError("downloaded archive does not contain one JNSQ package")
    return matches[0]


def venv_python(root: Path) -> Path:
    return (root / ".venv" / ("Scripts/python.exe" if os.name == "nt"
                              else "bin/python"))


def make_executable(path: Path) -> None:
    if os.name != "nt" and path.suffix == ".command" and path.exists():
        path.chmod(path.stat().st_mode | 0o111)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--manifest-url", default=DEFAULT_MANIFEST_URL)
    parser.add_argument("--archive-url", default=DEFAULT_ARCHIVE_URL)
    args = parser.parse_args()

    local_manifest_path = ROOT / MANIFEST_NAME
    local_manifest = read_json(local_manifest_path)
    local_version = str(local_manifest.get("version") or "pre-updater")
    print("\n  Je Ne Sais Quoi updater")
    print("  -----------------------")
    try:
        print(f"  > Checking GitHub (local version: {local_version})")
        remote_manifest = download_json(args.manifest_url)
        remote_version = str(remote_manifest.get("version") or "")
        remote_files = managed(remote_manifest)
        if not remote_version or not remote_files:
            raise ValueError("GitHub's update manifest is incomplete")
        print(f"  GitHub version: {remote_version}")
        if local_version == remote_version:
            print("\n  Already up to date.")
            return 0
        print(f"  Update available: {local_version} -> {remote_version}")
        if args.check_only:
            return 0
        if not args.non_interactive:
            answer = input("  Install this update now? [Y/n] ").strip().casefold()
            if answer not in {"", "y", "yes"}:
                print("  Update left untouched.")
                return 0
        if (ROOT / "jnsq_running.json").exists():
            raise RuntimeError(
                "JNSQ is running. Use STOP_NEXUS.command, then update again.")

        with tempfile.TemporaryDirectory(prefix="jnsq-update-") as temp_name:
            temp = Path(temp_name)
            archive = temp / "jnsq.zip"
            expanded = temp / "expanded"
            print(f"  > Downloading version {remote_version}")
            download(args.archive_url, archive)
            extract_checked(archive, expanded)
            package = package_root(expanded)
            package_manifest_path = package / MANIFEST_NAME
            package_manifest = read_json(package_manifest_path)
            if str(package_manifest.get("version") or "") != remote_version:
                raise ValueError("downloaded package version does not match manifest")
            package_files = managed(package_manifest)
            if package_files != remote_files:
                raise ValueError("downloaded package manifest differs from published manifest")

            print("  > Validating managed files")
            for relative, expected in package_files.items():
                rel = safe_relative(relative)
                source = package / rel
                if not source.is_file() or digest(source) != expected:
                    raise ValueError(f"fingerprint mismatch: {relative}")

            changes: list[tuple[str, Path, Path]] = []
            for relative, expected in package_files.items():
                rel = safe_relative(relative)
                source, destination = package / rel, ROOT / rel
                if not destination.is_file() or digest(destination) != expected:
                    changes.append((relative, source, destination))
            removals: list[tuple[str, Path]] = []
            remote_keys = {name.casefold() for name in package_files}
            for relative in managed(local_manifest):
                if relative.casefold() in remote_keys:
                    continue
                try:
                    destination = ROOT / safe_relative(relative)
                except ValueError:
                    continue
                if destination.is_file():
                    removals.append((relative, destination))

            requirements_changed = any(
                relative.replace("\\", "/").casefold() == "requirements.txt"
                for relative, _, _ in changes)
            python = venv_python(ROOT)
            if not python.is_file():
                raise RuntimeError(
                    "The local environment is missing. Run INSTALL_JNSQ.command first.")
            if requirements_changed:
                print("  > Installing newly required dependencies")
                result = subprocess.run(
                    [str(python), "-m", "pip", "install", "--requirement",
                     str(package / "requirements.txt")], cwd=ROOT)
                if result.returncode:
                    raise RuntimeError("dependency update failed before patching")

            rollback = temp / "rollback"
            rollback.mkdir()
            records: list[tuple[Path, bool, Path | None]] = []
            seen: set[Path] = set()
            for relative, destination in (
                    [(r, d) for r, _, d in changes] + removals):
                if destination in seen:
                    continue
                seen.add(destination)
                existed = destination.is_file()
                backup = rollback / safe_relative(relative) if existed else None
                if backup:
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(destination, backup)
                records.append((destination, existed, backup))
            manifest_backup = rollback / MANIFEST_NAME
            manifest_existed = local_manifest_path.is_file()
            if manifest_existed:
                shutil.copy2(local_manifest_path, manifest_backup)

            patch_started = True
            try:
                for _, source, destination in changes:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
                    make_executable(destination)
                for _, destination in removals:
                    destination.unlink()
                if changes or removals:
                    print("  > Checking patched source files")
                    result = subprocess.run(
                        [str(python), "-m", "compileall", "-q", "adapters",
                         "core", "harness", "room", "shell"], cwd=ROOT)
                    if result.returncode:
                        raise RuntimeError("source validation failed after patching")
                shutil.copy2(package_manifest_path, local_manifest_path)
                patch_started = False
            finally:
                if patch_started:
                    for destination, existed, backup in reversed(records):
                        if existed and backup:
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(backup, destination)
                        elif destination.exists():
                            destination.unlink()
                    if manifest_existed:
                        shutil.copy2(manifest_backup, local_manifest_path)
                    elif local_manifest_path.exists():
                        local_manifest_path.unlink()
                    print("  Previous managed files were restored.")

            print("\n  UPDATE COMPLETE")
            print(f"  Version: {remote_version}")
            print(f"  Changed managed files: {len(changes)}")
            print(f"  Retired managed files: {len(removals)}")
            print("  Local identities, personas, memories, histories, keys, and .venv were preserved.")
            print("  Start JNSQ with START_NEXUS.command.")
            return 0
    except Exception as exc:
        print(f"\n  UPDATE STOPPED: {exc}")
        print("  Existing local-life data was not intentionally managed or replaced.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

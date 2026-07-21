"""Build and reopen a deterministic non-persona AT8 JNSQ master bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import zipfile
from pathlib import Path


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_path(root: Path, track: dict) -> Path:
    extension = {"svg": "svg", "png": "png", "webp": "webp"}.get(
        track["medium"], "json")
    return root / f"{track['artifact_id']}.{extension}"


def bundle_path(track: dict) -> str:
    extension = {"svg": "svg", "png": "png", "webp": "webp"}.get(
        track["medium"], "json")
    return f"sources/{track['artifact_id']}.{extension}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input-dir", default="local_services/atelier_composition_canary")
    parser.add_argument(
        "--output-dir", default="local_services/atelier_masters_canary")
    args = parser.parse_args()
    source_root = Path(args.input_dir).resolve()
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    compositions = sorted(source_root.glob("composition_*.json"))
    if len(compositions) != 1:
        raise ValueError("AT8 verifier requires exactly one composition canary")
    composition_path = compositions[0]
    composition_bytes = composition_path.read_bytes()
    composition_sha = sha256(composition_bytes)
    artifact_id = composition_path.stem
    if not artifact_id.endswith(composition_sha[:16]):
        raise ValueError("composition content address does not match its bytes")
    graph = json.loads(composition_bytes)
    if graph.get("format") != "jnsq.composition.v1":
        raise ValueError("composition format is not admitted")
    sources = []
    entries = []
    for track in graph["tracks"]:
        path = source_path(source_root, track)
        data = path.read_bytes()
        digest = sha256(data)
        if digest != track["sha256"]:
            raise ValueError(f"source hash changed: {track['artifact_id']}")
        record = {
            "artifact_id": track["artifact_id"],
            "family": track["family"], "medium": track["medium"],
            "path": bundle_path(track), "sha256": digest,
            "variant": track["variant"],
        }
        sources.append(record)
        entries.append((record["path"], data))
    manifest = {
        "artifact": {
            "artifact_id": artifact_id, "medium": "composition",
            "sha256": composition_sha, "title": "AT8 canonical master",
        },
        "composition": {
            "format": graph["format"],
            "path": f"composition/{artifact_id}.json",
            "sha256": composition_sha,
        },
        "format": "jnsq.bundle.v1",
        "policy": {
            "autoplay": False, "external_references": False,
            "nested_compositions": False, "user_initiated": True,
        },
        "sources": sources, "timeline": graph["timeline"],
    }
    manifest_bytes = (json.dumps(
        manifest, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")) + "\n").encode("utf-8")
    ordered = [("manifest.json", manifest_bytes),
               (manifest["composition"]["path"], composition_bytes),
               *entries]
    total = sum(len(data) for _, data in ordered)
    if total > 96 * 1024 * 1024:
        raise ValueError("AT8 bundle exceeds the 96 MiB boundary")
    bundle = output / f"{artifact_id}.jnsq"
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in ordered:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 0
            archive.writestr(info, data)
    with zipfile.ZipFile(bundle) as archive:
        if archive.namelist() != [name for name, _ in ordered]:
            raise ValueError("AT8 bundle entry order changed")
        reopened = json.loads(archive.read("manifest.json"))
        if reopened != manifest:
            raise ValueError("AT8 bundle manifest changed on reopen")
        for record in sources:
            if sha256(archive.read(record["path"])) != record["sha256"]:
                raise ValueError("AT8 bundled source failed its hash receipt")
    sample_rate = 44_100
    frames = math.ceil(graph["timeline"]["return_seconds"] * sample_rate)
    receipt = {
        "ok": True, "bundle": str(bundle),
        "bundle_sha256": sha256(bundle.read_bytes()),
        "bundle_bytes": bundle.stat().st_size,
        "bundle_format": manifest["format"], "entries": len(ordered),
        "source_count": len(sources), "source_hashes_verified": True,
        "deterministic_timestamp": "1980-01-01T00:00:00",
        "compression": "store", "external_references": False,
        "autoplay": False, "user_initiated": True,
        "png_width": graph["width"], "png_height": graph["height"],
        "wav_sample_rate": sample_rate, "wav_frames": frames,
        "wav_expected_pcm_bytes": 44 + frames * 4,
        "wav_offline_boundary_admitted": frames <= 16_000_000,
        "browser_pixels_audio_required": True,
    }
    (output / "receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

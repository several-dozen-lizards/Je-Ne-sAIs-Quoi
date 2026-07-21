"""Build a non-persona AT7 cross-medium canary and print its receipt."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.atelier import (
    compile_audio_score, compile_canvas_scene, compile_composition,
    compile_scene3d,
)
from tools.verify_atelier_3d import MOTIONS as MOTIONS3D, SCENE as SCENE3D
from tools.verify_atelier_3d import VECTOR
from core.test_atelier import AUDIO_SCORE, CANVAS_MOTIONS, CANVAS_SCENE


def composition(canvas_id: str, audio_id: str, scene3d_id: str) -> dict:
    return {
        "tempo": 94, "beats": 8, "background": "#030611", "aspect": 1.25,
        "tracks": [{
            "artifact_id": canvas_id, "start_beat": 0,
            "duration_beats": 8, "gain": 0, "opacity": .72,
            "depth": -.6, "phase": .14,
        }, {
            "artifact_id": scene3d_id, "start_beat": 0,
            "duration_beats": 8, "gain": 0, "opacity": .82,
            "depth": 0, "phase": .36,
        }, {
            "artifact_id": audio_id, "start_beat": 1,
            "duration_beats": 6.5, "gain": .62, "opacity": 0,
            "depth": .6, "phase": .22,
        }],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir", default="local_services/atelier_composition_canary")
    args = parser.parse_args()
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    canvas = compile_canvas_scene(CANVAS_SCENE, CANVAS_MOTIONS, VECTOR)
    audio = compile_audio_score(AUDIO_SCORE, VECTOR)
    scene3d = compile_scene3d(SCENE3D, MOTIONS3D, VECTOR)
    sources = {}
    for prefix, compiled in (("canvas", canvas), ("audio", audio),
                             ("scene3d", scene3d)):
        artifact_id = f"{prefix}_{compiled['sha256'][:16]}"
        sources[artifact_id] = {
            "artifact_id": artifact_id, "medium": prefix,
            "variant": compiled["variant"], "sha256": compiled["sha256"],
        }
        (output / f"{artifact_id}.json").write_bytes(compiled["data"])
    canvas_id = next(key for key in sources if key.startswith("canvas_"))
    audio_id = next(key for key in sources if key.startswith("audio_"))
    scene3d_id = next(key for key in sources if key.startswith("scene3d_"))
    compiled = compile_composition(
        composition(canvas_id, audio_id, scene3d_id), sources.__getitem__, VECTOR)
    artifact = output / f"composition_{compiled['sha256'][:16]}.json"
    artifact.write_bytes(compiled["data"])
    receipt = {
        "ok": True, "artifact": str(artifact), "sha256": compiled["sha256"],
        "bytes": compiled["bytes"],
        "composition_format": compiled["composition_format"],
        "track_count": compiled["track_count"],
        "family_count": compiled["family_count"],
        "source_digest": compiled["source_digest"],
        "source_hashes": {key: value["sha256"] for key, value in sources.items()},
        "tempo_bpm": compiled["tempo_bpm"],
        "loop_seconds": compiled["loop_seconds"],
        "return_cycles": compiled["return_cycles"],
        "return_seconds": compiled["return_seconds"],
        "nested_compositions": False, "model_authored_code": False,
        "external_references": False, "host_owned_shared_clock": True,
        "autoplay": False,
    }
    (output / "receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

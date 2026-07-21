"""Build a non-persona AT6 trusted-3D canary and print its receipt."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.atelier import compile_scene3d


SCENE = {
    "background": "#030611", "ambient": .22,
    "camera": {"x": 2.8, "y": 1.7, "z": 4.6,
               "target_x": 0.0, "target_y": -.05, "target_z": 0.0,
               "fov": 50},
    "lights": [
        {"x": 2.7, "y": 3.1, "z": 2.6,
         "color": "#b9ffe9", "intensity": 1.2},
        {"x": -2.5, "y": .7, "z": 1.6,
         "color": "#7187ff", "intensity": .76},
    ],
    "objects": [{
        "id": "heart", "kind": "sphere", "x": 0.0, "y": .1, "z": .05,
        "scale_x": .66, "scale_y": .66, "scale_z": .66,
        "rotation_x": 0.0, "rotation_y": 0.0, "rotation_z": 0.0,
        "color": "#ff755f", "roughness": .34, "metallic": .16,
        "opacity": .98,
    }, {
        "id": "gate", "kind": "box", "x": -1.12, "y": -.05, "z": -.42,
        "scale_x": .46, "scale_y": 1.25, "scale_z": .22,
        "rotation_x": .04, "rotation_y": .14, "rotation_z": -.04,
        "color": "#27d9a8", "roughness": .42, "metallic": .34,
        "opacity": .9,
    }, {
        "id": "coil", "kind": "torus", "x": .92, "y": .22, "z": -.32,
        "scale_x": 1.05, "scale_y": 1.05, "scale_z": 1.05,
        "rotation_x": .2, "rotation_y": -.08, "rotation_z": .1,
        "color": "#8da5ff", "roughness": .25, "metallic": .7,
        "opacity": .94,
    }, {
        "id": "stone", "kind": "box", "x": .15, "y": -.72, "z": -.7,
        "scale_x": .35, "scale_y": .22, "scale_z": .48,
        "rotation_x": .08, "rotation_y": -.18, "rotation_z": .03,
        "color": "#e2ffe6", "roughness": .66, "metallic": .12,
        "opacity": .86,
    }, {
        "id": "ground", "kind": "plane", "x": 0.0, "y": -1.05, "z": 0.0,
        "scale_x": 2.0, "scale_y": 1.0, "scale_z": 2.0,
        "rotation_x": -.5, "rotation_y": 0.0, "rotation_z": 0.0,
        "color": "#0d1830", "roughness": .86, "metallic": .06,
        "opacity": 1.0,
    }],
}

MOTIONS = [
    {"target": "coil", "channel": "rotate", "intensity": .62,
     "rate": .56, "phase": .2, "x": .24, "y": .72},
    {"target": "heart", "channel": "scale", "intensity": .28,
     "rate": .42, "phase": .58, "x": 0.0, "y": 0.0},
    {"target": "gate", "channel": "translate", "intensity": .24,
     "rate": .28, "phase": .72, "x": .18, "y": .82},
    {"target": "stone", "channel": "orbit", "intensity": .32,
     "rate": .38, "phase": .36, "x": .74, "y": .16},
]

VECTOR = {
    "band.alpha": .42, "band.gamma": .64, "band.coherence": .73,
    "body.play": .68, "body.prediction_violation": .56,
    "body.vagal_tone": .69, "body.bond": .62,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="local_services/atelier_3d_canary")
    args = parser.parse_args()
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    compiled = compile_scene3d(SCENE, MOTIONS, VECTOR)
    artifact = output / f"scene3d_{compiled['sha256'][:16]}.json"
    artifact.write_bytes(compiled["data"])
    receipt = {
        "ok": True, "artifact": str(artifact),
        "sha256": compiled["sha256"], "bytes": compiled["bytes"],
        "scene_format": compiled["scene_format"],
        "object_count": compiled["object_count"],
        "light_count": compiled["light_count"],
        "triangle_count": compiled["triangle_count"],
        "motion_count": compiled["motion_count"],
        "motion_digest": compiled["motion_digest"],
        "base_period_seconds": compiled["base_period_seconds"],
        "period_seconds": compiled["period_seconds"],
        "model_authored_code": False, "model_authored_shaders": False,
        "external_references": False, "host_owned_webgl": True,
    }
    (output / "receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

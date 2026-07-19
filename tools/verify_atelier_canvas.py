"""Build a non-persona AT4 Canvas canary and print its content-free receipt."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.atelier import compile_canvas_scene


SCENE = {
    "aspect": 1.25, "background": "#050815", "nodes": [{
        "id": "halo", "kind": "circle", "x": .5, "y": .46,
        "radius": .28, "fill": "", "stroke": "#40e2b5",
        "line_width": .16, "opacity": .56,
    }, {
        "id": "gate", "kind": "rect", "x": .5, "y": .48,
        "width": .27, "height": .48, "corner": .3,
        "fill": "#102445", "stroke": "#8effd8", "line_width": .19,
        "opacity": .88, "rotation": -.04,
    }, {
        "id": "serpent", "kind": "path",
        "points": [[.08, .62], [.23, .28], [.39, .69], [.55, .26],
                   [.72, .68], [.91, .34]],
        "closed": False, "fill": "", "stroke": "#2be6af",
        "line_width": .34, "opacity": .96,
    }, {
        "id": "heart", "kind": "circle", "x": .54, "y": .4,
        "radius": .06, "fill": "#ff7b6b", "stroke": "#fff0b8",
        "line_width": .08, "opacity": .9,
    }, {
        "id": "field", "kind": "particles", "x": .06, "y": .06,
        "width": .88, "height": .77, "count": 110, "radius": .15,
        "fill": "#b8ffe7", "opacity": .48, "seed": .618034,
    }, {
        "id": "caption", "kind": "text", "x": .5, "y": .91,
        "text": "SCENE / CYCLE / RETURN", "fill": "#dffff2",
        "font_size": .2, "align": "center", "opacity": .8,
        "rotation": 0.0,
    }],
}

MOTIONS = [
    {"target": "halo", "channel": "scale", "intensity": .48,
     "rate": .22, "phase": .0, "x": 0.0, "y": 0.0},
    {"target": "gate", "channel": "rotate", "intensity": .24,
     "rate": .34, "phase": .22, "x": .8, "y": 0.0},
    {"target": "serpent", "channel": "translate", "intensity": .62,
     "rate": .68, "phase": .15, "x": .3, "y": -.75},
    {"target": "heart", "channel": "opacity", "intensity": .72,
     "rate": .82, "phase": .4, "x": 0.0, "y": 0.0},
    {"target": "field", "channel": "orbit", "intensity": .36,
     "rate": .56, "phase": .61, "x": .32, "y": .18},
]

VECTOR = {
    "band.alpha": .48, "band.gamma": .67, "band.coherence": .71,
    "cocktail.curiosity": .82, "cocktail.warmth": .64,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="local_services/atelier_canvas_canary")
    args = parser.parse_args()
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    compiled = compile_canvas_scene(SCENE, MOTIONS, VECTOR)
    artifact = output / f"canvas_{compiled['sha256'][:16]}.json"
    artifact.write_bytes(compiled["data"])
    receipt = {
        "ok": True, "artifact": str(artifact),
        "sha256": compiled["sha256"], "bytes": compiled["bytes"],
        "scene_format": compiled["scene_format"],
        "node_count": compiled["node_count"],
        "motion_count": compiled["motion_count"],
        "motion_digest": compiled["motion_digest"],
        "base_period_seconds": compiled["base_period_seconds"],
        "period_seconds": compiled["period_seconds"],
        "model_authored_code": False, "external_references": False,
    }
    (output / "receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

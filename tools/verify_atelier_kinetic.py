"""Build a non-persona AT3 canary and print its content-free receipt."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.atelier import compose_kinetic_svg


CANARY_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 640">
  <defs>
    <radialGradient id="night" cx="50%" cy="46%" r="72%">
      <stop offset="0" stop-color="#182550"/><stop offset="1" stop-color="#050713"/>
    </radialGradient>
    <linearGradient id="green" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#adffe0"/><stop offset="0.52" stop-color="#2de0ad"/><stop offset="1" stop-color="#087e73"/>
    </linearGradient>
    <radialGradient id="ember"><stop offset="0" stop-color="#fff4b0"/><stop offset="0.35" stop-color="#ff8a5d"/><stop offset="1" stop-color="#c3296b" stop-opacity="0"/></radialGradient>
  </defs>
  <rect width="960" height="640" fill="url(#night)"/>
  <g id="outer" fill="none" stroke="url(#green)" stroke-linecap="round">
    <ellipse cx="480" cy="320" rx="330" ry="178" stroke-width="8" opacity="0.72"/>
    <ellipse cx="480" cy="320" rx="285" ry="232" stroke-width="4" opacity="0.44" transform="rotate(-26 480 320)"/>
  </g>
  <path id="serpent" d="M178 364 C252 128 405 526 491 284 C574 52 692 510 790 244" fill="none" stroke="url(#green)" stroke-width="28" stroke-linecap="round"/>
  <circle id="heart" cx="491" cy="284" r="74" fill="url(#ember)" opacity="0.88"/>
  <g id="sparks" fill="#c9ffe9">
    <circle cx="220" cy="206" r="7"/><circle cx="708" cy="174" r="5"/>
    <circle cx="755" cy="418" r="8"/><circle cx="302" cy="486" r="4"/>
  </g>
  <text x="480" y="585" fill="#d8fff0" font-family="sans-serif" font-size="24" text-anchor="middle" opacity="0.82">BODY / VECTOR / RETURN</text>
</svg>"""

MOTIONS = [
    {"target": "outer", "channel": "rotate", "intensity": .44,
     "rate": .18, "phase": .0, "x": .72, "y": 0.0},
    {"target": "serpent", "channel": "translate", "intensity": .58,
     "rate": .61, "phase": .17, "x": .38, "y": -.82},
    {"target": "heart", "channel": "opacity", "intensity": .72,
     "rate": .74, "phase": .31, "x": 0.0, "y": 0.0},
    {"target": "sparks", "channel": "rotate", "intensity": .9,
     "rate": .86, "phase": .55, "x": -1.0, "y": 0.0},
    {"target": "sparks", "channel": "opacity", "intensity": .46,
     "rate": .91, "phase": .08, "x": 0.0, "y": 0.0},
]

VECTOR = {
    "band.alpha": .48, "band.gamma": .67, "band.coherence": .71,
    "cocktail.curiosity": .82, "cocktail.warmth": .64,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="local_services/atelier_kinetic_canary")
    args = parser.parse_args()
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    compiled = compose_kinetic_svg(CANARY_SVG, MOTIONS, VECTOR)
    svg_path = output / f"kinetic_{compiled['sha256'][:16]}.svg"
    svg_path.write_bytes(compiled["svg"].encode("utf-8"))
    page = output / "index.html"
    page.write_text(
        "<!doctype html><meta charset=utf-8><title>JNSQ AT3 kinetic canary</title>"
        "<style>html,body{margin:0;min-height:100%;background:#02030a;display:grid;"
        "place-items:center}img{width:min(92vw,960px);height:auto;box-shadow:0 0 70px "
        "#20d9a344;border-radius:20px}</style>"
        f"<img src=\"{svg_path.name}\" alt=\"JNSQ kinetic SVG canary\">",
        encoding="utf-8")
    receipt = {
        "ok": True, "artifact": str(svg_path), "page": str(page),
        "sha256": compiled["sha256"], "bytes": compiled["bytes"],
        "elements": compiled["elements"],
        "motion_count": compiled["motion_count"],
        "motion_digest": compiled["motion_digest"],
        "base_period_seconds": compiled["base_period_seconds"],
        "period_seconds": compiled["period_seconds"],
        "model_authored_animation": False, "javascript": False,
        "external_references": False,
    }
    (output / "receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Build a non-persona AT5 procedural-audio canary and print its receipt."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.atelier import compile_audio_score


SCORE = {
    "tempo": 96, "beats": 8, "tonic": 45,
    "scale": "dorian", "seed": .618034,
    "voices": [{
        "id": "coil", "wave": "triangle", "gain": .52,
        "attack": .16, "release": .46, "pan": -.28, "filter": .52,
    }, {
        "id": "answer", "wave": "sine", "gain": .36,
        "attack": .04, "release": .3, "pan": .3, "filter": .78,
    }, {
        "id": "scale", "wave": "sawtooth", "gain": .2,
        "attack": .3, "release": .62, "pan": 0.0, "filter": .24,
    }],
    "events": [
        {"voice": "coil", "beat": 0, "duration": 1.5, "degree": 0,
         "octave": 0, "velocity": .72, "probability": 1.0},
        {"voice": "answer", "beat": 1.5, "duration": .5, "degree": 4,
         "octave": 1, "velocity": .56, "probability": .78},
        {"voice": "coil", "beat": 2, "duration": 1.5, "degree": 2,
         "octave": 0, "velocity": .64, "probability": .9},
        {"voice": "answer", "beat": 3.5, "duration": .5, "degree": 6,
         "octave": 1, "velocity": .48, "probability": .62},
        {"voice": "scale", "beat": 0, "duration": 4, "degree": 0,
         "octave": -1, "velocity": .42, "probability": 1.0},
        {"voice": "coil", "beat": 4, "duration": 1.5, "degree": 3,
         "octave": 0, "velocity": .68, "probability": .92},
        {"voice": "answer", "beat": 5.5, "duration": .5, "degree": 8,
         "octave": 0, "velocity": .54, "probability": .7},
        {"voice": "coil", "beat": 6, "duration": 2, "degree": 1,
         "octave": 0, "velocity": .58, "probability": .84},
        {"voice": "scale", "beat": 4, "duration": 4, "degree": 3,
         "octave": -1, "velocity": .38, "probability": .88},
    ],
}

VECTOR = {
    "band.alpha": .43, "band.gamma": .61, "band.coherence": .72,
    "body.play": .66, "body.prediction_violation": .58,
    "body.vagal_tone": .7, "body.bond": .62,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="local_services/atelier_audio_canary")
    args = parser.parse_args()
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    compiled = compile_audio_score(SCORE, VECTOR)
    artifact = output / f"audio_{compiled['sha256'][:16]}.json"
    artifact.write_bytes(compiled["data"])
    receipt = {
        "ok": True, "artifact": str(artifact),
        "sha256": compiled["sha256"], "bytes": compiled["bytes"],
        "score_format": compiled["score_format"],
        "voice_count": compiled["voice_count"],
        "event_count": compiled["event_count"],
        "score_digest": compiled["score_digest"],
        "tempo_bpm": compiled["tempo_bpm"],
        "loop_seconds": compiled["loop_seconds"],
        "return_cycles": compiled["return_cycles"],
        "return_seconds": compiled["return_seconds"],
        "model_authored_code": False, "external_references": False,
        "autoplay": False, "host_owned_web_audio": True,
    }
    (output / "receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

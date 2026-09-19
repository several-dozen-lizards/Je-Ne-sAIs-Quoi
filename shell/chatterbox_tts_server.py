"""Private loopback Chatterbox Turbo synthesis service."""
from __future__ import annotations

import argparse
from io import BytesIO
import os
from pathlib import Path
import threading
import time

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field


ROOT = Path(__file__).resolve().parents[1]


class SynthesisRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2400)
    voice_reference: str = Field(min_length=1, max_length=1000)


class Engine:
    def __init__(self):
        self.model = None
        self.load_error = ""
        self.lock = threading.Lock()
        self.loaded_at = None

    def load(self):
        if self.model is not None:
            return self.model
        with self.lock:
            if self.model is not None:
                return self.model
            try:
                import torch
                from chatterbox.tts_turbo import ChatterboxTurboTTS
                device = "cuda" if torch.cuda.is_available() else "cpu"
                self.model = ChatterboxTurboTTS.from_pretrained(device=device)
                self.loaded_at = time.time()
                self.load_error = ""
                return self.model
            except Exception as error:
                self.load_error = str(error)[:500]
                raise

    def synthesize(self, request: SynthesisRequest):
        reference = Path(request.voice_reference).resolve()
        if (not reference.is_file() or reference.suffix.lower() != ".wav"
                or os.path.commonpath((str(ROOT), str(reference))) != str(ROOT)
                or reference.name != "chatterbox_reference.wav"):
            raise ValueError("the persona has no valid WAV voice reference")
        model = self.load()
        with self.lock:
            wav = model.generate(request.text, audio_prompt_path=str(reference))
        import soundfile as sf
        stream = BytesIO()
        samples = wav.squeeze(0).detach().cpu().numpy()
        sf.write(stream, samples, int(model.sr), format="WAV", subtype="PCM_16")
        return stream.getvalue(), int(model.sr)


def build_app() -> FastAPI:
    app = FastAPI(title="JNAIQ private Chatterbox Turbo")
    app.state.engine = Engine()

    @app.get("/health")
    def health():
        engine = app.state.engine
        return {"ok": True, "provider": "chatterbox-turbo",
                "model": "ResembleAI/chatterbox-turbo", "loaded": engine.model is not None,
                "load_error": engine.load_error}

    @app.post("/synthesize")
    def synthesize(request: SynthesisRequest):
        started = time.monotonic()
        try:
            audio, rate = app.state.engine.synthesize(request)
        except Exception as error:
            return JSONResponse(status_code=503, content={
                "error": str(error)[:500], "provider": "chatterbox-turbo"})
        return Response(audio, media_type="audio/wav", headers={
            "X-JNAIQ-Sample-Rate": str(rate),
            "X-JNAIQ-Synthesis-Ms": str(round((time.monotonic() - started) * 1000)),
            "Cache-Control": "no-store"})
    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8192)
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("Chatterbox is private loopback only")
    import uvicorn
    uvicorn.run(build_app(), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

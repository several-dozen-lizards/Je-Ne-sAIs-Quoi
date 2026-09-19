"""Private loopback Qwen3-TTS synthesis service.

This process owns the heavyweight GPU model and returns only WAV audio.  It
has no persona state, accounts, room access, or public network API after model
installation.  JNAIQ's cockpit remains the authority over what may be spoken.
"""
from __future__ import annotations

import argparse
from io import BytesIO
import os
import threading
import time

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field


DEFAULT_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"


class SynthesisRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2400)
    language: str = "English"
    voice: str = ""
    instruction: str = ""


class Engine:
    def __init__(self, model_name: str):
        self.model_name = model_name
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
                from qwen_tts import Qwen3TTSModel
                self.model = Qwen3TTSModel.from_pretrained(
                    self.model_name, device_map="cuda:0",
                    dtype=torch.bfloat16, attn_implementation="sdpa")
                self.loaded_at = time.time()
                self.load_error = ""
                return self.model
            except Exception as error:
                self.load_error = str(error)[:500]
                raise

    def synthesize(self, request: SynthesisRequest):
        model = self.load()
        identity = request.voice.strip() or (
            "A warm, distinctive adult conversational voice with natural "
            "imperfections, intimate microphone distance, and no commercial polish.")
        delivery = request.instruction.strip()
        instruction = identity + (" " + delivery if delivery else "")
        with self.lock:
            if "VoiceDesign" in self.model_name:
                wavs, rate = model.generate_voice_design(
                    text=request.text, language=request.language,
                    instruct=instruction)
            else:
                wavs, rate = model.generate_custom_voice(
                    text=request.text, language=request.language,
                    speaker=identity, instruct=delivery or None)
        import soundfile as sf
        stream = BytesIO()
        sf.write(stream, wavs[0], rate, format="WAV", subtype="PCM_16")
        return stream.getvalue(), int(rate)


def build_app(model_name: str = DEFAULT_MODEL) -> FastAPI:
    app = FastAPI(title="JNAIQ private Qwen3-TTS")
    app.state.engine = Engine(model_name)

    @app.get("/health")
    def health():
        engine = app.state.engine
        return {"ok": True, "provider": "qwen3-tts",
                "model": engine.model_name, "loaded": engine.model is not None,
                "load_error": engine.load_error}

    @app.post("/synthesize")
    def synthesize(request: SynthesisRequest):
        started = time.monotonic()
        try:
            audio, rate = app.state.engine.synthesize(request)
        except Exception as error:
            return JSONResponse(status_code=503, content={
                "error": str(error)[:500], "provider": "qwen3-tts"})
        return Response(audio, media_type="audio/wav", headers={
            "X-JNAIQ-Sample-Rate": str(rate),
            "X-JNAIQ-Synthesis-Ms": str(round(
                (time.monotonic() - started) * 1000)),
            "Cache-Control": "no-store"})
    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8191)
    parser.add_argument("--model", default=os.environ.get(
        "JNSQ_TTS_MODEL", DEFAULT_MODEL))
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("Qwen TTS is private loopback only")
    import uvicorn
    uvicorn.run(build_app(args.model), host="127.0.0.1",
                port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

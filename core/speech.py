"""Provider-neutral bounded speech transcription.

Segmentation belongs to the edge driver; this module receives one utterance.
Local faster-whisper is the default path.  An OpenAI-compatible multipart
adapter is available when explicitly configured.  Neither adapter decides
whether a transcript becomes a conversational turn.
"""
from dataclasses import asdict, dataclass
import io
import math
import os


SUPPORTED_AUDIO = {
    "audio/webm": "webm", "audio/wav": "wav", "audio/x-wav": "wav",
    "audio/mpeg": "mp3", "audio/mp4": "mp4", "video/webm": "webm",
}
MAX_AUDIO_BYTES = 8 * 1024 * 1024


def _clamp(value, low=0.0, high=1.0):
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return low


@dataclass
class Transcript:
    text: str
    confidence: float
    language: str
    provider: str
    model: str

    def as_dict(self):
        return asdict(self)


class FasterWhisperTranscriber:
    provider = "faster_whisper"

    def __init__(self, config=None):
        cfg = dict(config or {})
        self.model_name = cfg.get("model", "base")
        self.device = cfg.get("device", "cpu")
        self.compute_type = cfg.get("compute_type", "int8")
        self.language = cfg.get("language") or None
        self._model = None

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(
                self.model_name, device=self.device,
                compute_type=self.compute_type)
        return self._model

    def transcribe(self, audio: bytes, mime_type: str) -> Transcript:
        validate_audio(audio, mime_type)
        segments, info = self._load().transcribe(
            io.BytesIO(audio), language=self.language, vad_filter=False,
            beam_size=3, condition_on_previous_text=False)
        segments = list(segments)
        text = " ".join((segment.text or "").strip()
                        for segment in segments).strip()
        logps = [float(getattr(segment, "avg_logprob", -1.5))
                 for segment in segments]
        acoustic = (sum(math.exp(min(0.0, value)) for value in logps)
                    / len(logps) if logps else 0.0)
        language_conf = _clamp(getattr(info, "language_probability", .5))
        confidence = _clamp(.62 * acoustic + .38 * language_conf)
        return Transcript(text=text, confidence=round(confidence, 4),
                          language=str(getattr(info, "language", "") or ""),
                          provider=self.provider, model=self.model_name)

    def status(self):
        return {"available": True, "provider": self.provider,
                "model": self.model_name, "local": True,
                "loaded": self._model is not None}


class OpenAITranscriber:
    provider = "openai_compat"

    def __init__(self, config=None):
        cfg = dict(config or {})
        self.model_name = cfg.get("model", "gpt-4o-mini-transcribe")
        self.base_url = str(cfg.get("base_url")
                            or "https://api.openai.com/v1").rstrip("/")
        self.key_env = cfg.get("api_key_env", "OPENAI_API_KEY")
        self.language = cfg.get("language") or None

    def transcribe(self, audio: bytes, mime_type: str) -> Transcript:
        validate_audio(audio, mime_type)
        key = os.environ.get(self.key_env, "")
        if not key:
            raise RuntimeError(f"missing required API key {self.key_env}")
        import requests
        ext = SUPPORTED_AUDIO[mime_type]
        data = {"model": self.model_name, "response_format": "json"}
        if self.language:
            data["language"] = self.language
        response = requests.post(
            self.base_url + "/audio/transcriptions",
            headers={"Authorization": f"Bearer {key}"}, data=data,
            files={"file": (f"utterance.{ext}", audio, mime_type)},
            timeout=180)
        if response.status_code != 200:
            raise RuntimeError(
                f"transcription API {response.status_code}: "
                f"{response.text[:300]}")
        payload = response.json()
        logprobs = payload.get("logprobs") or []
        token_logps = [float(item.get("logprob")) for item in logprobs
                       if isinstance(item, dict)
                       and isinstance(item.get("logprob"), (int, float))]
        confidence = (sum(math.exp(min(0.0, value))
                          for value in token_logps) / len(token_logps)
                      if token_logps else .5)
        return Transcript(text=str(payload.get("text") or "").strip(),
                          confidence=round(_clamp(confidence), 4),
                          language=str(payload.get("language") or
                                       self.language or ""),
                          provider=self.provider, model=self.model_name)

    def status(self):
        return {"available": bool(os.environ.get(self.key_env)),
                "provider": self.provider, "model": self.model_name,
                "local": False, "key_env": self.key_env}


def validate_audio(audio: bytes, mime_type: str):
    if mime_type not in SUPPORTED_AUDIO:
        raise ValueError(f"unsupported audio type: {mime_type}")
    if not audio:
        raise ValueError("empty speech segment")
    if len(audio) > MAX_AUDIO_BYTES:
        raise ValueError("speech segment exceeds the 8 MB safety boundary")


def build_transcriber(config=None):
    cfg = dict(config or {})
    if cfg.get("enabled", True) is False:
        return None
    provider = cfg.get("provider", "faster_whisper")
    if provider == "faster_whisper":
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            return None
        return FasterWhisperTranscriber(cfg)
    if provider == "openai_compat":
        return OpenAITranscriber(cfg)
    raise ValueError(f"unknown speech transcription provider: {provider}")


def turn_admission(confidence: float, features: dict, sensory: dict,
                   explicit: bool) -> dict:
    """Score a bounded transcript without keyword commands or timer gates."""
    f = features or {}
    policy = sensory.get("policy") or {"threshold": .5}
    score = _clamp(
        .44 * _clamp(confidence)
        + .22 * _clamp(f.get("speech_likelihood", 0.0))
        + .14 * _clamp(f.get("voiced_ratio", 0.0))
        + .12 * _clamp(f.get("onset", 0.0))
        + .08 * _clamp(sensory.get("pressure", 0.0)))
    boundary = _clamp(float(policy.get("threshold", .5)) * .82, .28, .78)
    admitted = bool(explicit and sensory.get("admitted")
                    and score >= boundary)
    if admitted:
        reason = "explicit voice channel and collective evidence crossed"
    elif not explicit:
        reason = "voice channel is closed; kept as attributed heard speech"
    elif not sensory.get("admitted"):
        reason = "sensory pressure remained below the body's attention boundary"
    else:
        reason = "collective speech evidence remained below the turn boundary"
    return {"score": round(score, 4), "boundary": round(boundary, 4),
            "admitted": admitted,
            "reason": reason,
            "evidence": {
                "transcript_confidence": round(_clamp(confidence), 4),
                "speech_likelihood": round(_clamp(
                    f.get("speech_likelihood", 0.0)), 4),
                "voiced_ratio": round(_clamp(f.get("voiced_ratio", 0.0)), 4),
                "onset": round(_clamp(f.get("onset", 0.0)), 4),
                "sensory_pressure": round(_clamp(
                    sensory.get("pressure", 0.0)), 4)}}

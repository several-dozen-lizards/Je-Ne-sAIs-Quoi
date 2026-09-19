"""Explicit cloud TTS vessels.

Only already-projected speakable prose crosses these boundaries. API keys stay
server-side, responses are returned as audio bytes, and errors are scrubbed
before reaching the cockpit.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request


HUME_ENDPOINT = "https://api.hume.ai/v0/tts"
ELEVEN_ENDPOINT = "https://api.elevenlabs.io/v1/text-to-speech"
CLOUD_TTS_USER_AGENT = "JNAIQ-TTS/1.0"


def _settings_key(name: str) -> str:
    """Pick up keys saved after this persona process was started.

    The router receives Settings writes live, but already-running persona
    processes cannot inherit later environment changes. Re-reading the
    gitignored local store here lets the next cloud-voice request see a newly
    saved key without exposing it to the browser or requiring a persona restart.
    Replacements in the Settings-managed file win over a stale inherited value.
    """
    from shell import env_store
    env_store.load_env()
    return env_store.current_key(name).strip()


def _http_error_message(provider: str, code: int, raw: bytes) -> str:
    """Extract provider error text, including Hume's nested fault envelope."""
    try:
        detail = json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:
        detail = {}
    message = None
    if isinstance(detail, dict):
        fault = detail.get("fault")
        if isinstance(fault, dict):
            message = fault.get("faultstring")
        message = message or detail.get("message") or detail.get("error")
        nested = detail.get("detail")
        if not message and isinstance(nested, dict):
            message = (nested.get("message") or nested.get("error")
                       or nested.get("code") or nested.get("status"))
        if not message and isinstance(nested, str):
            message = nested
    message = str(message or f"HTTP {code}")[:300]
    if provider == "hume-octave" and "invalid apikey" in message.lower():
        return ("invalid Hume API key; replace HUME_API_KEY in "
                "Settings → API keys")
    if provider == "elevenlabs":
        if code == 401:
            return ("ElevenLabs authentication failed; replace "
                    "ELEVENLABS_API_KEY in Settings > API keys")
        if code == 402:
            reason = ("" if message == "HTTP 402" else f" ({message})")
            return ("ElevenLabs payment required or credit quota exhausted"
                    f"{reason}; check the account subscription, remaining "
                    "credits, and this API key's credit limit")
        if code == 403:
            reason = ("" if message == "HTTP 403" else f" ({message})")
            return ("ElevenLabs denied permission"
                    f"{reason}; check the API key's endpoint scopes and IP "
                    "allowlist")
    return message


def _voice_hume(value: str) -> dict:
    voice = str(value or "").strip()
    if not voice:
        raise ValueError("Hume Octave needs a saved voice ID or voice-library name")
    if voice.upper().startswith("HUME_AI:"):
        name = voice.split(":", 1)[1].strip()
        if not name:
            raise ValueError("Hume voice-library name is empty")
        return {"name": name, "provider": "HUME_AI"}
    if voice.upper().startswith("CUSTOM_VOICE:"):
        name = voice.split(":", 1)[1].strip()
        if not name:
            raise ValueError("Hume custom voice name is empty")
        return {"name": name, "provider": "CUSTOM_VOICE"}
    return {"id": voice}


def build_hume_request(text: str, voice: str) -> tuple[str, dict, dict]:
    key = _settings_key("HUME_API_KEY")
    if not key:
        raise ValueError("HUME_API_KEY is not set in Settings → API keys")
    payload = {"version": "2", "utterances": [{
        "text": text, "voice": _voice_hume(voice)}],
        "format": {"type": "mp3"}, "num_generations": 1}
    return HUME_ENDPOINT, {"X-Hume-Api-Key": key,
                           "User-Agent": CLOUD_TTS_USER_AGENT,
                           "Content-Type": "application/json"}, payload


def build_eleven_request(text: str, voice: str) -> tuple[str, dict, dict]:
    key = _settings_key("ELEVENLABS_API_KEY")
    voice_id = str(voice or "").strip()
    if not key:
        raise ValueError("ELEVENLABS_API_KEY is not set in Settings → API keys")
    if not voice_id:
        raise ValueError("ElevenLabs needs a voice ID")
    endpoint = (f"{ELEVEN_ENDPOINT}/{urllib.parse.quote(voice_id, safe='')}"
                "?output_format=mp3_44100_128")
    payload = {"text": text, "model_id": "eleven_v3",
               "voice_settings": {"use_speaker_boost": True}}
    return endpoint, {"xi-api-key": key,
                      "User-Agent": CLOUD_TTS_USER_AGENT,
                      "Content-Type": "application/json"}, payload


def synthesize(provider: str, text: str, voice: str,
               timeout: float = 180.0) -> tuple[bytes, str, dict]:
    try:
        if provider == "hume-octave":
            endpoint, headers, payload = build_hume_request(text, voice)
        elif provider == "elevenlabs":
            endpoint, headers, payload = build_eleven_request(text, voice)
        else:
            raise ValueError(f"unknown cloud voice provider '{provider}'")
        request = urllib.request.Request(
            endpoint, data=json.dumps(payload).encode("utf-8"),
            headers=headers, method="POST")
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(request, timeout=float(timeout)) as response:
                body = response.read()
                if provider == "hume-octave":
                    value = json.loads(body.decode("utf-8"))
                    generation = (value.get("generations") or [{}])[0]
                    audio = base64.b64decode(
                        generation.get("audio") or "", validate=True)
                    if not audio:
                        raise ValueError("Hume returned no audio")
                    result = (audio, "audio/mpeg", {
                        "request_id": str(value.get("request_id") or "")[:160],
                        "generation_id": str(
                            generation.get("generation_id") or "")[:160]})
                else:
                    if not body:
                        raise ValueError("ElevenLabs returned no audio")
                    result = (
                        body,
                        response.headers.get_content_type() or "audio/mpeg",
                        {"request_id": str(
                            response.headers.get("request-id") or "")[:160],
                         "character_cost": str(
                            response.headers.get("character-cost") or "")[:40]})
        except urllib.error.HTTPError as error:
            try:
                message = _http_error_message(
                    provider, error.code, error.read())
            except Exception:
                message = f"HTTP {error.code}"
            raise RuntimeError(
                f"{provider} refused synthesis: {str(message)[:300]}") from None
        from harness.service_health import record_service_health
        record_service_health("voice", provider, provider, status="ok")
        return result
    except Exception as error:
        from harness.service_health import record_service_health
        record_service_health(
            "voice", provider, provider, status="error", error=error)
        raise

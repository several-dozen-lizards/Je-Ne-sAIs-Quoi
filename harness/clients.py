"""Minimal model clients. Raw HTTP, no SDKs — the harness stays light.
API keys are NEVER printed, logged, or stored in this repo."""
import json
import math
import os
from urllib.parse import urlparse
import requests

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
V1_ENV_PATH = os.environ.get("JNSQ_LEGACY_ENV_PATH", "")


def resolve_anthropic_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return key
    if V1_ENV_PATH and os.path.exists(V1_ENV_PATH):
        with open(V1_ENV_PATH, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line.startswith("ANTHROPIC_API_KEY"):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("ANTHROPIC_API_KEY not found (environment or legacy path)")


def model_auth_status(spec: dict) -> dict:
    """Credential presence for a model spec, never the credential value."""
    ident = spec.get("identity") or {}
    provider = ident.get("provider")
    if provider == "anthropic_api" or ident.get("family") == "anthropic":
        try:
            resolve_anthropic_key()
            is_set = True
        except Exception:
            is_set = False
        return {"required": True, "env": "ANTHROPIC_API_KEY",
                "set": is_set}
    if provider == "openai_compat" or ident.get("family") == "openai_chat":
        env = ident.get("api_key_env") or "OPENAI_API_KEY"
        required = ident.get("locality") != "local"
        return {"required": required, "env": env,
                "set": bool(os.environ.get(env))}
    return {"required": False, "env": None, "set": True}


_LOGS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")


class OllamaClient:
    def __init__(self, spec: dict, host: str = "http://localhost:11434"):
        self.model = spec["identity"]["endpoint"]
        self.host = host
        self.stops = spec.get("prompt_structure", {}).get("stop_sequences") or []
        # spec's window_tokens drives Ollama's KV allocation (num_ctx).
        # Without this, the Modelfile's baked-in value wins and the spec
        # is decorative — 16K alloc was the 20% CPU offload (2026-07-03).
        self.num_ctx = spec.get("context", {}).get("window_tokens")
        self.last_meta = {}  # token/duration accounting from the most recent call

    def chat(self, system: str, user: str, max_tokens: int = 200,
             temperature: float = 0.3) -> str:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }
        if self.stops:
            body["options"]["stop"] = self.stops
        if self.num_ctx:
            body["options"]["num_ctx"] = self.num_ctx
        # 360s: a VRAM-evicted local model (llava/moondream squeeze) can
        # legitimately take 200s+; hanging up mid-thought loses the turn
        r = requests.post(f"{self.host}/api/chat", json=body, timeout=360)
        r.raise_for_status()
        data = r.json()
        self._record_meta(data)
        return (data.get("message", {}) or {}).get("content", "") or ""

    def _record_meta(self, data: dict):
        """Ollama hands back token + duration accounting on every reply;
        stop dropping it on the floor. Stash for callers, append to a
        dedicated readable log. Metering must never kill a turn."""
        try:
            import time
            self.last_meta = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "model": self.model,
                "prompt_tokens": data.get("prompt_eval_count"),
                "output_tokens": data.get("eval_count"),
                "prompt_ms": round((data.get("prompt_eval_duration") or 0) / 1e6),
                "gen_ms": round((data.get("eval_duration") or 0) / 1e6),
                "total_ms": round((data.get("total_duration") or 0) / 1e6),
                "load_ms": round((data.get("load_duration") or 0) / 1e6),
            }
            os.makedirs(_LOGS_DIR, exist_ok=True)
            with open(os.path.join(_LOGS_DIR, "ollama_meta.jsonl"), "a",
                      encoding="utf-8") as f:
                f.write(json.dumps(self.last_meta) + "\n")
        except Exception:
            pass  # the meter is never allowed to cost us the turn


class AnthropicClient:
    def __init__(self, spec: dict):
        self.model = spec["identity"]["endpoint"]
        self.key = resolve_anthropic_key()

    def chat(self, system: str, user: str, max_tokens: int = 200,
             temperature: float = 0.3) -> str:
        headers = {
            "x-api-key": self.key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        body = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        r = requests.post(ANTHROPIC_URL, headers=headers, json=body, timeout=120)
        if r.status_code != 200:
            raise RuntimeError(f"API {r.status_code}: {r.text[:300]}")
        data = r.json()
        return "".join(b.get("text", "") for b in data.get("content", [])
                       if b.get("type") == "text")


def resolve_temperature(policy: dict, temperature: float):
    """Map the body's expressive temperature onto one wire contract.

    The oscillator remains the source vector. A model spec may declare how
    its provider can receive that vector: dynamic (optionally bounded and
    rounded), fixed, or omitted. No provider/model names live in this law.
    """
    policy = policy or {}
    mode = policy.get("mode", "dynamic")
    if mode == "omit":
        return None
    if mode not in {"dynamic", "fixed"}:
        raise ValueError(f"unknown temperature policy mode '{mode}'")
    value = policy.get("value") if mode == "fixed" else temperature
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError("temperature policy produced a non-number")
    if not math.isfinite(value):
        raise ValueError("temperature policy produced a non-finite number")
    if policy.get("min") is not None:
        value = max(float(policy["min"]), value)
    if policy.get("max") is not None:
        value = min(float(policy["max"]), value)
    if policy.get("precision") is not None:
        precision = int(policy["precision"])
        if not 0 <= precision <= 12:
            raise ValueError("temperature precision must be between 0 and 12")
        value = round(value, precision)
    return value


def _rejected_parameter(error: dict, name: str) -> bool:
    """Recognize both OpenAI-style and compatible-provider rejections."""
    code = str(error.get("code") or "").lower()
    param = str(error.get("param") or "").lower()
    message = str(error.get("message") or "").lower()
    standard_codes = {"unsupported_parameter", "unsupported_value",
                      "invalid_parameter", "invalid_request_error"}
    return ((param == name and code in standard_codes)
            or (name in message and (bool(code) or not param)))


class OpenAICompatClient:
    """One adapter, many doors: LM Studio, llama.cpp server, vLLM,
    OpenRouter, Together, Groq — anything speaking the
    /chat/completions shape. KEY LAW: identity.api_key_env names an
    ENVIRONMENT VARIABLE (default OPENAI_API_KEY); the value never
    appears in specs, logs, or this repo. Unset env -> no auth header
    (local servers neither need nor want one)."""

    def __init__(self, spec: dict):
        ident = spec["identity"]
        self.model = ident["endpoint"]           # the model id
        base = (ident.get("base_url") or "").rstrip("/")
        if not base:
            raise ValueError(f"spec '{ident.get('name')}' is family "
                             f"openai_compat but has no identity."
                             f"base_url")
        self.url = base + "/chat/completions"
        # OpenAI proper retired `max_tokens` for modern GPT-5 Chat
        # Completions. Most compatible providers still use the older
        # spelling and translate it themselves, so choose by wire host.
        self.token_limit_param = ident.get("token_limit_param") or (
            "max_completion_tokens"
            if urlparse(base).hostname == "api.openai.com"
            else "max_tokens")
        self.key_env = ident.get("api_key_env") or "OPENAI_API_KEY"
        self.key = os.environ.get(self.key_env, "")
        if ident.get("locality") != "local" and not self.key:
            raise RuntimeError(
                f"missing required API key {self.key_env} for "
                f"model '{ident.get('name') or self.model}'")
        self.stops = spec.get("prompt_structure", {}) \
                         .get("stop_sequences") or []
        self.temperature_policy = ((spec.get("sampling") or {})
                                   .get("temperature") or {})

    def chat(self, system: str, user: str, max_tokens: int = 200,
             temperature: float = 0.3) -> str:
        headers = {"content-type": "application/json"}
        if self.key:
            headers["authorization"] = f"Bearer {self.key}"
        body = {
            "model": self.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        wire_temperature = resolve_temperature(self.temperature_policy,
                                               temperature)
        if wire_temperature is not None:
            body["temperature"] = wire_temperature
        body[self.token_limit_param] = max_tokens
        if self.stops:
            body["stop"] = self.stops
        # 360s, same reasoning as Ollama: a local server juggling VRAM
        # can legitimately take minutes; hanging up loses the turn
        r = requests.post(self.url, headers=headers, json=body, timeout=360)
        # Compatible APIs differ on a few optional Chat Completions
        # parameters. Invalid requests consume no generation; adapt once
        # when the provider explicitly names a safe optional parameter.
        if r.status_code == 400:
            try:
                error = (r.json().get("error") or {})
            except Exception:
                error = {}
            param = error.get("param")
            code = error.get("code")
            if code == "unsupported_parameter" and param == "max_tokens" \
                    and "max_tokens" in body:
                body["max_completion_tokens"] = body.pop("max_tokens")
                r = requests.post(self.url, headers=headers, json=body,
                                  timeout=360)
            elif ((param in {"temperature", "stop"}
                   and _rejected_parameter(error, param) and param in body)
                  or (_rejected_parameter(error, "temperature")
                      and "temperature" in body)):
                rejected = (param if param in {"temperature", "stop"}
                            else "temperature")
                body.pop(rejected)
                r = requests.post(self.url, headers=headers, json=body,
                                  timeout=360)
        if r.status_code != 200:
            raise RuntimeError(f"API {r.status_code}: {r.text[:300]}")
        data = r.json()
        choices = data.get("choices") or []
        if not choices:
            return ""
        return (choices[0].get("message") or {}).get("content", "") or ""


def client_for(spec: dict):
    provider = spec["identity"]["provider"]
    if provider == "ollama":
        return OllamaClient(spec)
    if provider == "anthropic_api":
        return AnthropicClient(spec)
    if provider == "openai_compat":
        return OpenAICompatClient(spec)
    raise ValueError(f"Unknown provider: {provider}")

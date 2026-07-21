"""Minimal model clients. Raw HTTP, no SDKs — the harness stays light.
API keys are NEVER printed, logged, or stored in this repo."""
import json
import math
import os
import atexit
import time
from urllib.parse import urlparse
import requests

from adapters.model_events import (
    ModelExchange, ToolSpec, validate_exchanges,
)
from harness.model_call_receipts import record_model_call

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


class _PersistentHTTP:
    """One process-scoped keep-alive pool for the ordinary model mouth.

    Request headers remain call-local and the session owns no application
    cookies.  Sharing the pool therefore reuses transport without merging
    provider, persona, or prompt state.
    """
    def __init__(self):
        self.session = self._new_session()

    @staticmethod
    def _new_session():
        session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=16, pool_maxsize=32, max_retries=0,
            pool_block=True)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def post(self, *args, **kwargs):
        try:
            return self.session.post(*args, **kwargs)
        except requests.exceptions.ConnectionError:
            # Providers and local gateways routinely reap idle keep-alive
            # sockets.  If that happens before a response exists, discard
            # the pool and replay the request once on a fresh connection.
            # Streaming read failures happen after this method returns and
            # are deliberately not replayed: visible text may already exist.
            self.session.close()
            self.session = self._new_session()
            return self.session.post(*args, **kwargs)

    def close(self):
        self.session.close()


_HTTP = _PersistentHTTP()
atexit.register(_HTTP.close)


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000.0, 3)


def resolve_http_timeouts(spec: dict, default_s: float = 360.0) -> dict:
    """Resolve positive finite per-model HTTP ceilings from declarative data."""
    declared = (((spec.get("transport") or {}).get("http")) or {})
    values = {}
    for name in ("connect", "read", "write", "pool"):
        raw = declared.get(f"{name}_timeout_s")
        value = default_s if raw is None else raw
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"transport.http.{name}_timeout_s must be a number")
        if not math.isfinite(value) or value <= 0:
            raise ValueError(
                f"transport.http.{name}_timeout_s must be positive and finite")
        values[name] = value
    return values


class OllamaClient:
    def __init__(self, spec: dict, host: str = "http://localhost:11434"):
        self.model = spec["identity"]["endpoint"]
        self.host = host
        self.stops = spec.get("prompt_structure", {}).get("stop_sequences") or []
        wire = ((spec.get("wire") or {}).get("ollama") or {})
        self.think = wire.get("think")
        if self.think is not None and not isinstance(self.think, bool):
            raise ValueError("wire.ollama.think must be boolean when declared")
        self.keep_alive = wire.get("keep_alive")
        if self.keep_alive is not None \
                and not isinstance(self.keep_alive, (str, int, float)):
            raise ValueError(
                "wire.ollama.keep_alive must be a duration string or number")
        # spec's window_tokens drives Ollama's KV allocation (num_ctx).
        # Without this, the Modelfile's baked-in value wins and the spec
        # is decorative — 16K alloc was the 20% CPU offload (2026-07-03).
        self.num_ctx = spec.get("context", {}).get("window_tokens")
        self.last_meta = {}  # token/duration accounting from the most recent call

    def chat(self, system: str, user: str, max_tokens: int = 200,
             temperature: float = 0.3, images: list = None,
             on_text=None) -> str:
        started = time.perf_counter()
        first_token_ms = None
        user_message = {"role": "user", "content": user}
        if images:
            user_message["images"] = [image["data"] for image in images]
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                user_message,
            ],
            "stream": bool(on_text),
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }
        if self.stops:
            body["options"]["stop"] = self.stops
        if self.num_ctx:
            body["options"]["num_ctx"] = self.num_ctx
        if self.think is not None:
            body["think"] = self.think
        if self.keep_alive is not None:
            body["keep_alive"] = self.keep_alive
        # 360s: a VRAM-evicted local model (llava/moondream squeeze) can
        # legitimately take 200s+; hanging up mid-thought loses the turn
        try:
            r = _HTTP.post(f"{self.host}/api/chat", json=body, timeout=360,
                           stream=bool(on_text))
            r.raise_for_status()
            if on_text:
                parts = []
                final = {}
                for raw in r.iter_lines(decode_unicode=True):
                    line = (raw or "").strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    final = data
                    text = (data.get("message") or {}).get("content") or ""
                    if text:
                        if first_token_ms is None:
                            first_token_ms = _elapsed_ms(started)
                        parts.append(text)
                        on_text(text)
                r.close()
                reply = "".join(parts)
                data = final
            else:
                data = r.json()
                reply = ((data.get("message", {}) or {})
                         .get("content", "") or "")
            self._record_meta(
                data, total_ms=_elapsed_ms(started),
                first_token_ms=first_token_ms, streamed=bool(on_text))
            return reply
        except Exception as error:
            meta = {"total_ms": _elapsed_ms(started),
                    "streamed": bool(on_text),
                    "error_type": type(error).__name__}
            record_model_call("ollama", self.model, meta, status="error")
            raise

    def _record_meta(self, data: dict, *, total_ms: float = None,
                     first_token_ms: float = None,
                     streamed: bool = False):
        """Ollama hands back token + duration accounting on every reply;
        stop dropping it on the floor. Stash for callers, append to a
        dedicated readable log. Metering must never kill a turn."""
        try:
            self.last_meta = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "model": self.model,
                "prompt_tokens": data.get("prompt_eval_count"),
                "input_tokens": data.get("prompt_eval_count"),
                "output_tokens": data.get("eval_count"),
                "prompt_ms": round((data.get("prompt_eval_duration") or 0) / 1e6),
                "gen_ms": round((data.get("eval_duration") or 0) / 1e6),
                "provider_ms": round((data.get("total_duration") or 0) / 1e6),
                "total_ms": total_ms,
                "load_ms": round((data.get("load_duration") or 0) / 1e6),
                "first_token_ms": first_token_ms,
                "attempts": 1,
                "streamed": streamed,
                "finish_reason": data.get("done_reason"),
            }
            os.makedirs(_LOGS_DIR, exist_ok=True)
            with open(os.path.join(_LOGS_DIR, "ollama_meta.jsonl"), "a",
                      encoding="utf-8") as f:
                f.write(json.dumps(self.last_meta) + "\n")
            record_model_call("ollama", self.model, self.last_meta)
        except Exception:
            pass  # the meter is never allowed to cost us the turn


class AnthropicClient:
    def __init__(self, spec: dict):
        self.model = spec["identity"]["endpoint"]
        self.key = resolve_anthropic_key()
        self.last_response_meta = None

    @staticmethod
    def _usage_meta(usage: dict, *, total_ms: float,
                    first_token_ms: float = None, streamed: bool = False,
                    finish_reason: str = None) -> dict:
        usage = dict(usage or {})
        return {
            "attempts": 1,
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "cache_read_tokens": (
                usage.get("cache_read_input_tokens")
                or usage.get("cache_read_tokens")),
            "cache_write_tokens": (
                usage.get("cache_creation_input_tokens")
                or usage.get("cache_write_tokens")),
            "first_token_ms": first_token_ms,
            "total_ms": total_ms,
            "streamed": streamed,
            "finish_reason": finish_reason,
        }

    def chat(self, system: str | list, user: str, max_tokens: int = 200,
             temperature: float = 0.3, images: list = None,
             on_text=None) -> str:
        started = time.perf_counter()
        first_token_ms = None
        headers = anthropic_headers(self.key)
        body = build_anthropic_body(
            self.model, system, user, max_tokens=max_tokens,
            temperature=temperature, images=images, stream=bool(on_text))
        try:
            r = _HTTP.post(ANTHROPIC_URL, headers=headers, json=body,
                           timeout=120, stream=bool(on_text))
            if r.status_code != 200:
                raise RuntimeError(f"API {r.status_code}: {r.text[:300]}")
            if not on_text:
                data = r.json()
                reply = "".join(
                    block.get("text", "") for block in data.get("content", [])
                    if block.get("type") == "text")
                self.last_response_meta = self._usage_meta(
                    data.get("usage") or {}, total_ms=_elapsed_ms(started),
                    finish_reason=data.get("stop_reason"))
            else:
                parts = []
                usage = {}
                finish_reason = None
                for raw in r.iter_lines(decode_unicode=True):
                    line = (raw or "").strip()
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if not payload:
                        continue
                    event = json.loads(payload)
                    event_type = event.get("type")
                    if event_type == "error":
                        detail = event.get("error") or {}
                        raise RuntimeError(
                            f"API stream error: {detail.get('type', 'unknown')}")
                    if event_type == "message_start":
                        usage.update((event.get("message") or {})
                                     .get("usage") or {})
                    elif event_type == "content_block_delta":
                        delta = event.get("delta") or {}
                        text = (delta.get("text")
                                if delta.get("type") == "text_delta" else "")
                        if text:
                            if first_token_ms is None:
                                first_token_ms = _elapsed_ms(started)
                            parts.append(text)
                            on_text(text)
                    elif event_type == "message_delta":
                        usage.update(event.get("usage") or {})
                        finish_reason = ((event.get("delta") or {})
                                         .get("stop_reason")
                                         or finish_reason)
                r.close()
                reply = "".join(parts)
                self.last_response_meta = self._usage_meta(
                    usage, total_ms=_elapsed_ms(started),
                    first_token_ms=first_token_ms, streamed=True,
                    finish_reason=finish_reason)
            record_model_call(
                "anthropic_api", self.model, self.last_response_meta)
            return reply
        except Exception as error:
            meta = {"total_ms": _elapsed_ms(started),
                    "first_token_ms": first_token_ms,
                    "streamed": bool(on_text),
                    "error_type": type(error).__name__}
            self.last_response_meta = dict(meta)
            record_model_call(
                "anthropic_api", self.model, meta, status="error")
            raise


def anthropic_headers(key: str) -> dict:
    return {
        "x-api-key": key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }


def _anthropic_user_content(user: str, images: list = None):
    if not images:
        return user
    return [
        {"type": "image", "source": {
            "type": "base64", "media_type": image["media_type"],
            "data": image["data"]}}
        for image in images
    ] + [{"type": "text", "text": user}]


def _anthropic_assistant_content(exchange: ModelExchange) -> list:
    content = []
    for event in exchange.assistant.events:
        if event.kind == "text_delta":
            content.append({"type": "text", "text": event.text})
        elif event.kind == "tool_call":
            content.append({
                "type": "tool_use",
                "id": event.call.call_id,
                "name": event.call.name,
                "input": dict(event.call.arguments),
            })
    return content


def _anthropic_tool_results(exchange: ModelExchange) -> list:
    blocks = []
    for result in exchange.tool_results:
        content = result.content
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False,
                                 sort_keys=True, separators=(",", ":"))
        block = {
            "type": "tool_result",
            "tool_use_id": result.call_id,
            "content": content,
        }
        if result.is_error:
            block["is_error"] = True
        blocks.append(block)
    blocks.extend({
        "type": "text",
        "text": text,
    } for text in exchange.continuation)
    return blocks


def build_anthropic_body(model: str, system: str | list, user: str,
                         max_tokens: int = 200, temperature: float = 0.3,
                         images: list = None, tools=(), exchanges=(),
                         stream: bool = False) -> dict:
    """One request-shape truth shared by legacy and structured transports."""
    exchanges = validate_exchanges(exchanges)
    # The organism's expressive vector may legitimately run hotter than the
    # Anthropic Messages API's 0..1 wire contract (altered-state circulation
    # can lift it as high as 1.2). Preserve that internal signal and translate
    # only at the provider boundary.
    wire_temperature = max(0.0, min(1.0, float(temperature)))
    messages = [{
        "role": "user",
        "content": _anthropic_user_content(user, images),
    }]
    for exchange in exchanges:
        messages.append({
            "role": "assistant",
            "content": _anthropic_assistant_content(exchange),
        })
        messages.append({
            "role": "user",
            "content": _anthropic_tool_results(exchange),
        })
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": wire_temperature,
        "system": system,
        "messages": messages,
    }
    if tools:
        admitted = []
        for tool in tools:
            if not isinstance(tool, ToolSpec):
                raise TypeError("Anthropic tools must be ToolSpec instances")
            admitted.append({
                "name": tool.name,
                "description": tool.description,
                "input_schema": dict(tool.input_schema),
            })
        body["tools"] = admitted
    if stream:
        body["stream"] = True
    return body


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


def openai_compat_headers(key: str) -> dict:
    headers = {"content-type": "application/json"}
    if key:
        headers["authorization"] = f"Bearer {key}"
    return headers


def _openai_user_content(user: str, images: list = None):
    if not images:
        return user
    return [{"type": "text", "text": user}] + [
        {"type": "image_url", "image_url": {
            "url": (f"data:{image['media_type']};base64,"
                    f"{image['data']}"),
            "detail": image.get("detail", "auto")}}
        for image in images
    ]


def _openai_assistant_message(exchange: ModelExchange) -> dict:
    text = "".join(
        event.text for event in exchange.assistant.events
        if event.kind == "text_delta")
    calls = []
    for call in exchange.assistant.calls:
        calls.append({
            "id": call.call_id,
            "type": "function",
            "function": {
                "name": call.name,
                "arguments": json.dumps(
                    dict(call.arguments), ensure_ascii=False,
                    sort_keys=True, separators=(",", ":")),
            },
        })
    return {
        "role": "assistant",
        "content": text or None,
        "tool_calls": calls,
    }


def _openai_tool_result_messages(exchange: ModelExchange) -> list:
    messages = []
    for result in exchange.tool_results:
        content = result.content
        if not isinstance(content, str):
            content = json.dumps(
                content, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"))
        messages.append({
            "role": "tool",
            "tool_call_id": result.call_id,
            "content": content,
        })
    return messages


def build_openai_compat_body(
        model: str, system: str, user: str, *,
        token_limit_param: str = "max_tokens", max_tokens: int = 200,
        temperature: float = 0.3, temperature_policy: dict = None,
        reasoning_effort: str = None, stops=(), images: list = None,
        tools=(), exchanges=(), stream: bool = False,
        wire: dict = None) -> dict:
    """One Chat Completions request truth for text and structured paths."""
    exchanges = validate_exchanges(exchanges)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": _openai_user_content(user, images)},
    ]
    for exchange in exchanges:
        messages.append(_openai_assistant_message(exchange))
        messages.extend(_openai_tool_result_messages(exchange))
        if exchange.continuation:
            messages.append({
                "role": "user",
                "content": "\n\n".join(exchange.continuation),
            })
    body = {
        "model": model,
        "stream": bool(stream),
        "messages": messages,
    }
    wire_temperature = resolve_temperature(
        temperature_policy or {}, temperature)
    if wire_temperature is not None:
        body["temperature"] = wire_temperature
    if reasoning_effort:
        body["reasoning_effort"] = reasoning_effort
    body[token_limit_param] = max_tokens
    if stops:
        body["stop"] = list(stops)
    if tools:
        admitted = []
        for tool in tools:
            if not isinstance(tool, ToolSpec):
                raise TypeError(
                    "OpenAI-compatible tools must be ToolSpec instances")
            admitted.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": dict(tool.input_schema),
                },
            })
        body["tools"] = admitted
        body["tool_choice"] = "auto"
    wire = wire or {}
    if wire.get("tool_stream") is not None:
        body["tool_stream"] = bool(wire["tool_stream"])
    if wire.get("include_stream_usage"):
        body["stream_options"] = {"include_usage": True}
    thinking = wire.get("thinking")
    if thinking is not None:
        if not isinstance(thinking, dict) or set(thinking) != {"type"}:
            raise ValueError(
                "wire.chat_completions.thinking must contain exactly 'type'")
        thinking_type = thinking.get("type")
        if thinking_type not in {"enabled", "disabled"}:
            raise ValueError(
                "wire.chat_completions.thinking.type must be "
                "'enabled' or 'disabled'")
        body["thinking"] = {"type": thinking_type}
    return body


def openai_compat_wire_correction(body: dict, error: dict):
    """Return one copied correction and its causal parameter, or ``None``."""
    corrected = dict(body)
    param = error.get("param")
    code = error.get("code")
    if code == "unsupported_parameter" and param == "max_tokens" \
            and "max_tokens" in corrected:
        corrected["max_completion_tokens"] = corrected.pop("max_tokens")
        return corrected, "max_tokens"
    if ((param in {"temperature", "stop", "reasoning_effort"}
         and _rejected_parameter(error, param) and param in corrected)
            or (_rejected_parameter(error, "temperature")
                and "temperature" in corrected)):
        rejected = (param if param in {
            "temperature", "stop", "reasoning_effort"
        } else "temperature")
        corrected.pop(rejected)
        return corrected, rejected
    return None


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
        self.spec_name = ident.get("name") or self.model
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
        self.reasoning_effort = ((spec.get("reasoning") or {})
                                 .get("effort"))
        self.wire = (((spec.get("wire") or {})
                      .get("chat_completions")) or {})
        thinking = self.wire.get("thinking")
        self.thinking_type = (
            thinking.get("type") if isinstance(thinking, dict) else None)
        self.http_timeouts = resolve_http_timeouts(spec)
        self.requests_timeout = (
            self.http_timeouts["connect"], self.http_timeouts["read"])
        self.last_response_meta = None

    def _declared_meta(self, meta: dict = None) -> dict:
        """Attach the declarative route without recording any content."""
        declared = dict(meta or {})
        declared["spec_name"] = self.spec_name
        if self.thinking_type:
            declared["thinking_type"] = self.thinking_type
        return declared

    @staticmethod
    def _visible_content(data: dict) -> str:
        choices = data.get("choices") or []
        if not choices:
            return ""
        content = (choices[0].get("message") or {}).get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                str(part.get("text") or "") for part in content
                if isinstance(part, dict)
                and part.get("type") in {"text", "output_text"})
        return ""

    @staticmethod
    def _response_meta(data: dict, attempts: int, *, total_ms: float = None,
                       first_token_ms: float = None,
                       streamed: bool = False) -> dict:
        choices = data.get("choices") or []
        choice = choices[0] if choices else {}
        usage = data.get("usage") or {}
        details = usage.get("completion_tokens_details") or {}
        prompt_details = usage.get("prompt_tokens_details") or {}
        return {
            "attempts": attempts,
            "finish_reason": choice.get("finish_reason"),
            "input_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "output_tokens": usage.get("completion_tokens"),
            "reasoning_tokens": details.get("reasoning_tokens"),
            "cache_read_tokens": (
                prompt_details.get("cached_tokens")
                or usage.get("cache_read_tokens")),
            "cache_write_tokens": usage.get("cache_write_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "first_token_ms": first_token_ms,
            "total_ms": total_ms,
            "streamed": streamed,
        }

    @staticmethod
    def _lower_reasoning_effort(effort):
        ladder = ["high", "medium", "low", "minimal", "none"]
        if effort not in ladder:
            return effort
        return ladder[min(ladder.index(effort) + 1, len(ladder) - 1)]

    def _post(self, headers: dict, body: dict, *, stream: bool = False):
        """Post once, then shed one explicitly rejected optional control."""
        r = _HTTP.post(self.url, headers=headers, json=body,
                       timeout=self.requests_timeout,
                       stream=stream)
        if r.status_code != 400:
            return r
        try:
            error = (r.json().get("error") or {})
        except Exception:
            error = {}
        param = error.get("param")
        code = error.get("code")
        if code == "unsupported_parameter" and param == "max_tokens" \
                and "max_tokens" in body:
            body["max_completion_tokens"] = body.pop("max_tokens")
        elif ((param in {"temperature", "stop", "reasoning_effort"}
               and _rejected_parameter(error, param) and param in body)
              or (_rejected_parameter(error, "temperature")
                  and "temperature" in body)):
            rejected = (param if param in {
                "temperature", "stop", "reasoning_effort"
            } else "temperature")
            body.pop(rejected)
        else:
            return r
        return _HTTP.post(self.url, headers=headers, json=body,
                          timeout=self.requests_timeout,
                          stream=stream)

    def chat(self, system: str, user: str, max_tokens: int = 200,
             temperature: float = 0.3, images: list = None,
             on_text=None) -> str:
        started = time.perf_counter()
        first_token_ms = None
        self.last_response_meta = None
        headers = openai_compat_headers(self.key)
        body = build_openai_compat_body(
            self.model, system, user,
            token_limit_param=self.token_limit_param,
            max_tokens=max_tokens, temperature=temperature,
            temperature_policy=self.temperature_policy,
            reasoning_effort=self.reasoning_effort, stops=self.stops,
            images=images, stream=bool(on_text), wire=self.wire)
        try:
            # Same generous read ceilings as before; the persistent pool only
            # removes repeated connection setup and changes no timeout law.
            r = self._post(headers, body, stream=bool(on_text))
            if r.status_code != 200:
                raise RuntimeError(f"API {r.status_code}: {r.text[:300]}")
            if on_text:
                reply_parts = []
                finish_reason = None
                usage = {}
                for raw in r.iter_lines(decode_unicode=True):
                    line = (raw or "").strip()
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if not payload or payload == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(chunk.get("usage"), dict):
                        usage.update(chunk["usage"])
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    choice = choices[0]
                    finish_reason = choice.get("finish_reason") or finish_reason
                    content = (choice.get("delta") or {}).get("content")
                    if isinstance(content, str) and content:
                        if first_token_ms is None:
                            first_token_ms = _elapsed_ms(started)
                        reply_parts.append(content)
                        on_text(content)
                r.close()
                reply = "".join(reply_parts)
                data = {"choices": [{"finish_reason": finish_reason}],
                        "usage": usage}
            else:
                data = r.json()
                reply = self._visible_content(data)
            first_meta = self._declared_meta(self._response_meta(
                data, 1, total_ms=_elapsed_ms(started),
                first_token_ms=first_token_ms, streamed=bool(on_text)))
            self.last_response_meta = first_meta
            if reply.strip():
                record_model_call(
                    "openai_compat", self.model, self.last_response_meta)
                return reply

            # A reasoning model can spend the whole completion allowance on
            # hidden work and return no visible speech. Retry once: the new
            # ceiling grows from observed usage while reasoning steps down.
            limit_key = ("max_completion_tokens"
                         if "max_completion_tokens" in body else "max_tokens")
            limit = int(body.get(limit_key) or max_tokens)
            observed = int(first_meta.get("completion_tokens") or 0)
            increment = min(limit, observed if observed > 0 else limit)
            retry_body = dict(body)
            retry_body["stream"] = False
            retry_body[limit_key] = limit + increment
            if retry_body.get("reasoning_effort"):
                retry_body["reasoning_effort"] = self._lower_reasoning_effort(
                    retry_body["reasoning_effort"])
            r = self._post(headers, retry_body)
            if r.status_code != 200:
                raise RuntimeError(f"API {r.status_code}: {r.text[:300]}")
            retry_data = r.json()
            reply = self._visible_content(retry_data)
            retry_meta = self._declared_meta(
                self._response_meta(retry_data, 2))
            combined = dict(retry_meta)
            for key in ("input_tokens", "output_tokens", "completion_tokens",
                        "reasoning_tokens", "cache_read_tokens",
                        "cache_write_tokens", "total_tokens"):
                values = [value for value in (
                    first_meta.get(key), retry_meta.get(key))
                          if isinstance(value, (int, float))]
                combined[key] = sum(values) if values else None
            combined.update({
                "attempts": 2,
                "total_ms": _elapsed_ms(started),
                "first_token_ms": first_token_ms,
                "streamed": bool(on_text),
                "recovered_empty_reply": bool(reply.strip()),
                "completion_limit": retry_body[limit_key],
            })
            self.last_response_meta = combined
            if reply.strip():
                if on_text:
                    on_text(reply)
                record_model_call(
                    "openai_compat", self.model, self.last_response_meta)
                return reply
            meta = self.last_response_meta
            raise RuntimeError(
                "API returned no visible reply after adaptive retry "
                f"(finish_reason={meta.get('finish_reason')!r}, "
                f"completion_tokens={meta.get('completion_tokens')!r}, "
                f"reasoning_tokens={meta.get('reasoning_tokens')!r}, "
                f"completion_limit={meta.get('completion_limit')})")
        except Exception as error:
            meta = self._declared_meta(self.last_response_meta)
            meta.update({"total_ms": _elapsed_ms(started),
                         "first_token_ms": first_token_ms,
                         "streamed": bool(on_text),
                         "error_type": type(error).__name__})
            self.last_response_meta = meta
            record_model_call(
                "openai_compat", self.model, meta, status="error")
            raise


def client_for(spec: dict):
    provider = spec["identity"]["provider"]
    if provider == "ollama":
        return OllamaClient(spec)
    if provider == "anthropic_api":
        return AnthropicClient(spec)
    if provider == "openai_compat":
        return OpenAICompatClient(spec)
    raise ValueError(f"Unknown provider: {provider}")

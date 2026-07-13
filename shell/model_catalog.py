"""Discover model IDs from the same API doors JNSQ can register.

Credentials are read from environment variables and are never returned.
Discovery is advisory: a user can always type an endpoint manually when a
provider does not expose a model-list endpoint.
"""
import os
import re

import requests


ANTHROPIC_MODELS_URL = "https://api.anthropic.com/v1/models"
OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"
_ENV_NAME = re.compile(r"[A-Z][A-Z0-9_]*$")


def _response_error(response) -> RuntimeError:
    # Provider errors are useful, but cap them and never include request
    # headers (which contain the credential).
    detail = (response.text or "").replace("\r", " ").replace("\n", " ")
    return RuntimeError(f"provider returned HTTP {response.status_code}: "
                        f"{detail[:300]}")


def _ids_from_openai_shape(payload) -> list[str]:
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ValueError("provider's /models response has no data list")
    found = []
    for row in rows:
        value = row if isinstance(row, str) else (row or {}).get("id")
        if isinstance(value, str) and value.strip():
            found.append(value.strip().removeprefix("models/"))
    return sorted(set(found), key=str.casefold)


def discover_models(family: str, base_url: str = None,
                    api_key_env: str = None) -> dict:
    """Return model IDs available through a configured transport.

    Supported families mirror ``scaffold_model_spec``. OpenAI-compatible
    discovery intentionally accepts arbitrary HTTP(S) base URLs because the
    desktop owner already uses those URLs for inference (including localhost).
    """
    if family == "ollama":
        response = requests.get(OLLAMA_TAGS_URL, timeout=20)
        if response.status_code != 200:
            raise _response_error(response)
        rows = response.json().get("models") or []
        models = sorted({(row.get("name") or row.get("model") or "").strip()
                         for row in rows if isinstance(row, dict)} - {""},
                        key=str.casefold)
        return {"models": models, "source": OLLAMA_TAGS_URL}

    if family == "anthropic":
        from harness.clients import resolve_anthropic_key
        response = requests.get(
            ANTHROPIC_MODELS_URL,
            headers={"x-api-key": resolve_anthropic_key(),
                     "anthropic-version": "2023-06-01"},
            params={"limit": 1000}, timeout=30)
        if response.status_code != 200:
            raise _response_error(response)
        return {"models": _ids_from_openai_shape(response.json()),
                "source": ANTHROPIC_MODELS_URL}

    if family != "openai_compat":
        raise ValueError(f"unknown family '{family}'")

    base = (base_url or "").strip().rstrip("/")
    if not re.match(r"^https?://", base):
        raise ValueError("OpenAI-compatible discovery needs an http(s) base URL")
    key_name = (api_key_env or "").strip() or "OPENAI_API_KEY"
    if not _ENV_NAME.fullmatch(key_name):
        raise ValueError("API key env var must be UPPER_SNAKE")
    headers = {"accept": "application/json"}
    key = os.environ.get(key_name, "")
    if key:
        headers["authorization"] = f"Bearer {key}"
    url = base + "/models"
    response = requests.get(url, headers=headers, timeout=30)
    if response.status_code != 200:
        suffix = (f" ({key_name} is not set)" if not key else "")
        raise RuntimeError(str(_response_error(response)) + suffix)
    return {"models": _ids_from_openai_shape(response.json()),
            "source": url, "key_set": bool(key), "key_env": key_name}

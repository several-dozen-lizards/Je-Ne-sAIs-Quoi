"""Actionable, privacy-safe household provider health projection."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from urllib.parse import urlparse

import yaml

from harness.clients import model_auth_status
from harness.service_health import read_service_health
from harness.spec_loader import load_all, load_spec


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MODEL_LOG = os.path.join(ROOT, "logs", "model_calls.jsonl")
MAX_MODEL_BYTES = 4 * 1024 * 1024
ROUTE_SECTIONS = {
    "social": ("model",),
    "metabolism": ("idle_model",),
    "perception": ("vision_model", "avatar_vision_model",
                   "focused_vision_model"),
    "interoception": ("affect_model",),
    "consolidation": ("gist_model",),
    "agency": ("model",),
    "intention_loom": ("model",),
    "writing_desk": ("model",),
    "archive_reader": ("model",),
    "document_reader": ("model",),
    "research_desk": ("model",),
    "atelier": ("model",),
}
HARD_CODES = {
    "credit_exhausted", "missing_key", "authentication_failed",
    "permission_denied", "model_unavailable", "local_service_unreachable",
}
TRANSIENT_MINIMUM = {
    "rate_limited": 2,
    "provider_unreachable": 2,
    "timeout": 2,
    "provider_error": 3,
}


def _timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _read_model_records(path: str = None,
                        max_bytes: int = MAX_MODEL_BYTES) -> list[dict]:
    path = path or os.environ.get("JNSQ_MODEL_CALL_LOG") or DEFAULT_MODEL_LOG
    if not os.path.exists(path):
        return []
    size = os.path.getsize(path)
    with open(path, "rb") as handle:
        if size > max_bytes:
            handle.seek(-max_bytes, os.SEEK_END)
            handle.readline()
        lines = handle.read().decode("utf-8", errors="replace").splitlines()
    rows = []
    for line in lines:
        try:
            value = json.loads(line)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _model_index():
    by_name, by_endpoint = {}, {}
    for spec in load_all():
        identity = spec.get("identity") or {}
        name, endpoint = identity.get("name"), identity.get("endpoint")
        if name:
            by_name[name] = spec
        if endpoint:
            by_endpoint.setdefault(endpoint, spec)
    return by_name, by_endpoint


def _provider_label(provider: str, resource: str, indexes=None) -> str:
    by_name, by_endpoint = indexes or _model_index()
    spec = by_name.get(resource) or by_endpoint.get(resource) or {}
    identity = spec.get("identity") or {}
    base = identity.get("base_url") or ""
    host = (urlparse(base).hostname or "").lower()
    if (provider in {"anthropic_api", "anthropic"}
            or identity.get("family") == "anthropic"):
        return "Anthropic"
    if provider == "ollama" or identity.get("provider") == "ollama":
        return "Ollama"
    if provider == "hume-octave":
        return "Hume"
    if provider == "elevenlabs":
        return "ElevenLabs"
    if "api.openai.com" in host:
        return "OpenAI"
    if "api.z.ai" in host:
        return "Z.AI"
    return identity.get("service") or identity.get("provider") \
        or provider or "Provider"


def _configured_routes(personas_dir: str) -> tuple[set[str], set[str]]:
    models, voices = set(), set()
    if not os.path.isdir(personas_dir):
        return models, voices
    for name in os.listdir(personas_dir):
        path = os.path.join(personas_dir, name, "roster.yaml")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as handle:
                roster = yaml.safe_load(handle) or {}
        except Exception:
            continue
        if roster.get("kind", "model_persona") != "model_persona":
            continue
        entries = roster.get("entries") or []
        active = roster.get("current_model") or (
            entries[0].get("model") if entries else None)
        if active:
            models.add(str(active))
        for section, keys in ROUTE_SECTIONS.items():
            mapping = roster.get(section) or {}
            for key in keys:
                value = mapping.get(key)
                if value:
                    models.add(str(value))
        voice = (roster.get("voice_output") or {}).get("provider")
        if voice in {"hume-octave", "elevenlabs"}:
            voices.add(voice)
    return models, voices


def _current_configuration_issues(personas_dir: str, indexes) -> list[dict]:
    models, voices = _configured_routes(personas_dir)
    issues = []
    for name in sorted(models):
        try:
            spec = load_spec(name)
        except Exception:
            issues.append({"code": "model_unavailable", "provider": "JNAIQ",
                           "resource": name, "occurrences": 1,
                           "last_seen": "configuration"})
            continue
        auth = model_auth_status(spec)
        if auth["required"] and not auth["set"]:
            identity = spec.get("identity") or {}
            issues.append({
                "code": "missing_key",
                "provider": _provider_label(
                    identity.get("provider") or identity.get("family"),
                    name, indexes),
                "resource": name,
                "key_env": auth.get("env"),
                "occurrences": 1,
                "last_seen": "configuration",
            })
    try:
        from shell import env_store
        voice_keys = {"hume-octave": "HUME_API_KEY",
                      "elevenlabs": "ELEVENLABS_API_KEY"}
        for provider in sorted(voices):
            key = voice_keys[provider]
            if not env_store.current_key(key).strip():
                issues.append({
                    "code": "missing_key",
                    "provider": _provider_label(provider, provider, indexes),
                    "resource": provider, "key_env": key,
                    "occurrences": 1, "last_seen": "configuration",
                })
    except Exception:
        pass
    return issues


def _normalized_events(hours: int, indexes) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    events = []
    for row in _read_model_records():
        stamp = _timestamp(row.get("ts"))
        if stamp is None or stamp < cutoff:
            continue
        resource = str(row.get("spec_name") or row.get("model") or "unknown")
        provider = _provider_label(str(row.get("provider") or ""),
                                   resource, indexes)
        events.append({
            "stamp": stamp, "ts": row.get("ts"), "status": row.get("status"),
            "code": row.get("error_code"), "provider": provider,
            "resource": resource, "persona": row.get("persona"),
        })
    for row in read_service_health():
        stamp = _timestamp(row.get("ts"))
        if stamp is None or stamp < cutoff:
            continue
        resource = str(row.get("resource") or row.get("provider") or "unknown")
        events.append({
            "stamp": stamp, "ts": row.get("ts"), "status": row.get("status"),
            "code": row.get("error_code"),
            "provider": _provider_label(
                str(row.get("provider") or ""), resource, indexes),
            "resource": resource, "persona": None,
        })
    return sorted(events, key=lambda event: event["stamp"])


def _unresolved_event_issues(events: list[dict]) -> list[dict]:
    issues = []
    failures = [event for event in events
                if event["status"] != "ok" and event.get("code")]
    for failed in failures:
        code, provider, resource = (failed["code"], failed["provider"],
                                    failed["resource"])
        provider_wide = code in {
            "credit_exhausted", "authentication_failed", "permission_denied",
            "rate_limited", "provider_unreachable", "local_service_unreachable",
        }
        later_success = any(
            event["stamp"] > failed["stamp"] and event["status"] == "ok"
            and event["provider"] == provider
            and (provider_wide or event["resource"] == resource)
            for event in events)
        if later_success:
            continue
        matching = [event for event in failures
                    if event["provider"] == provider
                    and event["code"] == code
                    and (provider_wide or event["resource"] == resource)]
        latest = matching[-1]
        if latest is not failed:
            continue
        required = 1 if code in HARD_CODES else TRANSIENT_MINIMUM.get(code, 3)
        if len(matching) < required:
            continue
        issues.append({
            "code": code, "provider": provider,
            "resource": "" if provider_wide else resource,
            "occurrences": len(matching), "last_seen": latest["ts"],
            "personas": sorted({str(event["persona"]) for event in matching
                                if event.get("persona")}),
        })
    return issues


def _incident_copy(issue: dict) -> dict:
    code, provider = issue["code"], issue["provider"]
    resource = issue.get("resource") or ""
    action = {"label": "Review work routing", "href": "/settings#routing"}
    if code == "credit_exhausted":
        title = f"{provider} credits appear exhausted"
        explanation = (f"{provider} refused a live request for billing or "
                       "credit reasons.")
        fix = (f"Top up the {provider} account, or move the affected route "
               "to another model. Then retry the failed action.")
    elif code == "missing_key":
        key = issue.get("key_env") or "the required API key"
        title = f"{provider} key is missing"
        explanation = f"A configured route needs {key}, but JNAIQ cannot find it."
        fix = "Open API keys, save the key, then restart the affected resident."
        action = {"label": "Open API keys", "href": "/settings#keys"}
    elif code == "authentication_failed":
        title = f"{provider} authentication failed"
        explanation = f"{provider} rejected the configured credential."
        fix = "Replace or verify the provider key in Settings, then retry."
        action = {"label": "Open API keys", "href": "/settings#keys"}
    elif code == "permission_denied":
        title = f"{provider} denied this request"
        explanation = "The credential exists, but its account, scope, or allowlist refused access."
        fix = "Check the key's endpoint permissions, account plan, and any IP allowlist."
        action = {"label": "Open API keys", "href": "/settings#keys"}
    elif code == "model_unavailable":
        title = f"Model unavailable: {resource or provider}"
        explanation = "A configured route names a model that the local or remote provider cannot supply."
        fix = (f"If this is Ollama, install it with `ollama pull {resource}`; "
               "otherwise choose a model your provider account can access.")
    elif code == "local_service_unreachable":
        title = f"{provider} cannot be reached"
        explanation = "JNAIQ could not connect to the configured local model service."
        fix = f"Start {provider}, confirm its model is installed, then retry or restart the resident."
    elif code == "rate_limited":
        title = f"{provider} is rate-limiting requests"
        explanation = "Several recent requests were refused because the provider is at its request limit."
        fix = "Wait for the limit window to clear, reduce concurrent provider work, or choose another route."
    elif code in {"provider_unreachable", "timeout"}:
        title = f"{provider} is not responding reliably"
        explanation = "Repeated recent calls could not reach the provider or timed out."
        fix = "Check the internet or local service, then retry. Provider outages may require waiting."
    else:
        title = f"{provider} requests are failing"
        explanation = "Several recent calls failed without a more specific safe diagnosis."
        fix = "Open the content-free model-call view, verify the route and provider, then retry."
    stable = f"{provider}|{code}|{resource}"
    incident_id = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:16]
    severity = "critical" if code in {
        "credit_exhausted", "missing_key", "authentication_failed",
        "local_service_unreachable", "model_unavailable",
    } else "warning"
    return {
        "id": incident_id, "revision": str(issue.get("last_seen") or ""),
        "severity": severity, "code": code, "provider": provider,
        "resource": resource, "title": title, "explanation": explanation,
        "fix": fix, "action": action,
        "occurrences": int(issue.get("occurrences") or 1),
        "personas": list(issue.get("personas") or []),
        "last_seen": issue.get("last_seen"),
    }


def provider_health_report(personas_dir: str, hours: int = 24) -> dict:
    """Return unresolved actionable incidents, never prompts or replies."""
    hours = max(1, min(int(hours), 24 * 7))
    indexes = _model_index()
    issues = _current_configuration_issues(personas_dir, indexes)
    issues.extend(_unresolved_event_issues(_normalized_events(hours, indexes)))
    deduped = {}
    for issue in issues:
        incident = _incident_copy(issue)
        key = incident["id"]
        existing = deduped.get(key)
        if existing is None or str(incident["revision"]) > str(existing["revision"]):
            deduped[key] = incident
    incidents = sorted(
        deduped.values(),
        key=lambda item: (item["severity"] != "critical",
                          str(item.get("last_seen") or "")),
        reverse=False)
    return {
        "ok": not incidents,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "incidents": incidents,
        "privacy": "content-free provider, route, status, and repair metadata only",
        "trigger": "initial load, focus, visibility return, or completed UI work",
    }

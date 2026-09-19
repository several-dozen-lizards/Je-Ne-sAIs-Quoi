"""Local forecast -> live yurt atmosphere.

Coordinates are explicitly configured by the human and kept in a separate
local file.  The provider is queried only after that opt-in.  Forecast samples
carry their own interval; that validity window, not a polling cadence, decides
when the next observation is due.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import tempfile
import urllib.parse
import urllib.request


OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
CURRENT_FIELDS = (
    "temperature_2m,apparent_temperature,precipitation,rain,showers,"
    "snowfall,weather_code,cloud_cover,wind_speed_10m,wind_gusts_10m,is_day"
)


def _number(value, default=0.0):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def yurt_weather(current: dict) -> dict:
    """Translate model evidence into the yurt's presently reachable states."""
    code = int(_number(current.get("weather_code"), -1))
    rain = max(_number(current.get("precipitation")),
               _number(current.get("rain")),
               _number(current.get("showers")))
    snow = _number(current.get("snowfall"))
    cloud = _number(current.get("cloud_cover"))
    wind = max(_number(current.get("wind_speed_10m")),
               _number(current.get("wind_gusts_10m")))

    thunder = code in {95, 96, 99}
    severe = thunder or wind >= 55 or rain >= 7.5
    wet_code = code in set(range(51, 68)) | set(range(80, 87))
    snow_code = code in set(range(71, 78)) | {85, 86}
    if severe:
        state = "storm"
    elif rain > 0.05 or snow > 0.02 or wet_code or snow_code:
        state = "rain"  # current renderer's precipitation-capable state
    elif cloud >= 48 or code in {1, 2, 3, 45, 48}:
        state = "cloudy"
    else:
        state = "clear"
    return {
        "weather": state,
        "evidence": {
            "weather_code": code, "precipitation_mm": round(rain, 3),
            "snowfall_cm": round(snow, 3), "cloud_cover_pct": round(cloud, 1),
            "wind_kmh": round(wind, 1),
        },
    }


def _parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def normalize_response(payload: dict, *, fetched_at=None) -> dict:
    current = dict(payload.get("current") or {})
    if not current:
        raise ValueError("weather provider returned no current conditions")
    observed = _parse_time(current.get("time"))
    interval = max(60, int(_number(current.get("interval"), 900)))
    valid_until = observed + dt.timedelta(seconds=interval)
    now = fetched_at or dt.datetime.now(dt.timezone.utc)
    mapped = yurt_weather(current)
    return {
        **mapped,
        "source": "open-meteo",
        "observed_at": observed.isoformat(),
        "fetched_at": now.isoformat(),
        "valid_until": valid_until.isoformat(),
        "current": current,
    }


def resident_observation(public_status: dict) -> tuple[str, dict]:
    """Render one resident-requested observation without exposing coordinates.

    This is a reader result, not ambient prompt material.  The caller decides
    whether to queue it for a turn.
    """
    value = dict(public_status or {})
    status = dict(value.get("status") or {})
    if not value.get("enabled"):
        raise ValueError("local weather sync is off")
    if not status.get("observed_at"):
        raise ValueError("no local weather observation is available")
    current = dict(status.get("current") or {})
    evidence = dict(status.get("evidence") or {})
    label = str(value.get("location_label") or "local area")[:80]
    condition = str(status.get("weather") or "unknown")
    lines = [
        "You chose to check the household's local weather. This is one "
        "timestamped host observation, not a standing instruction or an "
        "inference about what should matter to you.",
        f"Area: {label}",
        f"Observed at: {status['observed_at']}",
        f"Provider: {status.get('source') or 'unknown'}",
        f"Rendered yurt state: {condition}",
    ]
    measures = []
    for key, label_text, suffix in (
            ("temperature_2m", "temperature", " C"),
            ("apparent_temperature", "feels like", " C"),
            ("cloud_cover", "cloud cover", "%"),
            ("wind_speed_10m", "wind", " km/h"),
            ("wind_gusts_10m", "gusts", " km/h"),
            ("precipitation", "precipitation", " mm")):
        if key in current:
            measures.append(f"{label_text} {current[key]}{suffix}")
    if measures:
        lines.append("Current measures: " + "; ".join(measures))
    if evidence.get("snowfall_cm", 0):
        lines.append(f"Snowfall: {evidence['snowfall_cm']} cm")
    if status.get("error"):
        lines.append(
            "Freshness warning: the latest refresh failed; this is the last "
            f"valid observation. Host error: {status['error']}")
    receipt = {
        "ok": True,
        "queued": True,
        "kind": "local_weather_observation",
        "observed_at": status["observed_at"],
        "valid_until": status.get("valid_until"),
        "source": status.get("source"),
        "weather": condition,
        "stale": bool(status.get("error")),
    }
    return "\n".join(lines), receipt


def fetch_weather(latitude: float, longitude: float, *, timeout=12) -> dict:
    query = urllib.parse.urlencode({
        "latitude": round(float(latitude), 3),
        "longitude": round(float(longitude), 3),
        "current": CURRENT_FIELDS,
        "timezone": "UTC",
    })
    request = urllib.request.Request(
        f"{OPEN_METEO}?{query}",
        headers={"User-Agent": "JNAIQ-local-weather/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return normalize_response(payload)


def atomic_json(path: str, value: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=os.path.basename(path) + ".", suffix=".tmp",
        dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class LocalWeather:
    def __init__(self, config_path: str, tuning_path: str):
        self.config_path = config_path
        self.tuning_path = tuning_path
        self.config = self._read(config_path)
        self.status = dict(self.config.get("last_status") or {})

    @staticmethod
    def _read(path):
        try:
            with open(path, encoding="utf-8") as handle:
                value = json.load(handle)
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def public_status(self):
        return {
            "enabled": bool(self.config.get("enabled")),
            "location_label": str(self.config.get("location_label") or ""),
            "precision": self.config.get("precision"),
            "hemisphere": self.config.get("hemisphere"),
            "status": dict(self.status),
        }

    def configure(self, *, enabled, latitude=None, longitude=None,
                  location_label=""):
        config = dict(self.config)
        config["enabled"] = bool(enabled)
        if enabled:
            lat, lon = float(latitude), float(longitude)
            if not -90 <= lat <= 90 or not -180 <= lon <= 180:
                raise ValueError("weather coordinates are outside Earth")
            # Deliberately coarse: enough for local weather without retaining a
            # house-scale coordinate.
            config["latitude"] = round(lat, 2)
            config["longitude"] = round(lon, 2)
            config["precision"] = "coordinates rounded to 0.01 degrees"
            config["hemisphere"] = "north" if lat >= 0.0 else "south"
            config["location_label"] = str(location_label or "local area")[:80]
        self.config = config
        self._save()
        return self.public_status()

    def _save(self):
        saved = dict(self.config)
        saved["last_status"] = dict(self.status)
        atomic_json(self.config_path, saved)

    def due(self, now=None):
        if not self.config.get("enabled"):
            return False
        now = now or dt.datetime.now(dt.timezone.utc)
        try:
            return now >= _parse_time(self.status.get("valid_until"))
        except (TypeError, ValueError):
            return True

    def refresh(self, fetcher=fetch_weather):
        if not self.config.get("enabled"):
            raise ValueError("local weather sync is off")
        try:
            result = fetcher(
                self.config["latitude"], self.config["longitude"])
            tuning = self._read(self.tuning_path)
            tuning["weather"] = result["weather"]
            atomic_json(self.tuning_path, tuning)
            self.status = {**result, "ok": True, "error": ""}
        except Exception as exc:
            # Hold last valid room state. Failure is visible but never becomes
            # fabricated clear weather.
            self.status = {**self.status, "ok": False,
                           "error": str(exc)[:240]}
        self._save()
        return self.public_status()

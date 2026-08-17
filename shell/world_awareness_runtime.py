"""Live adapters from canonical JNSQ systems into typed awareness episodes."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import threading
import time
from typing import Any, Iterable

from core.world_awareness import (
    DOMAINS, EXTERNAL_RESEARCH_DOMAINS, WorldAwareness,
)


def _number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _timestamp(value) -> float | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.timestamp()


def _season(month: int, hemisphere: str) -> str | None:
    north = {
        12: "winter", 1: "winter", 2: "winter",
        3: "spring", 4: "spring", 5: "spring",
        6: "summer", 7: "summer", 8: "summer",
        9: "autumn", 10: "autumn", 11: "autumn",
    }
    hemisphere = str(hemisphere or "").casefold()
    if hemisphere not in {"north", "south"}:
        return None
    value = north[int(month)]
    if hemisphere == "south":
        return {"winter": "summer", "spring": "autumn",
                "summer": "winter", "autumn": "spring"}[value]
    return value


class WorldAwarenessRuntime:
    """Read canonical state at genuine events and expose bounded observations."""

    def __init__(self, engine, research_desk_runtime=None, *, config=None,
                 now_fn=time.time):
        self.engine = engine
        self.research = research_desk_runtime
        self.config = dict(config or {})
        self.now_fn = now_fn
        self.organ = WorldAwareness(
            engine.pdir, owner=engine.persona,
            enabled="world_awareness" in getattr(engine, "enabled", set()),
            now_fn=now_fn)
        self._condition = threading.Condition()
        self._closed = False

    def set_enabled(self, enabled: bool):
        self.organ.set_enabled(enabled)
        with self._condition:
            self._condition.notify_all()

    def close(self):
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def _weather(self) -> dict:
        room = getattr(self.engine, "room", None)
        if room is None:
            return {}
        try:
            value = room.local_weather()
        except Exception:
            return {}
        return dict(value or {}) if not value.get("error") else {}

    def location(self) -> dict:
        weather = self._weather()
        return {
            "configured": bool(weather.get("enabled")),
            "label": str(weather.get("location_label") or "")[:80],
            "precision": weather.get("precision"),
            "coordinates_exposed": False,
        }

    def _observe_seasonal_light(self, *, explicit=False) -> dict:
        now = self.now_fn()
        civil = dt.datetime.fromtimestamp(now).astimezone()
        weather = self._weather()
        status = dict(weather.get("status") or {})
        current = dict(status.get("current") or {})
        is_day = current.get("is_day")
        light = ("daylight" if bool(is_day) else "night") \
            if is_day is not None else "not observed"
        hemisphere = str(weather.get("hemisphere") or
                         self.config.get("hemisphere") or "")
        season = _season(civil.month, hemisphere)
        summary = (
            f"The local civil date is {civil.strftime('%A, %B %d, %Y')}; "
            + (f"the host-configured hemisphere places it in {season}. "
               if season else
               "no hemisphere has been configured, so no season is inferred. ")
            + (f"The weather provider currently marks it as {light}."
               if is_day is not None else
               "No location-grounded daylight sample is presently available."))
        return self.organ.observe(
            "seasonal_light",
            source_key="host-civil-and-weather-light",
            summary=summary,
            facts={"civil_date": civil.date().isoformat(),
                   "season": season, "light": light,
                   "hemisphere": hemisphere or None},
            provenance={"source": (
                "host civil clock + Open-Meteo is_day"
                if is_day is not None else "host civil clock")},
            dimensions={"novelty": .38, "locality": .72,
                        "consequence": .08, "provenance": .9,
                        "freshness": .92,
                        "chosen_interest": 1.0 if explicit else 0.0},
            observed_at=now, explicit=explicit)

    def _observe_weather(self, *, explicit=False) -> dict | None:
        weather = self._weather()
        if not weather.get("enabled"):
            return None
        status = dict(weather.get("status") or {})
        if not status.get("observed_at"):
            return None
        current = dict(status.get("current") or {})
        evidence = dict(status.get("evidence") or {})
        measures = []
        for key, label, suffix in (
                ("temperature_2m", "temperature", " C"),
                ("apparent_temperature", "feels like", " C"),
                ("cloud_cover", "cloud cover", "%"),
                ("wind_speed_10m", "wind", " km/h"),
                ("wind_gusts_10m", "gusts", " km/h"),
                ("precipitation", "precipitation", " mm")):
            if key in current:
                measures.append(f"{label} {current[key]}{suffix}")
        label = str(weather.get("location_label") or "local area")[:80]
        condition = str(status.get("weather") or "unknown")
        summary = (
            f"Current provider observation for {label}: {condition}"
            + ("; " + "; ".join(measures) if measures else "") + ".")
        consequence = max(
            min(1.0, _number(evidence.get("wind_kmh")) / 70.0),
            min(1.0, _number(evidence.get("precipitation_mm")) / 10.0),
            .9 if condition == "storm" else 0.0)
        return self.organ.observe(
            "weather", source_key="open-meteo-current",
            summary=summary,
            facts={"condition": condition, "measures": measures,
                   "stale": bool(status.get("error")),
                   "observed_at": status.get("observed_at")},
            provenance={"source": status.get("source") or "open-meteo",
                        "observed_at": status.get("observed_at"),
                        "valid_until": status.get("valid_until")},
            dimensions={"novelty": .58, "locality": 1.0,
                        "consequence": consequence, "provenance": .94,
                        "freshness": .9 if not status.get("error") else .28,
                        "chosen_interest": 1.0 if explicit else 0.0},
            observed_at=_timestamp(status.get("observed_at")) or self.now_fn(),
            valid_until=_timestamp(status.get("valid_until")),
            explicit=explicit)

    def _observe_household(self, *, explicit=False) -> dict | None:
        room = getattr(self.engine, "room", None)
        if room is None or not room.room_id:
            return None
        try:
            snapshot = room.snapshot()
        except Exception:
            return None
        members = sorted(str(value) for value in
                         dict(snapshot.get("members") or {}).keys())
        objects = dict(snapshot.get("objects") or {})
        room_name = str(snapshot.get("name") or room.room_id)
        summary = (
            f"In {room_name}, present members are "
            f"{', '.join(members) if members else 'none'}; "
            f"{len(objects)} shared objects are represented by the room host.")
        return self.organ.observe(
            "household", source_key=f"room:{room.room_id}:presence",
            summary=summary,
            facts={"room_id": room.room_id, "members": members,
                   "object_count": len(objects)},
            provenance={"source": "host-authoritative room snapshot",
                        "room_id": room.room_id},
            dimensions={"novelty": .72, "locality": 1.0,
                        "consequence": .22, "provenance": 1.0,
                        "freshness": .98,
                        "chosen_interest": 1.0 if explicit else 0.0},
            explicit=explicit)

    def _observe_resources(self, *, explicit=False) -> dict:
        mailbox = getattr(self.engine, "resident_event_mailbox", None)
        mailbox_state = mailbox.status() if mailbox is not None else {}
        leases = getattr(self.engine, "resident_leases", None)
        lease_state = leases.status() if leases is not None else {}
        depth = int(mailbox_state.get("depth") or 0)
        capacity = max(1, int(mailbox_state.get("capacity") or 1))
        ratio = depth / capacity
        pressure = ("open" if ratio < .35 else
                    "occupied" if ratio < .75 else "congested")
        enabled = sorted(getattr(self.engine, "enabled", set()))
        model = str(getattr(self.engine, "model", "unknown"))
        summary = (
            f"The current vessel is {model}; {len(enabled)} organs are enabled. "
            f"The resident event mailbox is {pressure} at {depth}/{capacity}. "
            "Lease state is host-observed and does not revoke resident agency.")
        return self.organ.observe(
            "resources", source_key="runtime-capacity",
            summary=summary,
            facts={"model": model, "enabled_organs": enabled,
                   "mailbox_pressure": pressure, "mailbox_depth": depth,
                   "mailbox_capacity": capacity,
                   "leases": lease_state},
            provenance={"source": "local runtime receipts"},
            dimensions={"novelty": .4, "locality": 1.0,
                        "consequence": ratio, "provenance": 1.0,
                        "freshness": 1.0,
                        "chosen_interest": 1.0 if explicit else 0.0},
            explicit=explicit)

    def _observe_capabilities(self, *, explicit=False) -> dict:
        """Describe the live host surface and real changes from its baseline."""
        enabled = sorted(getattr(self.engine, "enabled", set()))
        hosted = dict(getattr(self.engine, "_volitional_actions", {}) or {})
        actions = sorted(
            name for name, value in hosted.items()
            if value and str(value[0]) in enabled)
        prompt = dict(getattr(self.engine, "prompt_runtime", {}) or {})
        contract = {
            "mode": str(prompt.get("mode") or "unknown"),
            "profile": str(prompt.get("profile") or ""),
            "profile_revision": prompt.get("profile_revision"),
            "render_sha256": str(prompt.get("render_sha256") or ""),
            "enabled_actionable_capabilities": sorted(
                prompt.get("enabled_actionable_capabilities") or ()),
        }
        source_key = "host-capability-surface"
        prior = self.organ.latest_episode(
            "capabilities", source_key=source_key)
        prior_facts = dict((prior or {}).get("facts") or {})
        prior_organs = set(prior_facts.get("enabled_organs") or ())
        prior_actions = set(prior_facts.get("action_verbs") or ())
        added_organs = sorted(set(enabled) - prior_organs) if prior else []
        removed_organs = sorted(prior_organs - set(enabled)) if prior else []
        added_actions = sorted(set(actions) - prior_actions) if prior else []
        removed_actions = sorted(prior_actions - set(actions)) if prior else []
        prior_contract = dict(prior_facts.get("prompt_contract") or {})
        contract_changed = bool(prior and prior_contract != contract)
        changes = []
        for label, values in (
                ("added organs", added_organs),
                ("removed organs", removed_organs),
                ("added action verbs", added_actions),
                ("removed action verbs", removed_actions)):
            if values:
                changes.append(f"{label}: {', '.join(values)}")
        if contract_changed and not changes:
            changes.append("the compiled capability contract changed")
        if changes:
            lead = "The host capability surface changed: " + "; ".join(changes)
        else:
            lead = "The current host capability surface established a baseline"
        summary = (
            f"{lead}. It currently exposes {len(enabled)} enabled organs and "
            f"{len(actions)} resident-chosen action verbs. Availability is not "
            "intention, identity, obligation, or evidence of a particular "
            "subjective response.")
        change_count = (len(added_organs) + len(removed_organs)
                        + len(added_actions) + len(removed_actions)
                        + int(contract_changed))
        facts = {
            "enabled_organs": enabled,
            "action_verbs": actions,
            "added_organs": added_organs,
            "removed_organs": removed_organs,
            "added_action_verbs": added_actions,
            "removed_action_verbs": removed_actions,
            "prompt_contract_changed": contract_changed,
            "prompt_contract": contract,
        }
        return self.organ.observe(
            "capabilities", source_key=source_key, summary=summary,
            facts=facts,
            fingerprint_basis={
                "enabled_organs": enabled, "action_verbs": actions,
                "prompt_contract": contract,
            },
            provenance={"source": "local host capability registry"},
            dimensions={
                "novelty": min(1.0, .42 + .12 * change_count),
                "locality": 1.0,
                "consequence": min(1.0, .22 + .1 * change_count),
                "provenance": 1.0, "freshness": 1.0,
                "chosen_interest": 1.0 if explicit else 0.0,
            }, explicit=explicit)

    def _project_counts(self) -> dict:
        result = {}
        values = {
            "intentions": getattr(self.engine, "intention_loom_runtime", None),
            "writing": getattr(self.engine, "writing_desk_runtime", None),
            "research": self.research,
            "atelier": getattr(self.engine, "atelier_runtime", None),
        }
        for name, runtime in values.items():
            if runtime is None:
                continue
            try:
                if name == "intentions":
                    result["intention_cues"] = len(
                        runtime.loom.pending_cues())
                    project_loom = getattr(runtime, "project_loom", None)
                    if project_loom is not None:
                        result["project_proposals"] = int(
                            project_loom.status().get("proposal_count") or 0)
                elif name == "writing":
                    result["writing_seeds"] = len(
                        runtime.desk.pending_seeds())
                    result["writing_projects"] = len(
                        runtime.desk.projects_status())
                elif name == "research":
                    desk = runtime.desk.status()
                    result["research_opportunities"] = len(
                        desk.get("opportunities") or ())
                    result["research_interests"] = sum(
                        value.get("state") == "open"
                        for value in desk.get("interests") or ())
                    result["research_unread_sources"] = len(
                        desk.get("unread_sources") or ())
                    result["research_reports"] = len(
                        desk.get("reports") or ())
                elif name == "atelier":
                    result["atelier_seeds"] = len(
                        runtime.atelier.pending_seeds())
                    result["atelier_artifacts"] = len(
                        runtime.atelier.artifacts_status())
            except Exception:
                continue
        return result

    def _observe_projects(self, *, explicit=False) -> dict:
        counts = self._project_counts()
        total = sum(counts.values())
        rendered = ", ".join(f"{name} {count}" for name, count in
                             sorted(counts.items())) or "no project organs"
        return self.organ.observe(
            "projects", source_key="private-work-inventories",
            summary=(f"Current private work inventory counts: {rendered}. "
                     "Counts show availability, not obligation or desire."),
            facts={"counts": counts, "total": total},
            provenance={"source": "resident-owned organ ledgers"},
            dimensions={"novelty": .46, "locality": 1.0,
                        "consequence": min(1.0, total / 8.0),
                        "provenance": 1.0, "freshness": .96,
                        "chosen_interest": 1.0 if explicit else 0.0},
            explicit=explicit)

    def _observe_relational(self, *, explicit=False) -> dict:
        curiosity = getattr(self.engine, "outward_curiosity", None)
        counts = {}
        if curiosity is not None:
            try:
                counts = dict(curiosity.status().get("counts") or {})
            except Exception:
                counts = {}
        room = getattr(self.engine, "room", None)
        members = []
        if room is not None and room.room_id:
            try:
                members = sorted(dict(
                    room.snapshot().get("members") or {}).keys())
            except Exception:
                members = []
        summary = (
            f"Present room relationships include {', '.join(members) if members else 'no observed members'}. "
            f"Private relational question counts are {counts or {'open': 0}}; "
            "their words remain in their owning organ.")
        return self.organ.observe(
            "relational", source_key="presence-and-private-question-counts",
            summary=summary,
            facts={"present_members": members, "question_counts": counts},
            provenance={"source": "room presence + outward curiosity receipts"},
            dimensions={"novelty": .5, "locality": 1.0,
                        "consequence": .2, "provenance": 1.0,
                        "freshness": .92,
                        "chosen_interest": 1.0 if explicit else 0.0},
            explicit=explicit)

    def refresh(self, domains: Iterable[str] | None = None, *,
                explicit=False) -> list[dict]:
        if not self.organ.enabled and not explicit:
            return []
        wanted = ({str(value).casefold() for value in domains}
                  if domains is not None else
                  {"seasonal_light", "weather", "household", "resources",
                   "capabilities", "projects", "relational"})
        unknown = wanted - DOMAINS
        if unknown:
            raise ValueError(f"unknown awareness domain(s): {sorted(unknown)}")
        observations = []
        methods = {
            "seasonal_light": self._observe_seasonal_light,
            "weather": self._observe_weather,
            "household": self._observe_household,
            "resources": self._observe_resources,
            "capabilities": self._observe_capabilities,
            "projects": self._observe_projects,
            "relational": self._observe_relational,
        }
        for domain in sorted(wanted):
            method = methods.get(domain)
            if method is None:
                continue
            try:
                result = method(explicit=explicit)
            except Exception:
                continue
            if result and result.get("changed"):
                observations.append(result)
        with self._condition:
            self._condition.notify_all()
        return observations

    def context(self) -> tuple[str, dict]:
        if "world_awareness" not in getattr(self.engine, "enabled", set()):
            return "", {"schema_version": 1, "status": "disabled",
                        "rendered": False, "content_free": True}
        self.refresh()
        return self.organ.claim_context()

    def observe_domain(self, domain: str, *, focus: str = "") -> dict:
        domain = str(domain or "").casefold().strip()
        if domain not in DOMAINS:
            raise ValueError(
                "observe_world domain must be one of " +
                ", ".join(sorted(DOMAINS)))
        focus = " ".join(str(focus or "").split())[:240]
        if domain in EXTERNAL_RESEARCH_DOMAINS:
            location = self.location()
            if not location["configured"] or not location["label"]:
                raise ValueError(
                    "local world research needs a consented area in Weather sync")
            if self.research is None:
                raise ValueError("Research Desk is unavailable")
            label = location["label"]
            stems = {
                "local_news": f"current local news in {label}",
                "civic": (f"current public notices civic decisions transit "
                          f"closures and community events in {label}"),
                "cultural": (f"current arts culture library music exhibitions "
                             f"and public events in {label}"),
            }
            query = stems[domain] + (" " + focus if focus else "")
            result = self.research.admit_foreground_query(
                self.engine.idle_metabolism, query,
                why=f"resident-chosen {domain} observation for consented area")
            return {
                "ok": True, "domain": domain,
                "route": "private_research_desk",
                "result_count": int(result.get("result_count") or 0),
                "candidate_key": str(
                    dict(result.get("candidate") or {}).get("key") or ""),
                "location_precision": location.get("precision"),
                "coordinates_exposed": False,
                "interest_presumed": False,
                "speech_required": False,
            }
        observations = self.refresh((domain,), explicit=True)
        text, receipt = self.organ.open_domain(domain)
        if text:
            self.engine.queue_local_world_context(text)
        return {
            **receipt,
            "observation_changed": bool(observations),
            "speech_required": False,
            "automatic_memory": False,
        }

    def release(self, episode_id: str) -> dict:
        return self.organ.release(episode_id)

    def snapshot(self) -> dict:
        value = self.organ.snapshot()
        value["location"] = self.location()
        value["runtime"] = {
            "canonical_sources": [
                "host civil clock", "Open-Meteo weather status",
                "host-authoritative room", "local runtime receipts",
                "resident-owned project ledgers", "bounded Research Desk",
            ],
            "arbitrary_polling": False,
            "external_domains_require_resident_action": sorted(
                EXTERNAL_RESEARCH_DOMAINS),
        }
        return value

    def run(self, stop, emit):
        """Establish a baseline, then sleep until a civil calendar boundary.

        Weather wakes residents through the room host's semantic weather
        revision event. Other domains are refreshed by their own room/turn/
        organ events. The midnight predictor exists only for the date/season
        relationship; it is not an arbitrary scan cadence.
        """
        baseline = self.refresh(("capabilities", "seasonal_light", "weather"))
        for result in baseline:
            if result.get("crossed"):
                emit(result["episode"])
        while not stop.is_set():
            with self._condition:
                if self._closed:
                    return
                now = dt.datetime.fromtimestamp(self.now_fn()).astimezone()
                tomorrow = (now + dt.timedelta(days=1)).date()
                boundary = dt.datetime.combine(
                    tomorrow, dt.time.min, tzinfo=now.tzinfo).timestamp()
                delay = max(0.001, boundary - self.now_fn())
                self._condition.wait(timeout=min(delay, threading.TIMEOUT_MAX))
                if self._closed or stop.is_set():
                    return
            results = self.refresh(("seasonal_light", "weather"))
            for result in results:
                if result.get("crossed"):
                    emit(result["episode"])

"""Private, shadow-only scenario forecasts over exact Research Desk evidence.

The lab does not browse, schedule work, alter attention, or invent probability
priors.  It consumes immutable Research Desk snapshots, conservatively clusters
headline/article evidence, maps observed procedural stages, and composes an
exhaustive branch tree only when every conditional gate has an explicit prior.
Resolved forecasts feed a small calibration ledger instead of disappearing.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import time
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse
from xml.etree import ElementTree


SOURCE_ID_RE = re.compile(r"^web_[0-9a-f]{16}$")
FORECAST_ID_RE = re.compile(r"^forecast_[0-9a-f]{16}$")
BRANCH_ID_RE = re.compile(r"^branch_[0-9a-f]{16}$")

DEFAULT_GATES = (
    ("proposal", "proposal or public announcement"),
    ("advancement", "formal advancement or scheduling"),
    ("authorization", "authorization, passage, or adoption"),
    ("implementation", "operational implementation or enforcement"),
)

STAGE_PATTERNS = (
    (4, "implementation", re.compile(
        r"\b(takes? effect|went into effect|implemented|implementation|"
        r"enforced|enforcement began|deployed|operational|launched|rolled out|"
        r"began operating)\b", re.I)),
    (3, "authorization", re.compile(
        r"\b(signed into law|enacted|passed|approved|adopted|authorized|"
        r"awarded(?: the)? contract|final approval)\b", re.I)),
    (2, "advancement", re.compile(
        r"\b(advanced(?: by| from)? committee|cleared committee|scheduled|"
        r"on the agenda|public hearing|committee hearing|set for (?:a )?vote|"
        r"first reading|second reading|request for proposals?|\bRFP\b)\b", re.I)),
    (1, "proposal", re.compile(
        r"\b(introduced|filed|proposed|proposal|draft(?:ed)?|plans? to|"
        r"seeks? to|considering|called for|announced plans?)\b", re.I)),
)

BLOCKING_PATTERN = re.compile(
    r"\b(blocked|rejected|vetoed|withdrawn|stalled|dismissed|struck down|"
    r"delayed indefinitely|failed to advance|scrapped|abandoned)\b", re.I)

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|[\r\n]+")
WORD_RE = re.compile(r"[a-z0-9]+", re.I)
STOPWORDS = frozenset({
    "about", "after", "again", "against", "also", "among", "because",
    "before", "being", "between", "could", "from", "have", "into",
    "more", "news", "over", "says", "said", "that", "their", "there",
    "these", "they", "this", "through", "under", "what", "when", "where",
    "which", "while", "with", "would", "your",
})


def _digest(value: Any) -> str:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True,
                          default=str, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _bounded(value: Any, name: str, maximum: int, *, empty=False) -> str:
    text = " ".join(str(value or "").split())
    if not text and not empty:
        raise ValueError(f"{name} must not be empty")
    if len(text) > maximum:
        raise ValueError(f"{name} exceeds the {maximum}-character boundary")
    return text


def _local_name(tag: str) -> str:
    return str(tag or "").split("}")[-1].casefold()


def _child_text(node, names) -> str:
    wanted = {str(name).casefold() for name in names}
    for child in list(node):
        if _local_name(child.tag) in wanted:
            return " ".join("".join(child.itertext()).split())
    return ""


def _feed_items(snapshot: Mapping, maximum=200) -> list[dict]:
    """Expand an immutable RSS/Atom snapshot without fetching article URLs."""
    content_type = str(snapshot.get("content_type") or "").casefold()
    content = str(snapshot.get("content") or "")
    looks_xml = ("xml" in content_type or "rss" in content_type
                 or "atom" in content_type or content.lstrip().startswith("<"))
    if not looks_xml:
        return []
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError:
        return []
    nodes = [node for node in root.iter()
             if _local_name(node.tag) in {"item", "entry"}]
    items = []
    for node in nodes[:max(1, min(int(maximum), 500))]:
        title = _child_text(node, {"title"})
        summary = _child_text(node, {"summary", "description", "content"})
        published = _child_text(node, {"published", "updated", "pubdate"})
        link = _child_text(node, {"link", "guid"})
        if not link:
            for child in list(node):
                if _local_name(child.tag) == "link" and child.attrib.get("href"):
                    link = str(child.attrib["href"])
                    break
        if not title:
            continue
        items.append({
            "title": title[:500], "content": summary[:4000],
            "url": link[:2048], "published": published[:120],
            "source_id": snapshot.get("source_id"),
            "source_title": snapshot.get("title"),
            "source_url": snapshot.get("url"),
            "retrieved_at": snapshot.get("retrieved_at"),
        })
    return items


def _title_tokens(title: str) -> frozenset[str]:
    return frozenset(token for token in WORD_RE.findall(str(title).casefold())
                     if len(token) > 2 and token not in STOPWORDS)


def _similarity(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _source_family(url: str) -> str:
    host = (urlparse(str(url or "")).hostname or "unknown").casefold()
    return host[4:] if host.startswith("www.") else host


def _topic_match(text: str, terms) -> bool:
    folded = str(text or "").casefold()
    return not terms or any(term.casefold() in folded for term in terms)


def _extract_observations(item: Mapping, terms) -> list[dict]:
    title = _bounded(item.get("title") or "Untitled evidence", "evidence title",
                     500)
    body = str(item.get("content") or "")[:8000]
    candidates = [title]
    candidates.extend(sentence.strip() for sentence in SENTENCE_SPLIT_RE.split(body)
                      if sentence.strip())
    observations = []
    seen = set()
    prior_topic_context = False
    for sentence in candidates:
        sentence = " ".join(sentence.split())[:700]
        if not sentence:
            continue
        blocking = bool(BLOCKING_PATTERN.search(sentence))
        matches = [(rank, stage, pattern.search(sentence))
                   for rank, stage, pattern in STAGE_PATTERNS]
        matches = [(rank, stage, match) for rank, stage, match in matches if match]
        direct_topic = _topic_match(sentence, terms)
        contextual_stage = prior_topic_context and (blocking or bool(matches))
        prior_topic_context = direct_topic
        if not direct_topic and not contextual_stage:
            continue
        if matches:
            rank, stage, match = matches[0]
        elif blocking:
            rank, stage, match = 0, "blocked", BLOCKING_PATTERN.search(sentence)
        elif sentence == title:
            rank, stage, match = 0, "reported", None
        else:
            continue
        key = (item.get("source_id"), sentence.casefold(), stage, blocking)
        if key in seen:
            continue
        seen.add(key)
        observations.append({
            "observation_id": "obs_" + _digest(key)[:16],
            "source_id": item.get("source_id"),
            "citation": f"[{item.get('source_id')}]",
            "source_family": _source_family(
                item.get("source_url") or item.get("url")),
            "article_url": str(item.get("url") or "")[:2048],
            "title": title,
            "quote": sentence,
            "stage": stage,
            "stage_rank": rank,
            "direction": "blocks_progression" if blocking
                         else "supports_progression" if rank else "context",
            "matched_phrase": (match.group(0)[:160] if match else ""),
            "published": str(item.get("published") or "")[:120],
            "retrieved_at": item.get("retrieved_at"),
        })
    return observations[:40]


def _cluster_items(items: list[dict]) -> list[dict]:
    clusters: list[dict] = []
    for item in items:
        tokens = _title_tokens(item.get("title") or "")
        chosen = None
        for cluster in clusters:
            if _similarity(tokens, cluster["_tokens"]) >= .72:
                chosen = cluster
                break
        if chosen is None:
            chosen = {
                "cluster_id": "cluster_" + _digest({
                    "title": sorted(tokens),
                    "url": item.get("url") or item.get("source_url")})[:16],
                "title": item.get("title"), "items": [], "_tokens": tokens,
            }
            clusters.append(chosen)
        chosen["items"].append(item)
        if len(tokens) > len(chosen["_tokens"]):
            chosen["_tokens"] = tokens
    rendered = []
    for cluster in clusters:
        families = sorted({_source_family(
            item.get("source_url") or item.get("url"))
            for item in cluster["items"]})
        rendered.append({
            "cluster_id": cluster["cluster_id"], "title": cluster["title"],
            "item_count": len(cluster["items"]),
            "source_families": families,
            "source_ids": sorted({str(item.get("source_id"))
                                  for item in cluster["items"]}),
        })
    return rendered


def _normalize_gate(raw: Mapping, index: int) -> dict:
    value = dict(raw or {})
    gate_id = re.sub(r"[^a-z0-9_]+", "_", str(
        value.get("gate_id") or f"gate_{index + 1}").casefold()).strip("_")
    if not gate_id:
        raise ValueError("forecast gate id is invalid")
    label = _bounded(value.get("label") or gate_id.replace("_", " "),
                     "forecast gate label", 160)
    supplied = any(value.get(key) is not None
                   for key in ("probability", "probability_low", "probability_high"))
    if not supplied:
        return {"gate_id": gate_id, "label": label, "probability": None,
                "probability_low": None, "probability_high": None,
                "probability_basis": "not_estimated"}
    try:
        probability = float(value.get("probability"))
        low = float(value.get("probability_low")
                    if value.get("probability_low") is not None else probability)
        high = float(value.get("probability_high")
                     if value.get("probability_high") is not None else probability)
    except (TypeError, ValueError) as exc:
        raise ValueError("forecast gate probability is invalid") from exc
    if not 0.0 <= low <= probability <= high <= 1.0:
        raise ValueError("forecast gate probability range is invalid")
    basis = _bounded(value.get("probability_basis") or "supplied_prior",
                     "forecast probability basis", 240)
    return {"gate_id": gate_id, "label": label,
            "probability": probability, "probability_low": low,
            "probability_high": high, "probability_basis": basis}


def _branch_tree(gates: list[dict]) -> list[dict]:
    numeric = all(gate["probability"] is not None for gate in gates)
    if any(gate["probability"] is not None for gate in gates) and not numeric:
        raise ValueError("forecast probabilities must cover every gate or none")
    branches = []
    mid_prefix = low_prefix = high_prefix = 1.0
    for index, gate in enumerate(gates):
        label = (f"Does not reach {gate['label']}" if index == 0 else
                 f"Reaches prior gates but not {gate['label']}")
        branch = {"branch_id": "branch_" + _digest({
            "gate": gate["gate_id"], "outcome": "stops"})[:16],
                  "label": label, "terminal_gate": gate["gate_id"]}
        if numeric:
            p, low, high = (gate["probability"], gate["probability_low"],
                            gate["probability_high"])
            branch.update({
                "probability": mid_prefix * (1.0 - p),
                "probability_low": low_prefix * (1.0 - high),
                "probability_high": high_prefix * (1.0 - low),
            })
            mid_prefix *= p
            low_prefix *= low
            high_prefix *= high
        else:
            branch.update({"probability": None, "probability_low": None,
                           "probability_high": None})
        branches.append(branch)
    final = {"branch_id": "branch_" + _digest({
        "gates": [gate["gate_id"] for gate in gates],
        "outcome": "all_reached"})[:16],
             "label": "All modeled gates are reached", "terminal_gate": "complete"}
    if numeric:
        final.update({"probability": mid_prefix,
                      "probability_low": low_prefix,
                      "probability_high": high_prefix})
    else:
        final.update({"probability": None, "probability_low": None,
                      "probability_high": None})
    branches.append(final)
    return branches


class ScenarioForecastLab:
    """Append-only shadow forecast ledger rooted beneath one Research Desk."""

    def __init__(self, research_desk, *, now_fn=time.time):
        self.desk = research_desk
        self.root = Path(research_desk.root) / "scenario_lab"
        self.index = self.root / "index.jsonl"
        self.receipts = self.root / "receipts.jsonl"
        self.now_fn = now_fn
        self._lock = threading.RLock()

    def _append(self, path: Path, value: Mapping) -> dict:
        self.root.mkdir(parents=True, exist_ok=True)
        record = dict(value)
        with self._lock, path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False,
                                    sort_keys=True) + "\n")
        return record

    def records(self, kind=None, limit=1000) -> list[dict]:
        if not self.index.is_file():
            return []
        values = []
        with self._lock, self.index.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    value = json.loads(line)
                except ValueError:
                    continue
                if isinstance(value, dict) and (kind is None or value.get("kind") == kind):
                    values.append(value)
        return values[-max(1, min(int(limit), 5000)):]

    def _sources(self, source_ids) -> tuple[str, list[dict]]:
        ids = []
        for raw in source_ids or ():
            source_id = str(raw or "")
            if not SOURCE_ID_RE.fullmatch(source_id):
                raise ValueError("scenario evidence contains an invalid source id")
            if source_id not in ids:
                ids.append(source_id)
        if not 1 <= len(ids) <= 24:
            raise ValueError("scenario evidence requires one through 24 exact sources")
        interest_id = None
        snapshots = []
        for source_id in ids:
            source = self.desk.source(source_id)
            if interest_id is None:
                interest_id = source["interest_id"]
            elif source["interest_id"] != interest_id:
                raise ValueError("scenario evidence crossed research interest boundaries")
            snapshots.append(self.desk.inspect_source(source_id))
        return str(interest_id), snapshots

    def analyze_evidence(self, source_ids, topic_terms) -> dict:
        terms = []
        for raw in topic_terms or ():
            term = _bounded(raw, "scenario topic term", 80)
            if term.casefold() not in {value.casefold() for value in terms}:
                terms.append(term)
        if not 1 <= len(terms) <= 16:
            raise ValueError("scenario analysis requires one through 16 topic terms")
        interest_id, snapshots = self._sources(source_ids)
        items = []
        for snapshot in snapshots:
            expanded = _feed_items(snapshot)
            if expanded:
                items.extend(expanded)
            else:
                items.append({
                    "title": snapshot.get("title"),
                    "content": snapshot.get("content"),
                    "url": snapshot.get("url"),
                    "source_url": snapshot.get("url"),
                    "source_id": snapshot.get("source_id"),
                    "retrieved_at": snapshot.get("retrieved_at"),
                })
        relevant = [item for item in items if _topic_match(
            f"{item.get('title', '')} {item.get('content', '')}", terms)]
        clusters = _cluster_items(relevant)
        observations = []
        for item in relevant:
            observations.extend(_extract_observations(item, terms))
        families = sorted({observation["source_family"]
                           for observation in observations})
        stages = [observation["stage_rank"] for observation in observations]
        progression_clusters = set()
        blocking_clusters = set()
        item_cluster = {}
        for cluster in clusters:
            for source_id in cluster["source_ids"]:
                item_cluster.setdefault(source_id, set()).add(cluster["cluster_id"])
        for observation in observations:
            targets = item_cluster.get(observation["source_id"], set())
            if observation["direction"] == "blocks_progression":
                blocking_clusters.update(targets)
            elif observation["direction"] == "supports_progression":
                progression_clusters.update(targets)
        signals = {
            "snapshot_count": len(snapshots), "item_count": len(items),
            "relevant_item_count": len(relevant), "cluster_count": len(clusters),
            "independent_source_family_count": len(families),
            "source_families": families,
            "observed_stage_ceiling": max(stages) if stages else 0,
            "progression_cluster_count": len(progression_clusters),
            "blocking_cluster_count": len(blocking_clusters),
            "forecastability": ("uncalibrated_evidence_only" if len(families) >= 2
                                else "insufficient_independent_breadth"),
        }
        return {"interest_id": interest_id, "source_ids": [
            snapshot["source_id"] for snapshot in snapshots],
                "topic_terms": terms, "evidence_digest": _digest({
                    "sources": [(snapshot["source_id"], snapshot.get("content_sha256"))
                                for snapshot in snapshots], "terms": terms})[:16],
                "signals": signals, "clusters": clusters,
                "observations": observations}

    def record_intake(self, *, topic: str, corpus_lane: str, source_ids,
                      urls, failures=(), network_requests=0) -> dict:
        """Record a host-performed Research Desk snapshot batch, never content."""
        topic = _bounded(topic, "scenario intake topic", 240)
        corpus_lane = str(corpus_lane or "baseline").casefold()
        if corpus_lane not in {"baseline", "targeted_discovery"}:
            raise ValueError("scenario corpus lane is invalid")
        interest_id, snapshots = self._sources(source_ids)
        clean_urls = list(dict.fromkeys(_bounded(
            url, "scenario intake URL", 2048) for url in urls or ()))[:8]
        record = self._append(self.index, {
            "kind": "scenario_intake_recorded",
            "intake_id": "intake_" + _digest({
                "topic": topic, "lane": corpus_lane,
                "sources": [snapshot["source_id"] for snapshot in snapshots],
                "created_at": float(self.now_fn()),
            })[:16],
            "topic": topic, "corpus_lane": corpus_lane,
            "interest_id": interest_id,
            "source_ids": [snapshot["source_id"] for snapshot in snapshots],
            "urls": clean_urls,
            "failures": [str(value or "")[:300] for value in failures or ()][:8],
            "ownership": "persona_private_shadow", "shadow_only": True,
            "downstream_channels_touched": [], "created_at": float(self.now_fn()),
        })
        self._append(self.receipts, {
            "kind": "scenario_intake_snapshot", "intake_id": record["intake_id"],
            "source_set_digest": _digest(record["source_ids"])[:16],
            "corpus_lane": corpus_lane,
            "network_requests": max(0, int(network_requests)),
            "model_requests": 0, "downstream_channels_touched": [],
            "created_at": record["created_at"],
        })
        return record

    def _validate_corpus_lane(self, source_ids, corpus_lane: str):
        source_set = {str(source_id) for source_id in source_ids or ()}
        known = {record.get("corpus_lane") for record in self.records(
            "scenario_intake_recorded", limit=5000)
                 if source_set & set(record.get("source_ids") or ())}
        known.discard(None)
        if len(known) > 1:
            raise ValueError("forecast evidence mixed baseline and targeted corpora")
        if known and corpus_lane not in known:
            raise ValueError("forecast corpus lane disagrees with its intake record")

    def create_forecast(self, *, question: str, horizon_days: int,
                        source_ids, topic_terms, gates=(),
                        corpus_lane="baseline") -> dict:
        question = _bounded(question, "forecast question", 500)
        horizon_days = int(horizon_days)
        if not 1 <= horizon_days <= 3650:
            raise ValueError("forecast horizon must be one through 3650 days")
        corpus_lane = str(corpus_lane or "baseline").casefold()
        if corpus_lane not in {"baseline", "targeted_discovery"}:
            raise ValueError("forecast corpus lane is invalid")
        self._validate_corpus_lane(source_ids, corpus_lane)
        evidence = self.analyze_evidence(source_ids, topic_terms)
        raw_gates = list(gates or ())
        if not raw_gates:
            raw_gates = [{"gate_id": gate_id, "label": label}
                         for gate_id, label in DEFAULT_GATES]
        if not 1 <= len(raw_gates) <= 8:
            raise ValueError("forecast requires one through eight causal gates")
        normalized = [_normalize_gate(raw, index)
                      for index, raw in enumerate(raw_gates)]
        if len({gate["gate_id"] for gate in normalized}) != len(normalized):
            raise ValueError("forecast gate ids must be unique")
        ceiling = int(evidence["signals"]["observed_stage_ceiling"])
        blocking = evidence["signals"]["blocking_cluster_count"] > 0
        for index, gate in enumerate(normalized, start=1):
            gate["evidence_state"] = (
                "observed_with_blocking_evidence" if index <= ceiling and blocking
                else "observed" if index <= ceiling else "not_observed")
        branches = _branch_tree(normalized)
        created_at = float(self.now_fn())
        forecast_id = "forecast_" + _digest({
            "question": question, "horizon_days": horizon_days,
            "evidence": evidence["evidence_digest"], "corpus_lane": corpus_lane,
            "created_at": created_at})[:16]
        record = {
            "kind": "forecast_created", "forecast_id": forecast_id,
            "question": question, "horizon_days": horizon_days,
            "horizon_at": created_at + horizon_days * 86400.0,
            "interest_id": evidence["interest_id"],
            "corpus_lane": corpus_lane,
            "source_ids": evidence["source_ids"],
            "topic_terms": evidence["topic_terms"],
            "evidence_digest": evidence["evidence_digest"],
            "signals": evidence["signals"], "clusters": evidence["clusters"],
            "observations": evidence["observations"], "gates": normalized,
            "branches": branches,
            "probability_status": ("supplied_uncalibrated_priors" if all(
                gate["probability"] is not None for gate in normalized)
                else "not_estimated"),
            "ownership": "persona_private_shadow",
            "shadow_only": True, "downstream_channels_touched": [],
            "created_at": created_at,
        }
        self._append(self.receipts, {
            "kind": "forecast_shadow_created", "forecast_id": forecast_id,
            "source_set_digest": _digest(evidence["source_ids"])[:16],
            "evidence_digest": evidence["evidence_digest"],
            "probability_status": record["probability_status"],
            "network_requests": 0, "model_requests": 0,
            "downstream_channels_touched": [], "created_at": created_at,
        })
        return self._append(self.index, record)

    def forecast(self, forecast_id: str) -> dict:
        if not FORECAST_ID_RE.fullmatch(str(forecast_id or "")):
            raise ValueError("forecast id is invalid")
        value = next((record for record in reversed(self.records(
            "forecast_created", limit=5000))
                      if record.get("forecast_id") == forecast_id), None)
        if value is None:
            raise ValueError("forecast does not exist")
        resolution = next((record for record in reversed(self.records(
            "forecast_resolved", limit=5000))
                           if record.get("forecast_id") == forecast_id), None)
        return {**value, "resolution": resolution}

    def resolve(self, forecast_id: str, *, branch_id: str,
                source_ids, note="") -> dict:
        forecast = self.forecast(forecast_id)
        if forecast.get("resolution"):
            return {**forecast["resolution"], "duplicate": True}
        if not BRANCH_ID_RE.fullmatch(str(branch_id or "")):
            raise ValueError("forecast branch id is invalid")
        if branch_id not in {branch["branch_id"] for branch in forecast["branches"]}:
            raise ValueError("forecast branch does not belong to the forecast")
        interest_id, snapshots = self._sources(source_ids)
        if interest_id != forecast["interest_id"]:
            raise ValueError("forecast resolution crossed its research interest")
        note = _bounded(note, "forecast resolution note", 1000, empty=True)
        resolved_at = float(self.now_fn())
        record = self._append(self.index, {
            "kind": "forecast_resolved", "forecast_id": forecast_id,
            "branch_id": branch_id, "resolution_source_ids": [
                snapshot["source_id"] for snapshot in snapshots],
            "resolution_evidence_digest": _digest([
                (snapshot["source_id"], snapshot.get("content_sha256"))
                for snapshot in snapshots])[:16],
            "note": note, "ownership": "persona_private_shadow",
            "shadow_only": True, "downstream_channels_touched": [],
            "resolved_at": resolved_at,
        })
        self._append(self.receipts, {
            "kind": "forecast_shadow_resolved", "forecast_id": forecast_id,
            "branch_id": branch_id, "network_requests": 0,
            "model_requests": 0, "downstream_channels_touched": [],
            "created_at": resolved_at,
        })
        return {**record, "duplicate": False}

    def calibration(self) -> dict:
        forecasts = {record["forecast_id"]: record for record in self.records(
            "forecast_created", limit=5000)}
        resolutions = {record["forecast_id"]: record for record in self.records(
            "forecast_resolved", limit=5000)}
        scored = []
        bins = {index: {"predicted": [], "observed": []} for index in range(5)}
        for forecast_id, resolution in resolutions.items():
            forecast = forecasts.get(forecast_id)
            if not forecast or any(branch.get("probability") is None
                                   for branch in forecast.get("branches") or ()):
                continue
            actual = resolution["branch_id"]
            probabilities = {branch["branch_id"]: float(branch["probability"])
                             for branch in forecast["branches"]}
            brier = sum((probability - (1.0 if branch_id == actual else 0.0)) ** 2
                        for branch_id, probability in probabilities.items())
            actual_probability = max(probabilities.get(actual, 0.0), 1e-12)
            scored.append({"forecast_id": forecast_id, "brier": brier,
                           "log_loss": -math.log(actual_probability)})
            for branch_id, probability in probabilities.items():
                bin_index = min(4, int(probability * 5))
                bins[bin_index]["predicted"].append(probability)
                bins[bin_index]["observed"].append(
                    1.0 if branch_id == actual else 0.0)
        bands = []
        for index, values in bins.items():
            if not values["predicted"]:
                continue
            bands.append({
                "range_low": index / 5.0, "range_high": (index + 1) / 5.0,
                "count": len(values["predicted"]),
                "mean_predicted": sum(values["predicted"]) / len(values["predicted"]),
                "observed_frequency": sum(values["observed"]) / len(values["observed"]),
            })
        return {
            "resolved_forecast_count": len(resolutions),
            "scored_forecast_count": len(scored),
            "mean_brier": (sum(value["brier"] for value in scored) / len(scored)
                           if scored else None),
            "mean_log_loss": (sum(value["log_loss"] for value in scored) / len(scored)
                              if scored else None),
            "calibration_bands": bands,
            "status": "calibrating" if scored else "no_scored_resolutions",
        }

    def status(self) -> dict:
        forecasts = [self.forecast(record["forecast_id"])
                     for record in self.records("forecast_created", limit=200)]
        return {
            "root": "body/research_desk/scenario_lab",
            "shadow_only": True, "network_authority": False,
            "model_authority": False, "autonomy_influence": False,
            "memory_influence": False, "speech_influence": False,
            "forecast_count": len(forecasts), "forecasts": forecasts[-40:],
            "intakes": self.records("scenario_intake_recorded", limit=40),
            "calibration": self.calibration(),
            "policy": {
                "probabilities_without_explicit_priors": False,
                "automatic_prior_updates": False,
                "exact_research_desk_snapshots_required": True,
                "targeted_and_baseline_corpora_must_remain_distinct": True,
                "downstream_channels_touched": [],
            },
        }

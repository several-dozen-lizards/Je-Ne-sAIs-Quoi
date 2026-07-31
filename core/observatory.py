"""Read-only receipts and projections for the live salience field.

The organism never imports this module.  ``IdleMetabolism`` accepts a duck-
typed observer and emits facts at existing transitions; this observer owns the
append-only research log, non-mutating projections, and change notifications.
No observation method writes back into a candidate or changes field policy.
"""
from datetime import datetime, timezone
import hashlib
import io
import json
import os
import queue
import threading
import time
import math


def _stamp(now):
    return datetime.fromtimestamp(float(now), timezone.utc).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")


def _digest(text, limit=120):
    return " ".join(str(text or "").split())[:limit]


def _round(value):
    return round(float(value), 6)


def _private_ref(value):
    return "candidate_" + hashlib.sha256(
        str(value or "").encode("utf-8")).hexdigest()[:16]


class SalienceObserver:
    """Durable transition recorder with a genuinely read-only field view."""

    def __init__(self, persona: str, path: str, context_provider=None):
        self.persona = str(persona)
        self.path = path
        self.seq = 0
        self.revision = 0
        self.meta = {}
        self._snapshot_signature = None
        self._lock = threading.RLock()
        self._subscribers = set()
        self.context_provider = context_provider
        os.makedirs(os.path.dirname(path), exist_ok=True)

    def _responsiveness_context(self):
        """Read bounded numeric instruments; observer failure stays inert."""
        if not callable(self.context_provider):
            return {}
        try:
            value = self.context_provider()
            return dict(value or {}) if isinstance(value, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _competition(winner, beaten, selection=None):
        winner_total = max(0.0, float(winner.get("salience", 0.0)))
        alternatives = [max(0.0, float(item.get("salience", 0.0)))
                        for item in (beaten or [])]
        runner_up = max(alternatives, default=0.0)
        values = [winner_total, *alternatives]
        total = sum(values)
        shares = [value / total for value in values if value > 0.0] \
            if total > 0.0 else []
        entropy = -sum(share * math.log(share) for share in shares)
        normalized_entropy = (
            entropy / math.log(len(values))
            if len(values) > 1 and len(shares) > 1 else 0.0)
        sources = {
            str(item.get("source") or item.get("kind") or "unknown")
            for item in [winner, *(beaten or [])]}
        selected_score = dict(selection or {}).get("effective_salience")
        return {
            "candidate_count": len(values),
            "source_count": len(sources),
            "winner_salience": _round(winner_total),
            "runner_up_salience": _round(runner_up),
            "winner_margin": _round(winner_total - runner_up),
            "runner_up_ratio": _round(
                runner_up / winner_total if winner_total > 0.0 else 0.0),
            "salience_entropy": _round(normalized_entropy),
            "selected_effective_salience": (
                _round(selected_score) if selected_score is not None else None),
        }

    def _publish(self):
        self.revision += 1
        for subscriber in list(self._subscribers):
            try:
                subscriber.put_nowait(self.revision)
            except queue.Full:
                pass

    def _emit(self, record_type: str, now: float, **payload):
        """Append one record; instrumentation failure never enters the body."""
        try:
            with self._lock:
                self.seq += 1
                record = {"tick": _stamp(now), "persona": self.persona,
                          "type": record_type, "seq": self.seq, **payload}
                with open(self.path, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                self._publish()
                return record
        except Exception as exc:
            try:
                print("[salience-observatory] emission failed: "
                      + str(exc)[:240])
            except Exception:
                pass
            return None

    def subscribe(self):
        subscriber = queue.Queue(maxsize=1)
        with self._lock:
            self._subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber):
        with self._lock:
            self._subscribers.discard(subscriber)

    def _meta_for(self, key):
        return self.meta.get(str(key), {})

    def candidate(self, item: dict, salience=None, now=None):
        now = time.time() if now is None else float(now)
        item = dict(item or {})
        key = str(item.get("key") or "")
        total = float(item.get("salience", 0.0) if salience is None
                      else salience)
        meta = self._meta_for(key)
        components = dict(meta.get("salience_components") or {})
        component_total = sum(float(v) for v in components.values())
        if components and component_total > 0:
            scale = total / component_total
            components = {name: _round(float(value) * scale)
                          for name, value in components.items()}
        return {
            "key": key,
            "kind": item.get("kind"),
            "source": item.get("source"),
            "content_digest": _digest(item.get("node") or item.get("text")),
            "salience_total": _round(total),
            "salience_inputs": dict(meta.get("salience_inputs") or
                                    item.get("features") or {}),
            "salience_components": components,
            "born": item.get("born"),
            "updated": item.get("updated"),
            "age_s": _round(max(0.0, now - float(item.get("born", now)))),
            "ownership": meta.get("ownership"),
            "receipts": list(meta.get("receipts") or []),
        }

    def candidate_offered(self, item, offered_components, inputs, now,
                          raw_ref=None, ownership=None, receipts=None):
        key = str(item.get("key") or "")
        self.meta[key] = {
            "salience_components": dict(offered_components or {}),
            "salience_inputs": dict(inputs or {}),
            "ownership": ownership,
            "receipts": list(receipts or ([] if raw_ref is None else [raw_ref])),
        }
        return self._emit(
            "candidate_offered", now,
            candidate=self.candidate(item, now=now), raw_offering_ref=raw_ref)

    def candidates_merged(self, prior, survivor, offered_components, inputs,
                          now, raw_ref=None, ownership=None, receipts=None):
        key = str(survivor.get("key") or "")
        prior_total = float(prior.get("salience", 0.0))
        prior_meta = self._meta_for(key)
        prior_components = dict(prior_meta.get("salience_components") or {})
        if not prior_components:
            prior_components = {"existing_salience": prior_total}
        else:
            total = sum(prior_components.values()) or 1.0
            prior_components = {name: float(value) * prior_total / total
                                for name, value in prior_components.items()}
        residual = 1.0 - prior_total
        combined = dict(prior_components)
        for name, value in (offered_components or {}).items():
            combined[name] = combined.get(name, 0.0) + float(value) * residual
        old_receipts = list(prior_meta.get("receipts") or [])
        new_receipts = list(receipts or ([] if raw_ref is None else [raw_ref]))
        self.meta[key] = {
            "salience_components": combined,
            "salience_inputs": dict(inputs or {}),
            "ownership": ownership or prior_meta.get("ownership"),
            "receipts": list(dict.fromkeys(old_receipts + new_receipts)),
        }
        return self._emit(
            "candidates_merged", now, prior_keys=[key, key],
            surviving_key=key,
            prior_salience_breakdowns=[
                self.candidate(prior, now=now),
                {"salience_total": _round(sum(offered_components.values())),
                 "salience_components": {k: _round(v) for k, v in
                                          offered_components.items()}}],
            candidate=self.candidate(survivor, now=now),
            raw_offering_ref=raw_ref)

    def candidate_decayed(self, item, prior_value, new_value, now):
        key = str(item.get("key") or "")
        meta = self._meta_for(key)
        components = dict(meta.get("salience_components") or {})
        if components and prior_value > 0:
            scale = float(new_value) / float(prior_value)
            meta["salience_components"] = {
                name: float(value) * scale for name, value in components.items()}
        # Snapshot emission is deliberately batched by the caller.

    def candidate_expired(self, item, final_value, now):
        candidate = self.candidate(item, salience=final_value, now=now)
        record = self._emit("candidate_expired", now, candidate=candidate,
                            reason="cooled_out",
                            responsiveness={
                                "release_edge": "cooled_out",
                                "state": self._responsiveness_context()})
        self.meta.pop(str(item.get("key") or ""), None)
        return record

    def candidate_withdrawn(self, item, reason, now):
        record = self._emit(
            "candidate_withdrawn", now,
            candidate=self.candidate(item, now=now), reason=str(reason),
            responsiveness={
                "release_edge": "withdrawn",
                "state": self._responsiveness_context()})
        self.meta.pop(str(item.get("key") or ""), None)
        return record

    def candidate_won(self, winner, beaten, now, selection=None):
        return self._emit(
            "candidate_won", now,
            candidate=self.candidate(winner, now=now),
            beaten=[self.candidate(item, now=now) for item in beaten],
            selection=dict(selection or {}),
            responsiveness={
                "competition": self._competition(
                    winner, beaten, selection=selection),
                "state": self._responsiveness_context()})

    def field_effect(self, candidate_key, quantity, prior, new, now):
        return self._emit("field_effect", now,
                          candidate_key=str(candidate_key), quantity=quantity,
                          prior=_round(prior), new=_round(new))

    def candidate_requeued(self, item, reason, now):
        return self._emit("candidate_requeued", now,
                          candidate=self.candidate(item, now=now),
                          reason=str(reason),
                          responsiveness={
                              "release_edge": "requeued",
                              "state": self._responsiveness_context()})

    def discharge(self, item, outcome, response, prompt_receipt, now):
        response_text = str(response or "").strip()
        folded = response_text.casefold()
        quiet_exact = folded == "[quiet]"
        quiet_trailing = bool(response_text and not quiet_exact
                              and folded.endswith("[quiet]"))
        return self._emit(
            "discharge", now, candidate_key=str(item.get("key") or ""),
            outcome=str(outcome), model_response_digest=_digest(response, 200),
            quiet_exact=quiet_exact, quiet_trailing=quiet_trailing,
            prompt_receipt=prompt_receipt,
            responsiveness={
                "release_edge": "discharge",
                "state": self._responsiveness_context()})

    def play_counterfactual(self, projection, actual_winner_key, now):
        """Persist one already-computed content-free, unapplied comparison."""
        value = dict(projection or {})
        actual_ref = _private_ref(actual_winner_key)
        counterfactual_ref = value.get("counterfactual_winner_ref")
        eligible = int(value.get("eligible_count") or 0)
        original_margin = float(value.get("original_margin") or 0.0)
        counterfactual_margin = float(
            value.get("counterfactual_margin") or 0.0)
        return self._emit(
            "play_attention_counterfactual", now,
            schema=int(value.get("schema") or 1),
            owner=self.persona,
            ownership="persona_private",
            mode="shadow",
            applied=False,
            downstream_channels_touched=[],
            external_effects=False,
            eligibility=str(value.get("eligibility") or ""),
            candidate_count=int(value.get("candidate_count") or 0),
            eligible_count=eligible,
            play_event_count=int(value.get("play_event_count") or 0),
            attention_delta=_round(value.get("attention_delta") or 0.0),
            actual_winner_ref=actual_ref,
            original_winner_ref=value.get("original_winner_ref"),
            counterfactual_winner_ref=counterfactual_ref,
            changed_winner=bool(
                eligible > 0 and counterfactual_ref
                and counterfactual_ref != actual_ref),
            original_margin=_round(original_margin),
            counterfactual_margin=_round(counterfactual_margin),
            margin_delta=_round(counterfactual_margin - original_margin),
            candidates=list(value.get("candidates") or [])[:48])

    def admission_boundary(self, evidence, score, boundary, policy,
                           oscillator, outcome, now, event_id=None):
        return self._emit(
            "admission_boundary", now, event_id=event_id,
            evidence=dict(evidence or {}), score=_round(score),
            boundary=_round(boundary), policy=dict(policy or {}),
            oscillator=dict(oscillator or {}), outcome=str(outcome))

    def agency_transition(self, kind, now=None, **payload):
        """Record one bounded agency lifecycle edge without changing state."""
        kind = str(kind or "").strip()
        if not kind.startswith("agency_"):
            raise ValueError(
                "agency transition kind must begin with 'agency_'")
        now = time.time() if now is None else float(now)
        return self._emit(kind, now, **dict(payload or {}))

    def autonomy_transition(self, kind, now=None, **payload):
        """Record an organ transition without granting it field authority."""
        kind = str(kind or "").strip()
        allowed = (
            "intention_loom_", "writing_desk_", "archive_reader_",
            "document_reader_", "research_desk_", "atelier_",
        )
        if not kind.startswith(allowed):
            raise ValueError("autonomy transition kind has an unknown organ prefix")
        now = time.time() if now is None else float(now)
        return self._emit(kind, now, **dict(payload or {}))

    def project_field(self, field, now=None):
        """Compute effective values from the heap without calling decay()."""
        now = time.time() if now is None else float(now)
        candidates = []
        for _negative, _sequence, item in list(field.queue._heap):
            effective = field.queue._effective(item, now)
            candidates.append(self.candidate(item, effective, now))
        candidates.sort(key=lambda item: -item["salience_total"])
        pressure = field.pressure.to_dict()
        if pressure.get("active_node"):
            pressure["active_node"] = _digest(pressure["active_node"])
        satiety = {
            key: _round(field.satiety.warmth(key, now))
            for key in field.satiety.nodes
            if field.satiety.warmth(key, now) >= 0.05
        }
        return {"persona": self.persona, "observed_at": _stamp(now),
                "candidates": candidates, "field_pressure": pressure,
                "source_satiety": satiety}

    def field_snapshot(self, field, now):
        view = self.project_field(field, now)
        signature_view = json.loads(json.dumps(
            {"candidates": view["candidates"],
             "field_pressure": view["field_pressure"],
             "source_satiety": view["source_satiety"]}, default=str))
        # Age is a projection, not a state transition; it cannot create logs.
        for candidate in signature_view["candidates"]:
            candidate.pop("age_s", None)
        signature = hashlib.sha256(json.dumps(
            signature_view, sort_keys=True, ensure_ascii=False,
            default=str).encode("utf-8")).hexdigest()
        if signature == self._snapshot_signature:
            return None
        self._snapshot_signature = signature
        return self._emit("field_snapshot", now,
                          candidates=view["candidates"],
                          field_pressure=view["field_pressure"])

    def read_history(self, n=200, types=None):
        """Return newest records without replaying an ever-growing soak log."""
        wanted = {str(value) for value in (types or []) if str(value)}
        records = []
        try:
            with self._lock:
                for line in self._reverse_lines():
                    try:
                        record = json.loads(line)
                    except (TypeError, ValueError):
                        continue
                    if not wanted or record.get("type") in wanted:
                        records.append(record)
                        if len(records) >= max(1, int(n)):
                            break
        except FileNotFoundError:
            return []
        return records

    def _reverse_lines(self):
        """Yield complete UTF-8 JSONL records newest-first from disk."""
        with open(self.path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            position = handle.tell()
            carry = b""
            while position:
                size = min(io.DEFAULT_BUFFER_SIZE, position)
                position -= size
                handle.seek(position)
                block = handle.read(size) + carry
                lines = block.split(b"\n")
                carry = lines[0]
                for line in reversed(lines[1:]):
                    if line:
                        yield line.decode("utf-8")
            if carry:
                yield carry.decode("utf-8")

    @staticmethod
    def _mentions(value, key):
        if isinstance(value, dict):
            return any(SalienceObserver._mentions(item, key)
                       for item in value.values())
        if isinstance(value, list):
            return any(SalienceObserver._mentions(item, key) for item in value)
        return str(value) == str(key)

    def candidate_history(self, key):
        records = []
        try:
            with self._lock, open(self.path, encoding="utf-8") as handle:
                for line in handle:
                    try:
                        record = json.loads(line)
                    except (TypeError, ValueError):
                        continue
                    if self._mentions(record, key):
                        records.append(record)
        except FileNotFoundError:
            pass
        return records

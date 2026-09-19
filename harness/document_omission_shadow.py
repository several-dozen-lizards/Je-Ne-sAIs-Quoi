"""Content-free document ancestry through the existing prompt gate.

This is a shadow observer. It does not change retrieval, budgets, rendering,
selection, recovery, or resident state, and it never stores raw source anchors.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib


def opaque_document_ref(anchor: str) -> str:
    """Stable local comparison key without retaining the source anchor."""
    value = str(anchor or "").strip()
    if not value:
        raise ValueError("document anchor is required")
    digest = hashlib.sha256(
        ("jnaiq.document.anchor.v1\0" + value).encode("utf-8")).hexdigest()
    return "document:v1:" + digest


def build_document_evidence_trace(document_receipt, rendered_block,
                                  candidate_decision=None):
    """Return a sanitized trace plus raw rendered/all anchors for the caller.

    Raw anchors are returned separately for the existing canonical document
    reconciliation path. Only ``trace`` is safe for the prompt receipt.
    """
    receipt = dict(document_receipt or {})
    active = str(receipt.get("active_anchor") or "").strip()
    retrieved = [str(value or "").strip()
                 for value in (receipt.get("retrieved_anchors") or ())
                 if str(value or "").strip()]
    all_anchors = list(dict.fromkeys(([active] if active else []) + retrieved))
    candidate_complete = set(
        str(value or "").strip()
        for value in (receipt.get("candidate_complete_anchors") or ())
        if str(value or "").strip())
    rendered_text = str(rendered_block or "")
    rendered_complete = [
        anchor for anchor in all_anchors
        if anchor in candidate_complete and f"[[END {anchor}]]" in rendered_text]
    rendered_set = set(rendered_complete)
    retrieved_set = set(retrieved)
    anchors = []
    for anchor in all_anchors:
        if anchor in rendered_set:
            assembly_outcome = "rendered_complete"
        elif anchor in candidate_complete:
            assembly_outcome = "prompt_assembly_cut"
        else:
            assembly_outcome = "source_renderer_excerpt"
        anchors.append({
            "evidence_ref": opaque_document_ref(anchor),
            "eligibility": (
                "retrieved_by_turn_query" if anchor in retrieved_set
                else "active_reader_presence"),
            "assembly_outcome": assembly_outcome,
        })
    candidate = dict(candidate_decision or {})
    trace = {
        "schema": "jnaiq.document_prompt_evidence.v0",
        "source_kind": "human_owned_document_anchor",
        "block_name": "document_library",
        "candidate_ordinal": candidate.get("ordinal"),
        "block_outcome": candidate.get("outcome") or "not_assembled",
        "anchors": anchors,
        "counts": {
            "eligible": len(anchors),
            "rendered_complete": sum(
                item["assembly_outcome"] == "rendered_complete"
                for item in anchors),
            "source_renderer_excerpt": sum(
                item["assembly_outcome"] == "source_renderer_excerpt"
                for item in anchors),
            "prompt_assembly_cut": sum(
                item["assembly_outcome"] == "prompt_assembly_cut"
                for item in anchors),
        },
        "feedback_authorized": False,
    }
    # Preserve the contract's pre-existing sorted-set reconciliation order.
    return trace, sorted(set(rendered_complete)), sorted(set(all_anchors))


def analyze_document_recovery_demands(records):
    """Find later query retrievals matching earlier prompt-assembly cuts.

    A match is a recovery-demand candidate, not omission regret: no task
    failure or isolated-restoration evidence is present in PAC0 receipts.
    """
    prior_cuts = defaultdict(list)
    links = []
    eligible = rendered = excerpted = cut_count = 0
    for receipt_index, record in enumerate(records or ()):
        trace = dict(record.get("evidence_trace") or {})
        if trace.get("schema") != "jnaiq.document_prompt_evidence.v0":
            continue
        anchors = [item for item in (trace.get("anchors") or ())
                   if isinstance(item, dict) and item.get("evidence_ref")]
        eligible += len(anchors)
        rendered += sum(item.get("assembly_outcome") == "rendered_complete"
                        for item in anchors)
        excerpted += sum(
            item.get("assembly_outcome") == "source_renderer_excerpt"
            for item in anchors)
        cut_count += sum(item.get("assembly_outcome") == "prompt_assembly_cut"
                         for item in anchors)

        # Demand is evaluated before recording this receipt's cuts, so a cut
        # cannot satisfy itself within the same turn.
        for item in anchors:
            evidence_ref = str(item.get("evidence_ref") or "")
            if item.get("eligibility") != "retrieved_by_turn_query":
                continue
            if not prior_cuts[evidence_ref]:
                continue
            prior = prior_cuts[evidence_ref][-1]
            links.append({
                "schema": "jnaiq.document_recovery_demand.v0",
                "cut_cycle_id": prior["cycle_id"],
                "need_cycle_id": str(record.get("cycle_id") or ""),
                "receipt_distance": receipt_index - prior["receipt_index"],
                "demand_class": "later_query_retrieval",
                "attribution": "opaque_anchor_exact_match",
                "omission_regret_established": False,
                "feedback_authorized": False,
            })
        for item in anchors:
            if item.get("assembly_outcome") != "prompt_assembly_cut":
                continue
            evidence_ref = str(item["evidence_ref"])
            prior_cuts[evidence_ref].append({
                "cycle_id": str(record.get("cycle_id") or ""),
                "receipt_index": receipt_index,
            })

    return {
        "schema": "jnaiq.document_recovery_demand_summary.v0",
        "eligible_anchor_events": eligible,
        "rendered_complete_events": rendered,
        "source_renderer_excerpt_events": excerpted,
        "prompt_assembly_cut_events": cut_count,
        "recovery_demand_candidates": len(links),
        "recent": list(reversed(links[-80:])),
        "claim_boundary": (
            "exact ancestry plus later query retrieval only; task failure, "
            "repair, and omission regret are not established"),
        "feedback_authorized": False,
    }

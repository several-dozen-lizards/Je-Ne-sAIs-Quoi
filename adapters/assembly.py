"""PromptAssembly — the neutral IR between persona interior and model adapters.
The interior produces assemblies; adapters translate them per model spec.
The interior NEVER knows what model it's running on. That's the contract.

Budget law (the [PROMPT BLOCKS] lesson, encoded):
- A block over its own budget is truncated AT the budget, with a visible marker.
- If the total exceeds the model's practical window, VOLATILE blocks drop first,
  lowest priority first, and every drop is recorded in assembly.report.
- Nothing is ever silently truncated. The report is part of the output.
"""
import hashlib
import json
from dataclasses import dataclass, field


def est_tokens(text: str) -> int:
    """v0 estimator: ~4 chars/token. Replace with real tokenizer later."""
    return max(1, len(text) // 4)


def _digest(value) -> str:
    """Content-free identity for comparison without retaining prompt text."""
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass
class Block:
    name: str
    content: str
    priority: int = 5          # 1 = drop first, 10 = never drop
    budget: int = 0            # 0 = no per-block cap
    stable: bool = False       # stable -> cache-friendly position (API models)
    keep_tail: bool = False    # chronological blocks retain the newest edge
    authority: str = "system" # system law or fenced user-role source data

    def tokens(self) -> int:
        return est_tokens(self.content)


@dataclass
class PromptAssembly:
    blocks: list = field(default_factory=list)     # list[Block]
    messages: list = field(default_factory=list)   # [{"role","content"}...]
    report: list = field(default_factory=list)     # human-readable budget actions
    # Content-free provenance for supplemental attention allocation.  Adapters
    # do not consume this; the completed-turn observer reconciles it against
    # the post-budget candidate outcomes.
    attention_budget_trace: dict = field(default_factory=dict, repr=False)
    decision_receipt: dict = field(default_factory=dict, repr=False)
    _receipt_ordinals: dict = field(default_factory=dict, repr=False)

    def add(self, name, content, priority=5, budget=0, stable=False,
            keep_tail=False, authority="system"):
        if authority not in {"system", "user_data"}:
            raise ValueError(
                "prompt block authority must be system or user_data")
        self.blocks.append(Block(
            name, content, priority, budget, stable, keep_tail, authority))

    def apply_block_budgets(self, budgets):
        """Apply model-declared ceilings without widening organ budgets.

        The assembly owns relevance and current-state selection; the vessel
        spec owns how much of each selected block it can carry.  Reapplying
        the same ceilings is idempotent, which matters for continuation calls.
        """
        for block in self.blocks:
            declared = (budgets or {}).get(block.name)
            if declared is None:
                continue
            try:
                declared = int(declared)
            except (TypeError, ValueError):
                raise ValueError(
                    f"block budget for {block.name} must be an integer")
            if declared <= 0:
                raise ValueError(
                    f"block budget for {block.name} must be positive")
            block.budget = (
                min(block.budget, declared) if block.budget else declared)
        return self

    def enforce_budgets(self, practical_window: int, reply_reserve: int = 800,
                        requested_completion_tokens=None):
        """Apply per-block caps, then drop volatile low-priority blocks to fit."""
        report_start = len(self.report)
        candidates = []
        self._receipt_ordinals = {}
        for ordinal, block in enumerate(self.blocks):
            self._receipt_ordinals[id(block)] = ordinal
            candidates.append({
                "ordinal": ordinal,
                "name": block.name,
                "content_digest": _digest(block.content),
                "chars_before": len(block.content),
                "tokens_before": block.tokens(),
                "priority": block.priority,
                "stable": bool(block.stable),
                "authority": block.authority,
                "block_budget_tokens": block.budget,
                "keep_tail": bool(block.keep_tail),
                "transformations": [],
            })
        for b in self.blocks:
            if b.budget and b.tokens() > b.budget:
                keep_chars = b.budget * 4
                if b.keep_tail:
                    marker = (f"[...earlier content truncated at "
                              f"{b.budget} tok budget]\n")
                    remaining = max(0, keep_chars - len(marker))
                    b.content = marker + b.content[-remaining:]
                else:
                    b.content = (b.content[:keep_chars]
                                 + f"\n[...truncated at {b.budget} tok budget]")
                self.report.append(f"TRUNCATED block '{b.name}' to {b.budget} tok")
                candidates[self._receipt_ordinals[id(b)]][
                    "transformations"].append({
                        "action": "truncate",
                        "reason": "block_budget_exceeded",
                        "retained_edge": "tail" if b.keep_tail else "head",
                        "chars_after": len(b.content),
                        "tokens_after": b.tokens(),
                        "content_digest_after": _digest(b.content),
                    })

        def total():
            msgs = sum(est_tokens(m["content"]) for m in self.messages)
            return sum(b.tokens() for b in self.blocks) + msgs + reply_reserve

        droppable = sorted([b for b in self.blocks if not b.stable],
                           key=lambda b: b.priority)
        while total() > practical_window and droppable:
            victim = droppable.pop(0)
            self.blocks.remove(victim)
            self.report.append(
                f"DROPPED block '{victim.name}' (prio {victim.priority}, "
                f"{victim.tokens()} tok) to fit window {practical_window}")
        if total() > practical_window:
            self.report.append(
                f"WARNING: still over window after drops ({total()} > "
                f"{practical_window}); stable blocks exceed budget")
        surviving_by_ordinal = {
            self._receipt_ordinals[id(block)]: block for block in self.blocks}
        for candidate in candidates:
            block = surviving_by_ordinal.get(candidate["ordinal"])
            if block is None:
                candidate.update({
                    "outcome": "dropped",
                    "reason": "window_pressure_volatile_priority",
                    "chars_after": 0,
                    "tokens_after": 0,
                    "content_digest_after": None,
                })
            else:
                candidate.update({
                    "outcome": ("truncated" if candidate["transformations"]
                                else "retained"),
                    "reason": ("block_budget_exceeded"
                               if candidate["transformations"]
                               else "within_current_policy"),
                    "chars_after": len(block.content),
                    "tokens_after": block.tokens(),
                    "content_digest_after": _digest(block.content),
                })
        message_receipts = []
        for ordinal, message in enumerate(self.messages):
            content = message.get("content") or ""
            message_receipts.append({
                "ordinal": ordinal,
                "role": str(message.get("role") or ""),
                "content_digest": _digest(content),
                "chars": len(content),
                "tokens": est_tokens(content),
                "image_count": len(message.get("images") or ()),
            })
        self.decision_receipt = {
            "schema": "jnsq.prompt_assembly_decision.v0",
            "policy": {
                "name": "current_prompt_assembly",
                "revision": 0,
                "token_estimator": "floor_chars_div_4_min_1",
            },
            "envelope": {
                "practical_window_tokens": practical_window,
                "reply_reserve_tokens": reply_reserve,
                "requested_completion_tokens": requested_completion_tokens,
            },
            "candidates": candidates,
            "messages": message_receipts,
            "budget_actions": list(self.report[report_start:]),
            "estimated_total_tokens_after": total(),
            "serialization": None,
            "submission": {
                "attempted": False,
                "accepted": False,
                "provider_input_tokens": None,
                "finish_reason": None,
                "usage_evidence": "unavailable",
                "evidence_class": "assembly_only",
            },
        }
        return self

    def record_serialization(self, *, adapter_family: str, ordered_blocks,
                             system_payload, user: str, images=(),
                             user_data_blocks=()):
        """Attach exact-shape metadata without retaining rendered content."""
        if not self.decision_receipt:
            return
        self.decision_receipt["serialization"] = {
            "adapter_family": adapter_family,
            "block_ordinals": [self._receipt_ordinals[id(block)]
                               for block in ordered_blocks],
            "user_data_block_ordinals": [
                self._receipt_ordinals[id(block)]
                for block in user_data_blocks],
            "system_digest": _digest(system_payload),
            "system_chars": (len(system_payload)
                             if isinstance(system_payload, str)
                             else len(json.dumps(system_payload,
                                                 ensure_ascii=False,
                                                 sort_keys=True,
                                                 separators=(",", ":")))),
            "user_digest": _digest(user),
            "user_chars": len(user),
            "image_count": len(images or ()),
        }

    def mark_submission(self, *, attempted=True, accepted=False,
                        provider="", model="", requested_num_ctx=None,
                        error_type=None, provider_input_tokens=None,
                        finish_reason=None, usage_evidence=None):
        """Record transport reachability; never provider prompt contents."""
        if not self.decision_receipt:
            return
        submission = self.decision_receipt["submission"]
        submission.update({
            "attempted": bool(attempted),
            "accepted": bool(accepted),
            "provider": provider,
            "model": model,
            "requested_num_ctx": requested_num_ctx,
            "evidence_class": ("provider_returned" if accepted
                               else "submission_attempted" if attempted
                               else "assembly_only"),
        })
        submission["provider_input_tokens"] = provider_input_tokens
        submission["finish_reason"] = finish_reason
        submission["usage_evidence"] = (
            usage_evidence if provider_input_tokens is not None
            else "unavailable")
        if error_type:
            submission["error_type"] = error_type

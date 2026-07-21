"""PromptAssembly — the neutral IR between persona interior and model adapters.
The interior produces assemblies; adapters translate them per model spec.
The interior NEVER knows what model it's running on. That's the contract.

Budget law (the [PROMPT BLOCKS] lesson, encoded):
- A block over its own budget is truncated AT the budget, with a visible marker.
- If the total exceeds the model's practical window, VOLATILE blocks drop first,
  lowest priority first, and every drop is recorded in assembly.report.
- Nothing is ever silently truncated. The report is part of the output.
"""
from dataclasses import dataclass, field


def est_tokens(text: str) -> int:
    """v0 estimator: ~4 chars/token. Replace with real tokenizer later."""
    return max(1, len(text) // 4)


@dataclass
class Block:
    name: str
    content: str
    priority: int = 5          # 1 = drop first, 10 = never drop
    budget: int = 0            # 0 = no per-block cap
    stable: bool = False       # stable -> cache-friendly position (API models)
    keep_tail: bool = False    # chronological blocks retain the newest edge

    def tokens(self) -> int:
        return est_tokens(self.content)


@dataclass
class PromptAssembly:
    blocks: list = field(default_factory=list)     # list[Block]
    messages: list = field(default_factory=list)   # [{"role","content"}...]
    report: list = field(default_factory=list)     # human-readable budget actions

    def add(self, name, content, priority=5, budget=0, stable=False,
            keep_tail=False):
        self.blocks.append(Block(
            name, content, priority, budget, stable, keep_tail))

    def enforce_budgets(self, practical_window: int, reply_reserve: int = 800):
        """Apply per-block caps, then drop volatile low-priority blocks to fit."""
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
        return self

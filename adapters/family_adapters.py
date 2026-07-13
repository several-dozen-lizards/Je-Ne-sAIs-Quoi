"""Family adapters: PromptAssembly + model spec -> native model call.
One adapter per FAMILY (spec identity.family selects it). Adding a new model
of an existing family requires zero adapter code — just a spec file."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from adapters.assembly import PromptAssembly
from harness.clients import OllamaClient, AnthropicClient, OpenAICompatClient


class AnthropicAdapter:
    """anthropic family. Stable blocks first in the system param
    (cache-friendly per spec notes), volatile blocks after. Strict
    user/assistant alternation honored in messages."""
    family = "anthropic"

    def __init__(self, spec: dict):
        self.spec = spec
        self.client = AnthropicClient(spec)

    def render_system(self, asm: PromptAssembly) -> str:
        stable = [b for b in asm.blocks if b.stable]
        volatile = [b for b in asm.blocks if not b.stable]
        parts = [f"[{b.name.upper()}]\n{b.content}" for b in stable + volatile]
        return "\n\n".join(parts)

    def call(self, asm: PromptAssembly, max_tokens=400, temperature=0.7) -> str:
        window = self.spec["context"]["practical_window_tokens"]
        asm.enforce_budgets(window)
        system = self.render_system(asm)
        # v0: single-turn transport via harness client; multi-turn in v0.2
        user = asm.messages[-1]["content"] if asm.messages else ""
        return self.client.chat(system, user, max_tokens=max_tokens,
                                temperature=temperature)


class ChatMLAdapter:
    """llama3-chatml family (Ollama transport). Everything rides the system
    message within the small window; budget enforcement does real work here."""
    family = "llama3-chatml"

    def __init__(self, spec: dict):
        self.spec = spec
        self.client = OllamaClient(spec)

    def render_system(self, asm: PromptAssembly) -> str:
        # Order by priority (high first) so the most identity-critical
        # content sits earliest for the small model's attention.
        ordered = sorted(asm.blocks, key=lambda b: -b.priority)
        parts = [f"[{b.name.upper()}]\n{b.content}" for b in ordered]
        return "\n\n".join(parts)

    def call(self, asm: PromptAssembly, max_tokens=400, temperature=0.7) -> str:
        window = self.spec["context"]["practical_window_tokens"]
        asm.enforce_budgets(window)
        system = self.render_system(asm)
        user = asm.messages[-1]["content"] if asm.messages else ""
        return self.client.chat(system, user, max_tokens=max_tokens,
                                temperature=temperature)


class OpenAICompatAdapter:
    """openai_chat family (transport: OpenAICompatClient). One render
    shape, many doors — OpenAI proper, OpenRouter, Groq, Together,
    DeepSeek, xAI, plus local LM Studio / llama.cpp / vLLM. Renders the
    same way the chatml adapter does (07-05 work order: 'system blocks
    -> system message; asm.messages appended'): priority-ordered blocks
    collapse into the system string, the client ships them as a
    system-role message alongside the latest user turn.

    Family vs provider stays the existing convention: FAMILY names the
    render shape (openai_chat); PROVIDER names the wire (spec's
    identity.provider == 'openai_compat', which client_for dispatches on
    in the harness). base_url / api_key_env live on the spec; the KEY
    LAW is the client's job (unset env -> no auth header).

    NOTE (future knob, not needed for acceptance): hosted models with
    prompt caching prefer stable-first ordering to keep the prefix
    cacheable; chatml's priority-sort is neutral-to-slightly-worse
    there. Left chatml-identical per the work order; revisit if we start
    paying for uncached prefixes."""
    family = "openai_chat"

    def __init__(self, spec: dict):
        self.spec = spec
        self.client = OpenAICompatClient(spec)

    def render_system(self, asm: PromptAssembly) -> str:
        # priority-ordered, identical to ChatMLAdapter — highest-priority
        # identity content earliest in the system message.
        ordered = sorted(asm.blocks, key=lambda b: -b.priority)
        parts = [f"[{b.name.upper()}]\n{b.content}" for b in ordered]
        return "\n\n".join(parts)

    def call(self, asm: PromptAssembly, max_tokens=400, temperature=0.7) -> str:
        window = self.spec["context"]["practical_window_tokens"]
        asm.enforce_budgets(window)
        system = self.render_system(asm)
        user = asm.messages[-1]["content"] if asm.messages else ""
        return self.client.chat(system, user, max_tokens=max_tokens,
                                temperature=temperature)


_FAMILIES = {a.family: a for a in (AnthropicAdapter, ChatMLAdapter,
                                   OpenAICompatAdapter)}


def adapter_for(spec: dict):
    fam = spec["identity"]["family"]
    if fam not in _FAMILIES:
        raise ValueError(f"No adapter for family '{fam}'")
    return _FAMILIES[fam](spec)

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class LLMProvider(Protocol):
    """Open-source friendly LLM provider contract for future local, HF, Ollama, vLLM or llama.cpp backends."""

    name: str

    def generate(self, system_prompt: str, developer_prompt: str, context_prompt: str, user_prompt: str) -> str:
        """Generate a response from explicit prompts and retrieved context."""
        ...


@dataclass
class EvidenceBoundFallbackProvider:
    """Deterministic provider used when no external or local LLM is configured."""

    name: str = "blum_evidence_bound_fallback"

    def generate(self, system_prompt: str, developer_prompt: str, context_prompt: str, user_prompt: str) -> str:
        return (
            "The response was composed by Blum's deterministic evidence-bound analyst layer. "
            "No external LLM was required for this answer."
        )


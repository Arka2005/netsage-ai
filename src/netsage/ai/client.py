"""LLMClient protocol and LLMResponse — the interface every backend implements.

Downstream code (the run pipeline) never branches on which backend produced a response — it
only ever sees an LLMResponse. See docs/ai_diagnosis_specification.md §2.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass
class LLMResponse:
    text: str
    backend: str
    model: str
    temperature: float
    latency_ms: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class LLMClient(Protocol):
    def complete(self, system: str, user: str, *, temperature: float = 0.0) -> LLMResponse: ...

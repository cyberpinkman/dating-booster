from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from dating_boost.core.memory.models import MemoryFact


@dataclass(frozen=True)
class SemanticHookCandidate:
    fact_id: str
    text: str
    score: float


class SemanticHookProvider(Protocol):
    def retrieve_hooks(
        self,
        query: str,
        facts: Sequence[MemoryFact],
        limit: int,
    ) -> list[SemanticHookCandidate]:
        ...


class NoOpSemanticHookProvider:
    def retrieve_hooks(
        self,
        query: str,
        facts: Sequence[MemoryFact],
        limit: int,
    ) -> list[SemanticHookCandidate]:
        return []

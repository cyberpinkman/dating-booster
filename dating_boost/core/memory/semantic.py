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


class LocalLexicalSemanticHookProvider:
    def retrieve_hooks(
        self,
        query: str,
        facts: Sequence[MemoryFact],
        limit: int,
    ) -> list[SemanticHookCandidate]:
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []
        scored: list[tuple[float, str, str]] = []
        for fact in facts:
            text = str(fact.value).strip()
            if not text:
                continue
            text_lower = text.casefold()
            match_count = sum(1 for token in query_tokens if token in text_lower)
            if match_count == 0:
                continue
            score = match_count / len(query_tokens)
            scored.append((score, fact.fact_id, text))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [
            SemanticHookCandidate(fact_id=fact_id, text=text, score=score)
            for score, fact_id, text in scored[:limit]
        ]


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    current: list[str] = []
    cjk_buffer: list[str] = []
    for char in text.casefold():
        if _is_cjk(char):
            if current:
                tokens.append("".join(current))
                current = []
            cjk_buffer.append(char)
        elif char.isalnum():
            if cjk_buffer:
                tokens.extend(_cjk_ngrams(cjk_buffer))
                cjk_buffer = []
            current.append(char)
        else:
            if current:
                tokens.append("".join(current))
                current = []
            if cjk_buffer:
                tokens.extend(_cjk_ngrams(cjk_buffer))
                cjk_buffer = []
    if current:
        tokens.append("".join(current))
    if cjk_buffer:
        tokens.extend(_cjk_ngrams(cjk_buffer))
    return [token for token in tokens if len(token) >= 2]


def _is_cjk(char: str) -> bool:
    cp = ord(char)
    return (
        (0x4E00 <= cp <= 0x9FFF)
        or (0x3400 <= cp <= 0x4DBF)
        or (0x2E80 <= cp <= 0x2EFF)
        or (0x3000 <= cp <= 0x303F)
        or (0xF900 <= cp <= 0xFAFF)
        or (0x2F800 <= cp <= 0x2FA1F)
    )


def _cjk_ngrams(chars: list[str]) -> list[str]:
    if len(chars) < 2:
        return chars
    result: list[str] = []
    for i in range(len(chars) - 1):
        result.append(chars[i] + chars[i + 1])
    if len(chars) >= 3:
        for i in range(len(chars) - 2):
            result.append(chars[i] + chars[i + 1] + chars[i + 2])
    return result

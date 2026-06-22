from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from dating_boost.core.draft_evidence import DraftEvidencePack


DRAFT_GENERATION_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class DraftGenerationPrompt:
    schema_version: int
    prompt_id: str
    evidence_id: str
    system_prompt: str
    user_prompt: str
    supplemental_prompts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "prompt_id": self.prompt_id,
            "evidence_id": self.evidence_id,
            "system_prompt": self.system_prompt,
            "user_prompt": self.user_prompt,
            "supplemental_prompts": list(self.supplemental_prompts),
        }

    def public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "prompt_id": self.prompt_id,
            "evidence_id": self.evidence_id,
            "supplemental_prompt_count": len(self.supplemental_prompts),
            "system_prompt_hash": _digest(self.system_prompt),
            "user_prompt_hash": _digest(self.user_prompt),
        }


def build_draft_generation_prompt(
    evidence_pack: DraftEvidencePack,
    *,
    supplemental_prompts: list[str] | None = None,
) -> DraftGenerationPrompt:
    supplements = [str(item) for item in (supplemental_prompts or []) if str(item).strip()]
    system_prompt = _system_prompt()
    user_prompt = "\n\n".join(
        [
            "reply_mode: " + evidence_pack.reply_mode,
            "draft_kind: " + evidence_pack.draft_kind,
            "SECTION 1 latest_inbound_turn\n" + _json_block(evidence_pack.latest_turn),
            "SECTION 2 complete_conversation_thread\n" + _json_block(evidence_pack.conversation_thread),
            "SECTION 3 relationship_strategy_current_stage\n" + _json_block(evidence_pack.planner_recommendation),
            "SECTION 4 match_memory\n" + _json_block(evidence_pack.match_memory),
            "SECTION 5 user_memory\n" + _json_block(evidence_pack.user_memory),
            "SECTION 6 human_naturalness_requirements\n" + _naturalness_requirements(),
            _supplemental_section(supplements),
        ]
    ).rstrip()
    prompt_id = f"draft_prompt_{_digest({'evidence_id': evidence_pack.evidence_id, 'user_prompt': user_prompt})[:16]}"
    return DraftGenerationPrompt(
        schema_version=DRAFT_GENERATION_SCHEMA_VERSION,
        prompt_id=prompt_id,
        evidence_id=evidence_pack.evidence_id,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        supplemental_prompts=supplements,
    )


def _system_prompt() -> str:
    return (
        "You generate dating-app reply drafts as strict structured JSON. "
        "Use the evidence sections in the exact priority order: latest inbound turn first, then complete thread, "
        "then relationship strategy/current stage, then match memory, then user memory. "
        "Do not invent hard facts. Do not ignore the latest inbound turn. "
        "Keep Chinese private-chat wording natural, brief, and strategically useful."
    )


def _naturalness_requirements() -> str:
    return "\n".join(
        [
            "- The reply must sound like a real person in Chinese private chat, not a report or assistant output.",
            "- Prefer one clear conversational move; question is optional and at most one short question.",
            "- If multiple bubbles are more natural, use message_sequence and make each bubble serve a distinct job.",
            "- Do not mechanically split punctuation, stack labels, repeat known facts as hooks, or ask the match to decide after they delegated choice.",
            "- Avoid abstract planning words, survey-style A/B interrogation, and stale current-state assumptions.",
            "- The final bubble must carry the conversational push or landing handle when message_sequence is used.",
            "- Unless the planner explicitly recommends wait, slow_down_wait, or handoff, include an answerable "
            "relationship handle: a specific unknown detail, a small user-side self-disclosure, or a next-milestone "
            "bridge. A pure acknowledgement such as 明白, 锁定, or 收到 is not enough for managed/staged drafts.",
        ]
    )


def _supplemental_section(supplements: list[str]) -> str:
    if not supplements:
        return "SUPPLEMENTAL_REVISION_PROMPTS\n[]"
    return "SUPPLEMENTAL_REVISION_PROMPTS\n" + _json_block(supplements)


def _json_block(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

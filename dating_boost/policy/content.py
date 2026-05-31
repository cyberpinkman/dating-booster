"""Content policy checks for generated reply drafts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any, Mapping

OVERSEAS_STUDY_CLAIMS = (
    "studied overseas",
    "study overseas",
    "studied abroad",
    "study abroad",
    "studied in london",
    "study in london",
    "went to university in london",
    "go to university in london",
    "went to college in london",
    "go to college in london",
    "university in london",
)


@dataclass(frozen=True)
class ContentPolicyDecision:
    allowed: bool
    severity: str
    reason: str
    requires_user_confirmation: bool = False


def evaluate_draft_content(draft: Any, context_pack: Mapping[str, Any]) -> ContentPolicyDecision:
    """Evaluate generated reply variants against MVP content safety rules."""

    soft_invite_violation = _soft_invite_detail_violation_reason(draft, context_pack)
    if soft_invite_violation:
        return ContentPolicyDecision(
            allowed=False,
            severity="high",
            reason=soft_invite_violation,
        )

    if _has_overseas_study_constraint(context_pack) and _draft_contains_overseas_study_claim(draft):
        return ContentPolicyDecision(
            allowed=False,
            severity="high",
            reason="Draft claims overseas study despite user hard facts or boundaries.",
        )

    hard_fact_violation = _hard_fact_contradiction_reason(draft, context_pack)
    if hard_fact_violation:
        return ContentPolicyDecision(
            allowed=False,
            severity="high",
            reason=hard_fact_violation,
        )

    if _requires_labeled_divergence_confirmation(draft):
        return ContentPolicyDecision(
            allowed=True,
            severity="medium",
            reason="Medium or high persona/stance divergence needs user confirmation when unlabeled.",
            requires_user_confirmation=True,
        )

    return ContentPolicyDecision(
        allowed=True,
        severity="low",
        reason="Draft content passed MVP policy checks.",
    )


def _soft_invite_detail_violation_reason(draft: Any, context_pack: Mapping[str, Any]) -> str | None:
    recommendation = _planner_recommendation(context_pack)
    if recommendation.get("recommended_move") != "soft_invite_probe":
        return None

    for text in _draft_texts(draft):
        if _contains_contact_exchange(text):
            return "Soft invite draft includes contact exchange details that require user handoff."
        if _contains_specific_appointment_time(text):
            return "Soft invite draft includes specific appointment timing that requires user handoff."
        if _contains_specific_meetup_place(text):
            return "Soft invite draft includes a specific meetup place that requires user handoff."
    return None


def _planner_recommendation(context_pack: Mapping[str, Any]) -> Mapping[str, Any]:
    direct = context_pack.get("planner_recommendation")
    if isinstance(direct, Mapping):
        return direct
    for item in context_pack.get("items", []):
        if isinstance(item, Mapping) and item.get("label") == "planner_recommendation":
            content = item.get("content")
            if isinstance(content, Mapping):
                return content
    return {}


def _contains_contact_exchange(text: str) -> bool:
    normalized = text.casefold()
    contact_terms = (
        "微信",
        "wechat",
        "wx",
        "vx",
        "手机号",
        "电话",
        "号码",
        "加我",
        "我加你",
        "留个",
    )
    return any(term in normalized for term in contact_terms)


def _contains_specific_appointment_time(text: str) -> bool:
    normalized = text.casefold()
    if re.search(r"\b\d{1,2}\s*[:：]\s*\d{2}\b", normalized):
        return True
    if re.search(r"\d{1,2}\s*[点點]\s*(?:半|[0-5]?\d\s*分?)?", normalized):
        return True
    date_markers = (
        "今天",
        "今晚",
        "明天",
        "明晚",
        "后天",
        "後天",
        "大后天",
        "大後天",
        "周一",
        "周二",
        "周三",
        "周四",
        "周五",
        "周六",
        "周日",
        "周天",
        "星期一",
        "星期二",
        "星期三",
        "星期四",
        "星期五",
        "星期六",
        "星期日",
        "星期天",
        "礼拜一",
        "礼拜二",
        "礼拜三",
        "礼拜四",
        "礼拜五",
        "礼拜六",
        "礼拜日",
        "礼拜天",
    )
    return any(marker in normalized for marker in date_markers)


def _contains_specific_meetup_place(text: str) -> bool:
    normalized = text.casefold()
    place_markers = ("三里屯", "国贸", "朝阳大悦城", "合生汇", "环球港", "五道口", "望京")
    if any(marker in normalized for marker in place_markers):
        return True
    return bool(re.search(r"(?:在|去)[^，。！？,.!?]{1,16}(?:见|碰|喝|吃|坐|逛)", normalized))


def _has_overseas_study_constraint(context_pack: Mapping[str, Any]) -> bool:
    for item in context_pack.get("items", []):
        if not isinstance(item, Mapping):
            continue
        label = item.get("label")
        content = item.get("content", "")
        text = _flatten_text(content).lower()
        if label == "user_boundaries" and _mentions_forbidden_overseas_study(text):
            return True
        if label == "user_hard_facts" and _mentions_local_chinese_education(text):
            return True
    return False


def _hard_fact_contradiction_reason(draft: Any, context_pack: Mapping[str, Any]) -> str | None:
    hard_facts = _hard_fact_content(context_pack)
    if _age_fact_contradicted(draft, hard_facts):
        return "Draft contradicts user age hard facts."
    if _location_fact_contradicted(draft, hard_facts):
        return "Draft contradicts user location hard facts."
    return None


def _hard_fact_content(context_pack: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    facts: list[Mapping[str, Any]] = []
    for item in context_pack.get("items", []):
        if not isinstance(item, Mapping) or item.get("label") != "user_hard_facts":
            continue
        content = item.get("content")
        if isinstance(content, Mapping):
            facts.append(content)
        elif isinstance(content, list):
            facts.extend(entry for entry in content if isinstance(entry, Mapping))
    return facts


def _age_fact_contradicted(draft: Any, hard_facts: list[Mapping[str, Any]]) -> bool:
    known_ages = {
        int(content["age"])
        for content in hard_facts
        if str(content.get("age", "")).isdigit()
    }
    if not known_ages:
        return False
    for text in _draft_texts(draft):
        for match in re.finditer(r"\b(?:i(?:'m| am)|my age is)\s+(\d{1,3})\b", text.lower()):
            if int(match.group(1)) not in known_ages:
                return True
    return False


def _location_fact_contradicted(draft: Any, hard_facts: list[Mapping[str, Any]]) -> bool:
    known_locations = {
        str(content[key]).strip().lower()
        for content in hard_facts
        for key in ("city", "location", "residence", "home_city", "based_in")
        if content.get(key)
    }
    if not known_locations:
        return False
    claim_markers = ("i live in ", "i'm in ", "i am in ", "based in ", "i'm based in ", "from ")
    for text in _draft_texts(draft):
        normalized = text.lower()
        if any(marker in normalized for marker in claim_markers) and not any(
            location in normalized for location in known_locations
        ):
            return True
    return False


def _mentions_forbidden_overseas_study(text: str) -> bool:
    forbid_terms = ("do not", "don't", "dont", "never", "avoid", "forbid", "forbids", "forbidden")
    return any(term in text for term in forbid_terms) and "overseas study" in text


def _mentions_local_chinese_education(text: str) -> bool:
    return (
        "chinese university graduate" in text
        or ("chinese" in text and "university" in text)
        or ("china" in text and "university" in text)
    )


def _draft_contains_overseas_study_claim(draft: Any) -> bool:
    for value in _draft_texts(draft):
        if _contains_overseas_study_claim(value):
            return True
    return False


def _draft_texts(draft: Any) -> list[str]:
    values: list[str] = []
    for field_name in ("best_reply", "safer_reply", "bolder_reply"):
        value = getattr(draft, field_name, "")
        if isinstance(value, str):
            values.append(value)
    return values


def _contains_overseas_study_claim(text: str) -> bool:
    normalized = text.lower()
    return any(claim in normalized for claim in OVERSEAS_STUDY_CLAIMS)


def _requires_labeled_divergence_confirmation(draft: Any) -> bool:
    mode_notes = getattr(draft, "mode_notes", "")
    if isinstance(mode_notes, str) and mode_notes.strip():
        return False

    return any(
        _normalize_divergence(getattr(draft, field_name, "")) in {"medium", "high"}
        for field_name in ("stance_divergence", "persona_divergence")
    )


def _normalize_divergence(value: Any) -> str:
    if isinstance(value, Enum):
        return str(value.value).lower()
    return str(value).lower()


def _flatten_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return " ".join(_flatten_text(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_flatten_text(item) for item in value)
    return str(value)

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from dating_boost.core.standalone_runtime import StandaloneDraftPlanner
from dating_boost.policy.draft_review import DraftReviewDecision, DraftReviewFinding


def _review(code="quality_revision", category="naturalness", **overrides):
    finding = DraftReviewFinding(
        code=code, category=category, severity="medium", message="Revise wording.",
        revision_hint="Use one concrete conversational detail.", blocks_managed_send=True,
    )
    return replace(DraftReviewDecision(
        schema_version=1, status="needs_revision", allowed_for_display=True,
        allowed_for_stage=True, allowed_for_managed_send=False,
        requires_user_confirmation=False, primary_reason=code, summary={},
        findings=[finding], revision_hints=[finding.revision_hint], payload_hash="payload",
        payload_format="single_message", message_count=1, review_id="review_1",
    ), **overrides)


def _passed_review():
    return _review(
        status="ok", allowed_for_managed_send=True, primary_reason="passed",
        findings=[], revision_hints=[], review_id="review_2",
    )


@pytest.fixture
def planner_boundary(tmp_path, monkeypatch):
    observation = SimpleNamespace(app_id="tashuo", provenance={"runtime": "mac-ios-app"})
    evidence = SimpleNamespace(
        status="ok", context_pack={"fixture": True}, planner_recommendation={"recommended_move": "bridge_topic"},
        public_dict=lambda: {"status": "ok"},
    )
    backend = SimpleNamespace()
    audit = Mock()
    monkeypatch.setattr("dating_boost.core.repositories.ObservationRepository", lambda root: SimpleNamespace(load_latest_observation=lambda match_id: observation))
    monkeypatch.setattr("dating_boost.core.draft_evidence.build_draft_evidence", lambda *args, **kwargs: evidence)
    monkeypatch.setattr("dating_boost.intelligence.backend_factory.create_model_backend", lambda config: backend)
    monkeypatch.setattr("dating_boost.core.draft_review_audit.DraftReviewAuditRepository", lambda root: audit)
    generations = [SimpleNamespace(
        status="ok", primary_reason=None, draft_payload={"best_reply": f"Synthetic draft {index}"},
        generation_id=f"generation_{index}", self_review_attempts=[], summary=lambda: {"status": "ok"},
    ) for index in (1, 2)]
    generate = Mock(side_effect=generations)
    monkeypatch.setattr("dating_boost.intelligence.draft_generation.generate_reply_with_refinement", generate)

    def run(reviews):
        review = Mock(side_effect=reviews)
        monkeypatch.setattr("dating_boost.policy.draft_review.review_draft", review)
        planner = StandaloneDraftPlanner(tmp_path, backend_config={"type": "scripted"})
        result = planner.draft_for_match(match_id="synthetic_match", mode="adaptive", supplemental_prompts=["Original constraint."])
        return result, generate, review, audit

    return run


@pytest.mark.parametrize(("code", "category"), [
    ("naturalness_abstract_wording", "naturalness"),
    ("draft_strategy_no_delta", "strategy"),
    ("draft_stale_temporal_topic_without_bridge", "temporal_fit"),
])
def test_quality_contract_gets_one_rewrite_then_same_review_and_audit(planner_boundary, code, category):
    first = _review(code, category)
    final = _passed_review()
    result, generate, review, audit = planner_boundary([first, final])

    assert result["status"] == "ok"
    assert result["draft"]["best_reply"] == "Synthetic draft 2"
    assert result["draft_review"] == final.to_dict()
    assert generate.call_count == review.call_count == audit.append_review.call_count == 2
    assert first.revision_hints[0] in generate.call_args_list[1].kwargs["supplemental_prompts"][-1]
    for generation_call, review_call, audit_call in zip(generate.call_args_list, review.call_args_list, audit.append_review.call_args_list, strict=True):
        assert generation_call.kwargs["max_attempts"] == 1
        assert generation_call.kwargs["model_self_review"] is False
        assert generation_call.kwargs["supplemental_prompts"][0] == "Original constraint."
        assert review_call.kwargs["mode"] == audit_call.kwargs["mode"] == "managed_live"
        assert audit_call.kwargs["draft_payload"] == review_call.args[0]
    assert [call.args[0] for call in audit.append_review.call_args_list] == [first, final]


def test_quality_still_blocked_after_exactly_one_rewrite(planner_boundary):
    first = _review()
    final = replace(first, review_id="review_2")
    result, generate, review, audit = planner_boundary([first, final])

    assert result["status"] == "blocked"
    assert result["reason"] == final.primary_reason
    assert result["draft_review"] == final.to_dict()
    assert generate.call_count == review.call_count == audit.append_review.call_count == 2


@pytest.mark.parametrize("case", ["confirmation", "high", "hard_display", "hard_stage", "mixed_confirmation", "blocked_status", "stage_disallowed"])
def test_hard_confirmation_and_mixed_findings_never_rewrite(planner_boundary, case):
    # Include a formerly whitelisted quality code: it cannot override a hard
    # finding in the same review, even if summary flags are inconsistent.
    review = _review("draft_revision_required")
    if case in {"high", "hard_display", "hard_stage", "mixed_confirmation"}:
        hard = DraftReviewFinding(
            code="hard_boundary", category="content", severity="high" if case == "high" else "medium",
            message="A hard boundary applies.", blocks_display=case == "hard_display",
            blocks_stage=case == "hard_stage", requires_user_confirmation=case == "mixed_confirmation",
        )
        review = replace(review, findings=[*review.findings, hard])
    elif case == "confirmation":
        review = replace(review, requires_user_confirmation=True)
    elif case == "blocked_status":
        review = replace(review, status="blocked")
    else:
        review = replace(review, allowed_for_stage=False)

    result, generate, checked, audit = planner_boundary([review])

    assert result["status"] == "blocked"
    assert generate.call_count == checked.call_count == audit.append_review.call_count == 1


def test_already_allowed_review_does_not_rewrite(planner_boundary):
    result, generate, review, audit = planner_boundary([_passed_review()])
    assert result["status"] == "ok"
    assert generate.call_count == review.call_count == audit.append_review.call_count == 1

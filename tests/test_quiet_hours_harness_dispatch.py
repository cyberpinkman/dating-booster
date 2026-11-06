import hashlib
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from dating_boost import cli_harness
from dating_boost.apps.registry import create_adapter
from dating_boost.core.live_send_contract import pre_send_time_block
from tests.gui_harness_support import (
    FakeRunner, _autonomous_audit_binding, _draft_generation_binding, _live_send_auth,
    _planner_evidence, _run_cli_json, _select_runtime_scope, _write_draft_review_audit, _write_json,
)

pytestmark = pytest.mark.managed_critical


def test_harness_keeps_validated_quiet_hours_until_return(tmp_path: Path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    before_window = datetime(2026, 11, 6, 22, 59, 59).astimezone().isoformat()
    inside_window = datetime(2026, 11, 6, 23, 0).astimezone().isoformat()
    monkeypatch.setenv("DATING_BOOST_NOW", before_window)
    _select_runtime_scope(data_dir, "wechat")

    draft = "收到啦"
    draft_path = tmp_path / "draft.txt"
    draft_path.write_text(draft, encoding="utf-8")
    digest = hashlib.sha256(draft.encode()).hexdigest()
    auth_id, target = "auth_quiet", "match_ada"
    auth_path, request_path = tmp_path / "auth.json", tmp_path / "request.json"
    auth = _live_send_auth("wechat", authorization_id=auth_id, allowed_match_ids=[target])
    _write_json(auth_path, {**auth, "quiet_hours": ["23:00-08:00"]})
    _write_json(request_path, {
        "schema_version": 1, "action_request_id": "fixture_request", "action": "send_message", "app_id": "wechat",
        "match_id": target, "candidate_key": "wechat_ada", "payload_hash": digest, "precondition_hash": "pre_hash",
        "autonomous_audit_binding": _autonomous_audit_binding(authorization_id=auth_id, target_match_id=target, payload_hash=digest),
        "requires_post_action_verification": True, "draft_review_id": "draft_review_fixture",
        "policy": {"allowed": True, "draft_review_id": "draft_review_fixture"},
        "target_binding": {"target_match_id": target, "candidate_key": "wechat_ada", "required_visible_text": ["Ada"]},
        **_draft_generation_binding(), **_planner_evidence(),
    })
    _write_draft_review_audit(data_dir, target_match_id=target, payload_hash=digest)
    runner = FakeRunner(ocr_text="微信\nAda\n昨天 21:14\n在吗\n发送\n", window_name="WeChat")
    adapter = create_adapter(app_id="wechat", platform="darwin", runner=runner, window_title="WeChat")
    runtime_scope_check = cli_harness._runtime_scope_block_payload
    stage_draft = adapter.session.stage_wechat_draft

    def replace_authorization_after_validation(*args):
        _write_json(auth_path, {**auth, "quiet_hours": []})
        return runtime_scope_check(*args)

    def stage_across_cutoff(*args, **kwargs):
        staged = stage_draft(*args, **kwargs)
        assert staged["status"] == "ok"
        monkeypatch.setenv("DATING_BOOST_NOW", inside_window)
        return staged

    with (
        patch.object(cli_harness, "_runtime_scope_block_payload", side_effect=replace_authorization_after_validation),
        patch("dating_boost.cli.create_adapter", return_value=adapter),
        patch.object(adapter.session, "stage_wechat_draft", side_effect=stage_across_cutoff),
    ):
        code, result = _run_cli_json([
            "harness", "wechat", "send-message", "--data-dir", str(data_dir), "--authorization", str(auth_path),
            "--action-request", str(request_path), "--text-file", str(draft_path), "--output-dir", str(tmp_path / "frames"), "--json",
        ])

    assert (code, result["reason"], result["send_action_executed"]) == (2, "authorization_quiet_hours", False)
    assert runner.focused_text == draft
    assert not any("key code 36" in " ".join(command) for command in runner.commands)
    assert pre_send_time_block() is None

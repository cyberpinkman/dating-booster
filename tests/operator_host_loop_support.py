import json
import hashlib
import os
import subprocess
import sys
import tempfile
import argparse
import unittest
from unittest.mock import patch
from pathlib import Path
import shutil

from dating_boost.cli import main
from dating_boost.core.operator import OperatorRepository
from dating_boost.host_loop import (
    HostLoopCommandError, HostLoopError, HostLoopSupervisor, _target_binding_for_work_item,
    _thread_template, _validate_managed_sequence_visual_confirmation,
)
from dating_boost.perception.observations import AppObservation
from tests.gui_harness_support import (
    _bumble_conversation_png,
    _tashuo_mac_ios_app_conversation_with_messages_png,
    _tinder_conversation_send_button_png,
)


FIXTURE_DIR = Path("tests/fixtures/host_loop/tinder")




class OperatorHostLoopTestCase(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        self._env["DATING_BOOST_NOW"] = "2026-05-26T00:00:00Z"

    def _bootstrap_data_dir(self, data_dir: Path) -> None:
        for argv in (
            [
                "init-profile",
                "--data-dir",
                str(data_dir),
                "--input",
                str(FIXTURE_DIR / "user_profile.json"),
            ],
            [
                "user",
                "ingest-profile",
                "--data-dir",
                str(data_dir),
                "--input",
                str(FIXTURE_DIR / "user_dating_profile.json"),
            ],
            [
                "user",
                "ingest-interview",
                "--data-dir",
                str(data_dir),
                "--input",
                str(FIXTURE_DIR / "user_self_interview.json"),
            ],
        ):
            exit_code, _payload = self._run_cli(argv)
            self.assertEqual(exit_code, 0)

    def _run_cli(self, argv):
        from contextlib import redirect_stdout
        from io import StringIO

        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(argv)
        return exit_code, json.loads(output.getvalue())

    def _run_script(self, *args: str) -> dict:
        result = subprocess.run(
            [sys.executable, "scripts/operator_host_loop.py", *args],
            cwd=Path.cwd(),
            env=self._env,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        return json.loads(result.stdout)

    def _write_json(self, path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

def _action_result_for_work_item(work_item: dict) -> dict:
    return {
        "action_request_id": work_item["action_request_id"],
        "action": "send_message",
        "target_match_id": work_item["match_id"],
        "payload_hash": work_item["payload_hash"],
        "precondition_hash": work_item["precondition_hash"],
        "autonomous_audit_binding": work_item["autonomous_audit_binding"],
        "pre_action_observation_id": work_item.get("pre_action_observation_id"),
        "post_action_observation_id": f"{work_item.get('pre_action_observation_id')}_sent",
        "result_status": "succeeded",
        "evidence": {
            "post_send_visible_text": work_item["payload_text"],
            "staged_text_verified": True,
        },
    }

def _audit_binding(*, authorization_id: str, target_match_id: str, payload_hash: str, precondition_hash: str = "pre_hash") -> dict:
    return {
        "schema_version": 1,
        "binding_type": "autonomous_authorization",
        "authorization_id": authorization_id,
        "action": "send_message",
        "target_match_id": target_match_id,
        "payload_hash": payload_hash,
        "precondition_hash": precondition_hash,
    }

def _write_draft_review_audit(data_dir: Path, work_item: dict) -> None:
    review_id = str(work_item.get("draft_review_id") or "").strip()
    payload_hash = str(work_item.get("payload_hash") or "").strip()
    target_match_id = str(work_item.get("match_id") or work_item.get("target_match_id") or "").strip()
    if not review_id or not payload_hash or not target_match_id:
        return
    payload_messages = work_item.get("payload_messages")
    message_count = len(payload_messages) if isinstance(payload_messages, list) and payload_messages else 1
    path = data_dir / "audit" / "draft_reviews.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": 1,
        "review_id": review_id,
        "created_at": "2026-05-26T00:00:00Z",
        "mode": "managed_live",
        "target_match_id": target_match_id,
        "payload_hash": payload_hash,
        "payload_format": work_item.get("payload_format") or "single_message",
        "message_count": message_count,
        "status": "ok",
        "allowed_for_display": True,
        "allowed_for_stage": True,
        "allowed_for_managed_send": True,
        "requires_user_confirmation": False,
        "primary_reason": "passed",
        "finding_codes": [],
        "findings": [],
        "revision_hint_count": 0,
        "context_manifest": [],
        "draft_payload_hash": payload_hash,
        "context_pack_hash": "context_fixture",
        "draft_topic_labels": [],
        "draft_character_count": len(str(work_item.get("payload_text") or "")),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    generation_id = str(work_item.get("draft_generation_id") or "").strip()
    evidence_id = str(work_item.get("draft_evidence_id") or "").strip()
    if generation_id and evidence_id:
        generation_path = data_dir / "audit" / "draft_generations.jsonl"
        generation_record = {
            "schema_version": 1,
            "generation_id": generation_id,
            "evidence_id": evidence_id,
            "prompt_id": "prompt_fixture",
            "status": "ok",
            "primary_reason": None,
            "prompt_hash": "prompt_hash_fixture",
            "context_hash": "context_hash_fixture",
            "draft_hash": payload_hash,
            "attempt_count": 1,
            "self_review_attempts": [
                {
                    "ai_or_weird_probability": 20,
                    "reason": "fixture_passed",
                    "supplemental_prompt_hash": "",
                }
            ],
            "created_at": "2026-05-26T00:00:00Z",
        }
        with generation_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(generation_record, ensure_ascii=False, sort_keys=True) + "\n")

def _wechat_managed_work_item(payload_text: str, payload_hash: str) -> dict:
    return {
        "schema_version": 1,
        "work_item_id": "work_wechat_send",
        "work_item_type": "send_message",
        "action_request_id": "act_wechat_send",
        "match_id": "match_wechat",
        "candidate_key": "wechat_ada",
        "payload_text": payload_text,
        "payload_hash": payload_hash,
        "precondition_hash": "pre_hash",
        "autonomous_audit_binding": _audit_binding(
            authorization_id="auth_wechat_live",
            target_match_id="match_wechat",
            payload_hash=payload_hash,
        ),
        "pre_action_observation_id": "obs_before",
        "target_profile_observation": {
            "review_status": "observed",
            "profile_text": "喜欢日料，周末常去看展。",
            "photo_cues": [],
            "hook_candidates": ["日料", "看展"],
            "evidence": "Profile was reviewed before drafting.",
        },
        "requires_post_action_verification": True,
        "draft_review_id": "draft_review_fixture",
        "draft_evidence_id": "draft_evidence_fixture",
        "draft_generation_id": "draft_generation_fixture",
        "latest_turn_id": "latest_turn_fixture",
        "conversation_thread_revision": 1,
        "draft_self_review_summary": {
            "schema_version": 1,
            "status": "ok",
            "ai_or_weird_probability": 20,
            "attempts": 1,
            "source": "unit_fixture",
        },
        "policy": {"allowed": True, "draft_review_id": "draft_review_fixture"},
        "planner_alignment": "ok",
        "conversation_stage": "rapport_building",
        "conversation_move": "warm_reciprocal_question",
        "target_binding": {"required_visible_text": ["Ada"], "target_match_id": "match_wechat"},
    }

def _iphone_current_thread_target_binding(app_id: str, target_match_id: str, candidate_key: str) -> dict:
    return {
        "binding_type": "current_thread_visual_identity",
        "target_match_id": target_match_id,
        "candidate_key": candidate_key,
        "conversation_fingerprint": f"{candidate_key}:thread",
        "thread_evidence": {
            "observation_id": f"obs_{candidate_key}",
            "screen_state": f"{app_id}_conversation",
            "latest_inbound_fingerprint": f"{candidate_key}:latest-inbound",
            "visual_anchor_hash": "0123456789abcdef",
        },
    }

import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from dating_boost import __version__
from dating_boost.cli import main


REQUIRED_AGENT_NATIVE_COMMANDS = {
    "capabilities",
    "memory ingest-observation",
    "memory get-match",
    "memory update-match",
    "context build",
    "policy check-draft",
    "policy check-action",
    "action record-result",
    "feedback record",
}


class AgentNativeCliTests(unittest.TestCase):
    def test_capabilities_json_contract_lists_schema_and_commands(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "memory"
            output = StringIO()

            with redirect_stdout(output):
                exit_code = main(["capabilities", "--json", "--data-dir", str(data_dir)])

            payload = json.loads(output.getvalue())

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["schema_version"], 1)
            self.assertEqual(payload["tool_version"], __version__)
            self.assertIsInstance(payload["git_commit"], str)
            self.assertEqual(payload["data_dir"], str(data_dir.resolve()))
            self.assertEqual(payload["schema_versions"]["action_result"], 1)
            self.assertEqual(payload["schema_versions"]["stage_result"], 1)
            self.assertEqual(payload["schema_versions"]["action_correction"], 1)
            self.assertEqual(payload["schema_versions"]["reply_draft"], 4)
            self.assertEqual(payload["schema_versions"]["draft_review"], 1)
            self.assertEqual(payload["schema_versions"]["user_disclosure_profile"], 1)
            self.assertEqual(payload["schema_versions"]["user_readiness"], 1)
            self.assertEqual(payload["schema_versions"]["planner_assessment"], 1)
            self.assertEqual(payload["schema_versions"]["goal_plan"], 1)
            self.assertEqual(payload["schema_versions"]["planner_recommendation"], 1)
            self.assertEqual(payload["schema_versions"]["data_store"], 2)
            self.assertEqual(payload["schema_versions"]["migration"], 1)
            self.assertEqual(payload["schema_versions"]["automation_lock"], 1)
            self.assertEqual(payload["schema_versions"]["confirmation"], 1)
            self.assertEqual(payload["schema_versions"]["production_smoke"], 1)
            self.assertEqual(payload["schema_versions"]["backup_recovery_key"], 1)
            self.assertEqual(payload["schema_versions"]["support_log"], 1)
            self.assertEqual(payload["schema_versions"]["support_evidence"], 1)
            self.assertTrue(REQUIRED_AGENT_NATIVE_COMMANDS.issubset(set(payload["supported_commands"])))
            self.assertIn("data doctor", payload["supported_commands"])
            self.assertIn("data migrate", payload["supported_commands"])
            self.assertIn("data export", payload["supported_commands"])
            self.assertIn("data delete", payload["supported_commands"])
            self.assertIn("confirmation create", payload["supported_commands"])
            self.assertIn("confirmation confirm", payload["supported_commands"])
            self.assertIn("confirmation validate", payload["supported_commands"])
            self.assertIn("support session start", payload["supported_commands"])
            self.assertIn("support bundle", payload["supported_commands"])
            self.assertIn("action record-correction", payload["supported_commands"])
            self.assertIn("operator record-stage-result", payload["supported_commands"])
            self.assertNotIn("workflow draft", payload["supported_commands"])
            self.assertIn("planner update", payload["supported_commands"])
            self.assertIn("planner get", payload["supported_commands"])
            self.assertIn("planner recommend", payload["supported_commands"])
            self.assertIn("planner event-log", payload["supported_commands"])
            self.assertIn("user readiness", payload["supported_commands"])
            self.assertIn("harness tinder observe", payload["supported_commands"])
            self.assertIn("harness tinder action", payload["supported_commands"])
            self.assertIn("harness tinder workflow", payload["supported_commands"])
            self.assertIn("policy_capabilities", payload)
            self.assertIn("memory_capabilities", payload)
            self.assertIn("storage_capabilities", payload)
            self.assertIn("agent_native_capabilities", payload)
            self.assertTrue(payload["storage_capabilities"]["sqlite"])
            self.assertTrue(payload["storage_capabilities"]["backup_requires_recovery_passphrase"])
            self.assertEqual(payload["storage_capabilities"]["backup_recovery_passphrase_sources"], ["env", "file"])
            self.assertTrue(payload["memory_capabilities"]["export"])
            self.assertTrue(payload["memory_capabilities"]["delete"])
            self.assertTrue(payload["policy_capabilities"]["confirmation_contract"])
            self.assertTrue(payload["agent_native_capabilities"]["production_smoke"])
            self.assertTrue(payload["agent_native_capabilities"]["real_stage_smoke_required"])
            self.assertTrue(payload["agent_native_capabilities"]["goal_oriented_planning"])
            self.assertTrue(payload["agent_native_capabilities"]["conversation_scores"])
            self.assertTrue(payload["agent_native_capabilities"]["topic_lifecycle"])
            self.assertTrue(payload["agent_native_capabilities"]["soft_invite_probe"])
            self.assertTrue(payload["agent_native_capabilities"]["planner_report"])
            self.assertTrue(payload["agent_native_capabilities"]["stage_only_audit"])
            self.assertTrue(payload["agent_native_capabilities"]["action_correction_audit"])
            self.assertTrue(payload["agent_native_capabilities"]["self_disclosure_profile"])
            self.assertTrue(payload["agent_native_capabilities"]["low_investment_repair"])
            self.assertTrue(payload["agent_native_capabilities"]["tinder_profile_read_harness"])
            self.assertTrue(payload["agent_native_capabilities"]["tinder_chat_navigation_harness"])
            self.assertIsInstance(payload["warnings"], list)

    def test_nested_agent_native_commands_reuse_mvp_storage_and_policy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            profile_path = Path(temp_dir) / "profile.json"
            profile_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "user_id": "user_local",
                        "facts": [
                            {
                                "id": "fact_local_education",
                                "kind": "fact",
                                "content": {"education": "Chinese university graduate"},
                                "source_type": "user_input",
                                "evidence": "User confirmed local education background.",
                                "confidence": "high",
                                "created_at": "2026-05-25T00:00:00Z",
                                "last_seen_at": "2026-05-25T00:00:00Z",
                            }
                        ],
                        "preferences": [],
                        "boundaries": [],
                        "style_examples": ["short, warm, dry humor"],
                        "goals": ["practice better dating conversations"],
                        "persona_baseline": "reserved",
                        "persona_range": ["warmer", "more outgoing"],
                        "stance_range": ["can express curiosity about new interests"],
                        "updated_at": "2026-05-25T00:00:00Z",
                        "default_reply_mode": "adaptive",
                    }
                ),
                encoding="utf-8",
            )

            self._run([
                "init-profile",
                "--data-dir",
                str(data_dir),
                "--input",
                str(profile_path),
            ])
            ingest_exit, ingest_payload, _ = self._run([
                "memory",
                "ingest-observation",
                "--data-dir",
                str(data_dir),
                "--input",
                "tests/fixtures/intelligence/app_observation_chat.json",
            ])
            match_id = ingest_payload["match_id"]

            get_exit, match_payload, _ = self._run([
                "memory",
                "get-match",
                "--data-dir",
                str(data_dir),
                "--match-id",
                match_id,
            ])
            context_exit, context_payload, _ = self._run([
                "context",
                "build",
                "--data-dir",
                str(data_dir),
                "--match-id",
                match_id,
                "--mode",
                "adaptive",
            ])

            context_path = data_dir / "context_payload.json"
            draft_path = data_dir / "blocked_draft.json"
            context_path.write_text(json.dumps(context_payload), encoding="utf-8")
            draft_path.write_text(
                json.dumps(
                    {
                        "best_reply": "I studied overseas too. London was incredible.",
                        "safer_reply": "I studied in London too.",
                        "bolder_reply": "I went to university in London, so I get it.",
                        "why_this_works": "It invents an education connection.",
                        "situation_read": "Blocked policy test situation.",
                        "conversation_move": "deepen_current",
                        "hook_source": "profile_unknown_detail",
                        "naturalness_notes": ["unit test fixture"],
                        "followup_if_match_replies": "Stop if policy blocks.",
                        "risk_flags": ["contradicts hard facts"],
                        "missing_info": [],
                        "mode_notes": "Adaptive mode.",
                        "persona_divergence": "low",
                        "stance_divergence": "low",
                    }
                ),
                encoding="utf-8",
            )
            check_exit, check_payload, check_text = self._run([
                "policy",
                "check-draft",
                "--input",
                str(draft_path),
                "--context",
                str(context_path),
            ])

            self.assertEqual(ingest_exit, 0)
            self.assertEqual(get_exit, 0)
            self.assertEqual(context_exit, 0)
            self.assertEqual(check_exit, 2)
            self.assertEqual(match_payload["match"]["match_id"], match_id)
            self.assertIn("obs_chat_001", match_payload["match"]["observation_ids"])
            self.assertEqual(context_payload["context_pack"]["reply_mode"], "adaptive")
            self.assertEqual(check_payload["status"], "blocked")
            self.assertFalse(check_payload["draft_review"]["allowed_for_display"])
            self.assertIn("content_hard_fact", check_payload["draft_review"]["summary"]["finding_codes"])
            self.assertNotIn("policy", check_payload)
            self.assertNotIn("best_reply", check_payload)
            self.assertNotIn("I studied overseas too", check_text)

    def test_policy_check_action_matches_authorize(self):
        authorize_exit, authorize_payload, _ = self._run(["authorize", "send_message", "--autonomous"])
        policy_exit, policy_payload, _ = self._run([
            "policy",
            "check-action",
            "send_message",
            "--autonomous",
        ])

        self.assertEqual(authorize_exit, 0)
        self.assertEqual(policy_exit, 0)
        for key in ("allowed", "action", "autonomous", "reason"):
            self.assertEqual(policy_payload[key], authorize_payload[key])

    def test_feedback_record_alias_appends_event(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)

            exit_code, payload, _ = self._run([
                "feedback",
                "record",
                "--data-dir",
                str(data_dir),
                "--match-id",
                "match_alex",
                "--draft-id",
                "draft_1",
                "--mode",
                "adaptive",
                "--label",
                "accepted",
            ])

            events_path = data_dir / "matches" / "match_alex" / "feedback_events.jsonl"
            events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(events[0]["label"], "accepted")

    def test_action_record_result_writes_audit_jsonl_for_each_result_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)

            for status in ("succeeded", "failed", "unknown"):
                input_path = data_dir / f"{status}.json"
                input_path.write_text(
                    json.dumps(
                        {
                            "action_request_id": f"action_request_{status}",
                            "action": "send_message",
                            "target_match_id": "match_alex",
                            "payload_hash": f"sha256:{status}",
                            "pre_action_observation_id": "obs_before",
                            "post_action_observation_id": f"obs_after_{status}",
                            "result_status": status,
                            "evidence": {
                                "verification": f"post-action screenshot reviewed as {status}",
                            },
                        }
                    ),
                    encoding="utf-8",
                )

                exit_code, payload, _ = self._run([
                    "action",
                    "record-result",
                    "--data-dir",
                    str(data_dir),
                    "--input",
                    str(input_path),
                ])

                self.assertEqual(exit_code, 0)
                self.assertEqual(payload["status"], "ok")

            audit_path = data_dir / "audit" / "action_results.jsonl"
            events = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]

            self.assertEqual([event["result_status"] for event in events], ["succeeded", "failed", "unknown"])
            self.assertEqual(events[0]["schema_version"], 1)
            self.assertEqual(events[0]["action"], "send_message")
            self.assertEqual(events[0]["payload_hash"], "sha256:succeeded")

    def test_action_record_result_rejects_invalid_status_missing_hash_and_missing_evidence(self):
        invalid_payloads = [
            {
                "action": "send_message",
                "target_match_id": "match_alex",
                "payload_hash": "sha256:x",
                "pre_action_observation_id": "obs_before",
                "post_action_observation_id": "obs_after",
                "result_status": "maybe",
                "evidence": {"verification": "invalid status"},
            },
            {
                "action": "send_message",
                "target_match_id": "match_alex",
                "pre_action_observation_id": "obs_before",
                "post_action_observation_id": "obs_after",
                "result_status": "unknown",
                "evidence": {"verification": "missing hash"},
            },
            {
                "action": "send_message",
                "target_match_id": "match_alex",
                "payload_hash": "sha256:missing-request",
                "pre_action_observation_id": "obs_before",
                "post_action_observation_id": "obs_after",
                "result_status": "unknown",
                "evidence": {"verification": "missing action request id"},
            },
            {
                "action": "send_message",
                "target_match_id": "match_alex",
                "payload_hash": "sha256:y",
                "pre_action_observation_id": "obs_before",
                "post_action_observation_id": "obs_after",
                "result_status": "unknown",
            },
        ]

        for index, payload in enumerate(invalid_payloads):
            with self.subTest(index=index):
                with tempfile.TemporaryDirectory() as temp_dir:
                    data_dir = Path(temp_dir)
                    input_path = data_dir / "invalid.json"
                    input_path.write_text(json.dumps(payload), encoding="utf-8")

                    exit_code, error_payload, _ = self._run([
                        "action",
                        "record-result",
                        "--data-dir",
                        str(data_dir),
                        "--input",
                        str(input_path),
                    ])

                    self.assertEqual(exit_code, 2)
                    self.assertEqual(error_payload["status"], "error")
                    self.assertFalse((data_dir / "audit" / "action_results.jsonl").exists())

    def test_action_record_correction_appends_without_rewriting_history(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            result_path = data_dir / "result.json"
            correction_path = data_dir / "correction.json"
            result_path.write_text(
                json.dumps(
                    {
                        "action_request_id": "action_request_stage_misrecorded",
                        "action": "send_message",
                        "target_match_id": "match_alex",
                        "payload_hash": "sha256:stage-only",
                        "pre_action_observation_id": "obs_before",
                        "post_action_observation_id": "obs_after",
                        "result_status": "succeeded",
                        "evidence": {"verification": "legacy mistaken send audit"},
                    }
                ),
                encoding="utf-8",
            )
            self._run(["action", "record-result", "--data-dir", str(data_dir), "--input", str(result_path)])
            original_events = (data_dir / "audit" / "action_results.jsonl").read_text(encoding="utf-8").splitlines()
            correction_path.write_text(
                json.dumps(
                    {
                        "corrects_event_id": "action_result_manual_001",
                        "corrected_status": "unknown",
                        "reason": "This was only staged, not sent.",
                        "evidence": {"review": "fresh audit split stage-only from send"},
                    }
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"DATING_BOOST_NOW": "2026-06-12T04:48:00Z"}):
                exit_code, payload, _ = self._run([
                    "action",
                    "record-correction",
                    "--data-dir",
                    str(data_dir),
                    "--input",
                    str(correction_path),
                ])
            current_events = (data_dir / "audit" / "action_results.jsonl").read_text(encoding="utf-8").splitlines()
            corrections = [
                json.loads(line)
                for line in (data_dir / "audit" / "action_corrections.jsonl").read_text(encoding="utf-8").splitlines()
            ]

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(current_events, original_events)
            self.assertEqual(corrections[0]["corrected_status"], "unknown")
            self.assertEqual(corrections[0]["corrects_event_id"], "action_result_manual_001")
            self.assertEqual(corrections[0]["created_at"], "2026-06-12T04:48:00Z")

    def _run(self, argv):
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(argv)
        text = output.getvalue()
        return exit_code, json.loads(text), text


if __name__ == "__main__":
    unittest.main()

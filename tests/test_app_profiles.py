import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = ROOT / "app_profiles"
SCHEMA_PATH = ROOT / "schemas" / "app_profile.schema.json"

SUPPORT_LEVELS = {
    "native_observation",
    "native_navigation",
    "native_draft_staging",
    "managed_live_send",
}
REQUIRED_FIELDS = {
    "schema_version",
    "app_id",
    "display_name",
    "support_level",
    "host_loop_supported",
    "host_loop_send_modes",
    "message_list_observation",
    "thread_observation",
    "stage_send_verification",
    "native_gui_harness",
    "adapter",
    "capabilities",
    "selectors",
    "target_binding",
    "live_send_requirements",
    "managed_session",
    "special_policies",
    "post_send_verification",
    "known_gui_pitfalls",
    "unsupported_actions",
}


class AppProfileContractTests(unittest.TestCase):
    def test_schema_file_defines_required_profile_contract(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        self.assertEqual(schema["title"], "Dating Booster App Profile")
        self.assertEqual(set(schema["required"]), REQUIRED_FIELDS)
        self.assertEqual(set(schema["properties"]["support_level"]["enum"]), SUPPORT_LEVELS)
        self.assertIn("native_gui_harness", schema["properties"])

    def test_all_app_profiles_validate_against_json_schema(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)
        profile_paths = sorted(PROFILE_DIR.glob("*.json"))
        self.assertTrue(profile_paths)

        for path in profile_paths:
            with self.subTest(profile=path.name):
                profile = json.loads(path.read_text(encoding="utf-8"))
                errors = sorted(validator.iter_errors(profile), key=lambda error: tuple(error.path))
                self.assertEqual([error.message for error in errors], [])
                self.assertEqual(profile["schema_version"], 2)
                self.assertEqual(profile["app_id"], path.stem)
                if profile["host_loop_supported"]:
                    self.assertTrue(profile["host_loop_send_modes"], path.name)
                self.assertIn("native_gui_harness", profile)
                self.assertTrue(profile["native_gui_harness"]["supported_stage_actions"])
                self.assertEqual(profile["adapter"]["backend"], profile["native_gui_harness"]["backend"])
                self.assertEqual(profile["capabilities"]["host_loop_supported"], profile["host_loop_supported"])
                self.assertEqual(profile["capabilities"]["send_modes"], profile["host_loop_send_modes"])
                self.assertEqual(
                    profile["capabilities"]["stage_actions"],
                    profile["native_gui_harness"]["supported_stage_actions"],
                )
                self.assertEqual(
                    profile["capabilities"]["live_actions"],
                    profile["native_gui_harness"]["supported_live_actions"],
                )
                self.assertEqual(
                    profile["selectors"]["blocked_actions"],
                    profile["native_gui_harness"]["blocked_actions"],
                )
                if "native_gui_harness" in profile:
                    harness = profile["native_gui_harness"]
                    self.assertTrue(harness["backend"])
                    self.assertTrue(harness["supported_stage_actions"])
                    self.assertIn("blocked_actions", harness)
                    exposes_live_send = (
                        "live" in profile["host_loop_send_modes"]
                        or bool(harness.get("supported_live_actions"))
                        or "live_send" in harness
                    )
                    if exposes_live_send:
                        self.assertEqual(profile["support_level"], "managed_live_send")
                managed = profile["managed_session"]
                for key in (
                    "default_max_threads_per_cycle",
                    "high_throughput_max_threads_per_cycle",
                    "cycle_send_limit",
                    "message_list_pagination_supported",
                ):
                    self.assertIn(key, managed, path.name)

    def test_bumble_opening_move_policy_is_role_sensitive_and_managed_send_safe(self):
        profile = json.loads((PROFILE_DIR / "bumble.json").read_text(encoding="utf-8"))

        self.assertEqual(profile["support_level"], "managed_live_send")
        self.assertTrue(profile["host_loop_supported"])
        self.assertEqual(profile["host_loop_send_modes"], ["stage", "live"])
        self.assertIn("send_message", profile["native_gui_harness"]["supported_live_actions"])
        self.assertTrue(profile["native_gui_harness"]["live_send"]["requires_exact_staged_text_verification"])
        self.assertTrue(profile["native_gui_harness"]["live_send"]["requires_outbound_bubble_verification"])

        policy = profile["opening_move_policy"]

        self.assertEqual(policy["scope"], "bumble_opening_move")
        self.assertEqual(policy["female_user"]["agent_decision_authority"], "none")
        self.assertEqual(
            set(policy["female_user"]["user_decision_required"]),
            {"enable_opening_move", "skip_opening_move", "accept_male_reply", "reject_male_reply"},
        )
        self.assertIn("ask_user_to_decide", policy["female_user"]["agent_allowed_actions"])
        self.assertIn("enable_opening_move", policy["female_user"]["agent_disallowed_actions"])
        self.assertIn("reject_male_reply", policy["female_user"]["agent_disallowed_actions"])

        self.assertTrue(policy["male_user"]["agent_may_draft_reply"])
        self.assertTrue(policy["male_user"]["requires_user_confirmation_before_send"])
        self.assertTrue(policy["male_user"]["current_harness_stage_supported"])
        self.assertTrue(policy["male_user"]["current_harness_send_supported"])
        self.assertFalse(policy["male_user"]["autonomous_opening_move_send_supported"])
        self.assertIn("draft_opening_move_reply", policy["male_user"]["agent_allowed_actions"])
        self.assertIn(
            "send_opening_move_reply_without_user_confirmation",
            policy["male_user"]["agent_disallowed_actions"],
        )

        blocked = set(profile["native_gui_harness"]["blocked_actions"])
        self.assertTrue(
            {
                "opening_move_enable",
                "opening_move_skip",
                "opening_move_decide_reply_satisfaction",
                "opening_move_send",
            }.issubset(blocked)
        )

    def test_tashuo_question_gate_policy_is_role_sensitive_and_managed_send_safe(self):
        profile = json.loads((PROFILE_DIR / "tashuo.json").read_text(encoding="utf-8"))

        self.assertEqual(profile["support_level"], "managed_live_send")
        self.assertTrue(profile["host_loop_supported"])
        self.assertEqual(profile["host_loop_send_modes"], ["stage", "live"])
        self.assertIn("send_message", profile["native_gui_harness"]["supported_live_actions"])
        self.assertEqual(profile["native_gui_harness"]["launch_navigation"]["app_name"], "tashu")
        self.assertEqual(
            profile["native_gui_harness"]["launch_navigation"]["expected_app_labels"],
            ["tashu", "她说", "TaShuo"],
        )
        self.assertEqual(profile["native_gui_harness"]["launch_navigation"]["bundle_id"], "com.intelcupid.tashuo")
        self.assertTrue(profile["native_gui_harness"]["live_send"]["requires_exact_staged_text_verification"])
        self.assertTrue(profile["native_gui_harness"]["live_send"]["requires_outbound_bubble_verification"])
        stage_rules = "\n".join(profile["stage_send_verification"])
        self.assertIn("Direct typing is never allowed for Chinese", stage_rules)
        self.assertIn("Accessibility set-text", stage_rules)
        self.assertIn("chat_list_row_to_thread", profile["target_binding"]["allowed_structural_binding_types"])
        self.assertIn("current_thread_visual_identity", profile["target_binding"]["allowed_structural_binding_types"])
        pitfalls = "\n".join(profile["known_gui_pitfalls"])
        self.assertIn("visual_anchor_hash", pitfalls)
        self.assertIn("do not use message-list row position or header OCR", pitfalls)

        policy = profile["question_gate_policy"]

        self.assertEqual(policy["scope"], "tashuo_question_gate")
        self.assertEqual(policy["female_user"]["agent_decision_authority"], "none")
        self.assertEqual(
            set(policy["female_user"]["user_decision_required"]),
            {"enable_question", "skip_question_gate", "accept_male_reply", "reject_male_reply"},
        )
        self.assertIn("ask_user_to_decide", policy["female_user"]["agent_allowed_actions"])
        self.assertIn("skip_question_gate", policy["female_user"]["agent_disallowed_actions"])
        self.assertIn("reject_male_reply", policy["female_user"]["agent_disallowed_actions"])

        self.assertTrue(policy["male_user"]["agent_may_draft_reply"])
        self.assertTrue(policy["male_user"]["requires_user_confirmation_before_send"])
        self.assertFalse(policy["male_user"]["current_harness_stage_supported"])
        self.assertFalse(policy["male_user"]["current_harness_send_supported"])
        self.assertFalse(policy["male_user"]["autonomous_question_gate_send_supported"])
        self.assertIn("draft_question_gate_reply", policy["male_user"]["agent_allowed_actions"])
        self.assertIn(
            "send_question_gate_reply_without_user_confirmation",
            policy["male_user"]["agent_disallowed_actions"],
        )

        blocked = set(profile["native_gui_harness"]["blocked_actions"])
        self.assertTrue(
            {
                "question_gate_enable",
                "question_gate_skip",
                "question_gate_decide_reply_satisfaction",
                "question_gate_send",
            }.issubset(blocked)
        )

    def test_tashuo_mac_ios_app_stage_and_live_send_are_alternate_runtime_capabilities(self):
        profile = json.loads((PROFILE_DIR / "tashuo.json").read_text(encoding="utf-8"))

        self.assertNotIn("stage_draft", profile["native_gui_harness"]["supported_stage_actions"])
        self.assertNotIn("prepare_message_page", profile["native_gui_harness"]["supported_stage_actions"])
        self.assertNotIn("stage_draft", profile["capabilities"]["stage_actions"])
        self.assertNotIn("prepare_message_page", profile["capabilities"]["stage_actions"])
        mac_runtime = profile["native_gui_harness"]["alternate_runtimes"]["mac_ios_app"]
        self.assertEqual(mac_runtime["backend"], "mac_ios_app")
        self.assertIn("stage_draft", mac_runtime["supported_stage_actions"])
        self.assertIn("prepare_message_page", mac_runtime["supported_stage_actions"])
        self.assertIn("send_message", mac_runtime["supported_live_actions"])
        self.assertEqual(mac_runtime["live_send_status"], "supported")
        self.assertNotIn("live_send_block_reason", mac_runtime)
        self.assertTrue(mac_runtime["target_binding"]["visual_only_exact_verification_allowed"])
        self.assertTrue(mac_runtime["live_send_requirements"]["visual_only_exact_verification_allowed"])

    def test_iphone_dating_apps_allow_row_to_thread_binding_for_non_ocr_nicknames(self):
        for app_id in ("tinder", "bumble", "tashuo"):
            with self.subTest(app_id=app_id):
                profile = json.loads((PROFILE_DIR / f"{app_id}.json").read_text(encoding="utf-8"))
                self.assertIn("chat_list_row_to_thread", profile["target_binding"]["allowed_structural_binding_types"])

    def test_live_send_required_evidence_names_match_harness_payload_keys(self):
        known_evidence_keys = {
            "staged_text_verified",
            "staged_exact_text_verified",
            "staged_exact_text_ocr_verified",
            "input_cleared_after_send",
            "post_action_screen_captured",
            "outbound_message_verified",
            "outbound_exact_text_verified",
            "outbound_exact_text_ocr_verified",
        }

        for path in PROFILE_DIR.glob("*.json"):
            profile = json.loads(path.read_text(encoding="utf-8"))
            with self.subTest(app_id=profile["app_id"]):
                required = set(profile["live_send_requirements"]["required_evidence"])
                self.assertTrue(required)
                self.assertLessEqual(required, known_evidence_keys)
                runtimes = profile.get("native_gui_harness", {}).get("alternate_runtimes", {})
                for runtime_name, runtime_profile in runtimes.items():
                    runtime_requirements = runtime_profile.get("live_send_requirements")
                    if not isinstance(runtime_requirements, dict):
                        continue
                    with self.subTest(app_id=profile["app_id"], runtime=runtime_name):
                        runtime_required = set(runtime_requirements.get("required_evidence") or [])
                        self.assertTrue(runtime_required)
                        self.assertLessEqual(runtime_required, known_evidence_keys)

    def test_tashuo_default_and_mac_ios_live_send_required_evidence_are_runtime_specific(self):
        profile = json.loads((PROFILE_DIR / "tashuo.json").read_text(encoding="utf-8"))
        default_required = set(profile["live_send_requirements"]["required_evidence"])
        mac_required = set(
            profile["native_gui_harness"]["alternate_runtimes"]["mac_ios_app"]["live_send_requirements"][
                "required_evidence"
            ]
        )

        self.assertIn("staged_exact_text_ocr_verified", default_required)
        self.assertIn("outbound_exact_text_ocr_verified", default_required)
        self.assertNotIn("staged_exact_text_verified", default_required)
        self.assertNotIn("outbound_exact_text_verified", default_required)
        self.assertFalse(profile["live_send_requirements"]["visual_only_exact_verification_allowed"])
        self.assertFalse(profile["target_binding"]["visual_only_exact_verification_allowed"])

        self.assertIn("staged_exact_text_verified", mac_required)
        self.assertIn("outbound_exact_text_verified", mac_required)
        self.assertNotIn("staged_exact_text_ocr_verified", mac_required)
        self.assertNotIn("outbound_exact_text_ocr_verified", mac_required)


if __name__ == "__main__":
    unittest.main()

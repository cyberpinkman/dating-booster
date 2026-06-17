import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from dating_boost.cli import main
from dating_boost.core.gui_harness import NativeGuiHarness
from dating_boost.core.live_send_contract import live_send_action_request_block_reason


ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = ROOT / "app_profiles"


class AppAdapterArchitectureTests(unittest.TestCase):
    def test_registry_discovers_all_runtime_profiles(self):
        from dating_boost.apps.registry import host_loop_app_ids, supported_app_ids

        profiles = {
            json.loads(path.read_text(encoding="utf-8"))["app_id"]: json.loads(path.read_text(encoding="utf-8"))
            for path in PROFILE_DIR.glob("*.json")
        }

        self.assertEqual(set(supported_app_ids()), set(profiles))
        self.assertEqual(
            set(host_loop_app_ids()),
            {app_id for app_id, profile in profiles.items() if profile["host_loop_supported"]},
        )

    def test_registry_blocks_real_gui_adapter_creation_under_pytest(self):
        from dating_boost.apps.registry import create_adapter

        with patch.dict("os.environ", {"PYTEST_CURRENT_TEST": "test blocks real gui"}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "real_gui_adapter_disabled_in_tests"):
                create_adapter("wechat")

    def test_registry_allows_injected_runner_under_pytest(self):
        from dating_boost.apps.registry import create_adapter

        with patch.dict("os.environ", {"PYTEST_CURRENT_TEST": "test allows fake runner"}, clear=False):
            adapter = create_adapter("wechat", runner=object())

        self.assertEqual(adapter.manifest.app_id, "wechat")

    def test_each_profile_has_matching_adapter_manifest(self):
        from dating_boost.apps.registry import create_adapter

        for path in PROFILE_DIR.glob("*.json"):
            profile = json.loads(path.read_text(encoding="utf-8"))
            with self.subTest(app_id=profile["app_id"]):
                adapter = create_adapter(profile["app_id"], runner=object())
                manifest = adapter.manifest

                self.assertEqual(manifest.app_id, profile["app_id"])
                self.assertEqual(manifest.display_name, profile["display_name"])
                self.assertEqual(manifest.support_level, profile["support_level"])
                self.assertEqual(manifest.host_loop_supported, profile["host_loop_supported"])
                self.assertEqual(manifest.host_loop_send_modes, tuple(profile["host_loop_send_modes"]))
                self.assertEqual(
                    set(manifest.supported_stage_actions),
                    set(profile["native_gui_harness"]["supported_stage_actions"]),
                )
                self.assertEqual(
                    set(manifest.supported_live_actions),
                    set(profile["native_gui_harness"]["supported_live_actions"]),
                )

    def test_platform_harness_no_longer_exposes_app_specific_public_methods(self):
        app_specific_methods = {
            "launch_tinder",
            "launch_bumble",
            "launch_wechat",
            "observe_tinder_screen",
            "observe_bumble_screen",
            "observe_wechat_screen",
            "run_tinder_action",
            "run_bumble_action",
            "run_tinder_workflow",
            "run_bumble_workflow",
            "send_tinder_message",
            "send_bumble_message",
            "send_wechat_message",
            "stage_wechat_draft",
        }

        self.assertTrue(app_specific_methods.isdisjoint(set(dir(NativeGuiHarness))))

    def test_platform_harness_source_no_longer_owns_app_specific_methods_or_bridge(self):
        source = Path(NativeGuiHarness.__module__.replace(".", "/") + ".py")
        source_path = ROOT / source
        core_source = source_path.read_text(encoding="utf-8")

        self.assertNotIn("_APP_SPECIFIC_NATIVE_GUI_METHODS", core_source)
        self.assertNotIn('self.app_id == "wechat"', core_source)
        self.assertNotIn('self.app_id == "bumble"', core_source)
        for method_name in (
            "doctor_wechat",
            "launch_tinder",
            "launch_bumble",
            "launch_wechat",
            "observe_tinder_screen",
            "observe_bumble_screen",
            "observe_wechat_screen",
            "run_tinder_action",
            "run_bumble_action",
            "send_tinder_message",
            "send_bumble_message",
            "send_wechat_message",
            "stage_wechat_draft",
        ):
            with self.subTest(method=method_name):
                self.assertNotIn(f"    def {method_name}(", core_source)

    def test_live_send_target_binding_policy_load_failure_blocks_supported_live_app(self):
        draft_text = "hi"
        action_request = {
            "schema_version": 1,
            "action_request_id": "act_bumble_send",
            "action": "send_message",
            "app_id": "bumble",
            "match_id": "match_bumble",
            "candidate_key": "bumble_ada",
            "payload_hash": "8f434346648f6b96df89dda901c5176b10a6d83961dd3c1ac88b59b2dc327aa4",
            "precondition_hash": "pre_hash",
            "planner_alignment": "ok",
            "conversation_stage": "rapport_building",
            "conversation_move": "warm_reciprocal_question",
            "autonomous_audit_binding": {
                "binding_type": "autonomous_authorization",
                "authorization_id": "auth_bumble_live",
                "action": "send_message",
                "target_match_id": "match_bumble",
                "payload_hash": "8f434346648f6b96df89dda901c5176b10a6d83961dd3c1ac88b59b2dc327aa4",
                "precondition_hash": "pre_hash",
            },
            "requires_post_action_verification": True,
            "policy": {"allowed": True},
            "target_binding": {
                "required_visible_text": ["Opening Move", "Aa"],
                "target_match_id": "match_bumble",
                "candidate_key": "bumble_ada",
            },
        }
        authorization = {
            "authorization_id": "auth_bumble_live",
            "scope": "send_chat_messages",
            "app_id": "bumble",
            "expires_at": "2099-01-01T00:00:00Z",
            "allowed_actions": ["send_message"],
            "autonomous_send": True,
            "live_send": True,
            "requires_post_action_verification": True,
        }

        with patch("dating_boost.apps.registry.target_binding_policy", side_effect=RuntimeError("profile unavailable")):
            reason = live_send_action_request_block_reason(
                action_request,
                draft_text,
                authorization=authorization,
                app_id="bumble",
                data_dir=None,
            )

        self.assertEqual(reason, "target_binding_policy_unavailable")

    def test_live_send_contract_requires_planner_evidence_before_gui_send(self):
        draft_text = "hi"
        payload_hash = hashlib.sha256(draft_text.encode("utf-8")).hexdigest()
        action_request = {
            "schema_version": 1,
            "action_request_id": "act_bumble_send",
            "action": "send_message",
            "app_id": "bumble",
            "match_id": "match_bumble",
            "candidate_key": "bumble_ada",
            "payload_hash": payload_hash,
            "precondition_hash": "pre_hash",
            "autonomous_audit_binding": {
                "binding_type": "autonomous_authorization",
                "authorization_id": "auth_bumble_live",
                "action": "send_message",
                "target_match_id": "match_bumble",
                "payload_hash": payload_hash,
                "precondition_hash": "pre_hash",
            },
            "requires_post_action_verification": True,
            "policy": {"allowed": True},
            "target_binding": {
                "required_visible_text": ["Ada"],
                "target_match_id": "match_bumble",
                "candidate_key": "bumble_ada",
            },
        }
        authorization = {
            "authorization_id": "auth_bumble_live",
            "scope": "send_chat_messages",
            "app_id": "bumble",
            "expires_at": "2099-01-01T00:00:00Z",
            "allowed_actions": ["send_message"],
            "autonomous_send": True,
            "live_send": True,
            "requires_post_action_verification": True,
        }

        self.assertEqual(
            live_send_action_request_block_reason(
                action_request,
                draft_text,
                authorization=authorization,
                app_id="bumble",
                data_dir=None,
            ),
            "action_request_planner_alignment_required",
        )

        action_request["planner_alignment"] = "not_provided"
        self.assertEqual(
            live_send_action_request_block_reason(
                action_request,
                draft_text,
                authorization=authorization,
                app_id="bumble",
                data_dir=None,
            ),
            "action_request_planner_alignment_required",
        )

        action_request["planner_alignment"] = "ok"
        self.assertEqual(
            live_send_action_request_block_reason(
                action_request,
                draft_text,
                authorization=authorization,
                app_id="bumble",
                data_dir=None,
            ),
            "action_request_planner_context_required",
        )

        action_request["conversation_stage"] = "rapport_building"
        action_request["conversation_move"] = "warm_reciprocal_question"
        self.assertIsNone(
            live_send_action_request_block_reason(
                action_request,
                draft_text,
                authorization=authorization,
                app_id="bumble",
                data_dir=None,
            )
        )

    def test_live_send_contract_accepts_message_sequence_payload_hash(self):
        messages = [
            "慢热联盟可以成立",
            "狼人杀这种局我一般也先观察一会儿",
            "熟了再开麦会比较自然",
        ]
        draft_text = "\n".join(messages)
        payload_hash = hashlib.sha256(
            json.dumps(
                {"payload_format": "message_sequence", "messages": messages},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        action_request = {
            "schema_version": 1,
            "action_request_id": "act_bumble_send_sequence",
            "action": "send_message",
            "app_id": "bumble",
            "match_id": "match_bumble",
            "candidate_key": "bumble_ada",
            "payload_text": draft_text,
            "payload_hash": payload_hash,
            "payload_format": "message_sequence",
            "payload_messages": [
                {
                    "index": index,
                    "text": text,
                    "message_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "character_count": len(text),
                }
                for index, text in enumerate(messages, start=1)
            ],
            "precondition_hash": "pre_hash",
            "planner_alignment": "ok",
            "conversation_stage": "warmup",
            "conversation_move": "low_investment_repair",
            "autonomous_audit_binding": {
                "binding_type": "autonomous_authorization",
                "authorization_id": "auth_bumble_live",
                "action": "send_message",
                "target_match_id": "match_bumble",
                "payload_hash": payload_hash,
                "precondition_hash": "pre_hash",
            },
            "requires_post_action_verification": True,
            "policy": {"allowed": True},
            "target_binding": {
                "required_visible_text": ["Ada"],
                "target_match_id": "match_bumble",
                "candidate_key": "bumble_ada",
            },
        }
        authorization = {
            "authorization_id": "auth_bumble_live",
            "scope": "send_chat_messages",
            "app_id": "bumble",
            "expires_at": "2099-01-01T00:00:00Z",
            "allowed_actions": ["send_message"],
            "autonomous_send": True,
            "live_send": True,
            "requires_post_action_verification": True,
        }

        self.assertIsNone(
            live_send_action_request_block_reason(
                action_request,
                draft_text,
                authorization=authorization,
                app_id="bumble",
                data_dir=None,
            )
        )

    def test_host_loop_required_send_evidence_comes_from_adapter_manifest(self):
        from dating_boost.apps.registry import manifest_for_app
        from dating_boost.host_loop import _managed_gui_send_required_evidence

        self.assertEqual(
            _managed_gui_send_required_evidence("bumble"),
            manifest_for_app("bumble").required_send_evidence,
        )
        self.assertIn("staged_exact_text_ocr_verified", _managed_gui_send_required_evidence("bumble"))
        self.assertIn("staged_exact_text_ocr_verified", _managed_gui_send_required_evidence("tashuo"))
        self.assertIn("outbound_exact_text_ocr_verified", _managed_gui_send_required_evidence("tashuo"))
        self.assertIn("staged_exact_text_verified", _managed_gui_send_required_evidence("tashuo", "mac-ios-app"))
        self.assertIn("outbound_exact_text_verified", _managed_gui_send_required_evidence("tashuo", "mac-ios-app"))
        self.assertNotIn("staged_exact_text_ocr_verified", _managed_gui_send_required_evidence("tashuo", "mac-ios-app"))
        self.assertNotIn("outbound_exact_text_ocr_verified", _managed_gui_send_required_evidence("tashuo", "mac-ios-app"))

    def test_manifest_declares_cli_aliases_for_app_specific_compat_commands(self):
        from dating_boost.apps.registry import manifest_for_app

        self.assertIn("open-profile", manifest_for_app("tinder").cli_aliases)

    def test_tashuo_semantics_live_in_tashuo_adapter_package_not_global_session(self):
        import dating_boost.apps.tashuo.native as tashuo_native
        import dating_boost.apps.tashuo.screen_state as tashuo_screen_state

        native_session_source = (ROOT / "dating_boost" / "apps" / "native_gui_session.py").read_text(encoding="utf-8")
        global_screen_state_source = (ROOT / "dating_boost" / "harness" / "screen_state.py").read_text(encoding="utf-8")

        self.assertTrue(hasattr(tashuo_native, "send_tashuo_message"))
        self.assertTrue(hasattr(tashuo_native, "run_tashuo_workflow"))
        self.assertTrue(hasattr(tashuo_screen_state, "classify_tashuo_screen_text"))
        self.assertNotIn("def send_tashuo_message", native_session_source)
        self.assertNotIn("def _tashuo_action_steps", native_session_source)
        self.assertNotIn("classify_tashuo_screen_text", global_screen_state_source)

    def test_harness_doctor_dispatches_to_adapter_not_session_app_branch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            with redirect_stdout(StringIO()):
                select_exit = main([
                    "runtime",
                    "select",
                    "--data-dir",
                    str(data_dir),
                    "--app-id",
                    "wechat",
                    "--json",
                ])
            calls: dict[str, object] = {}

            class FakeAdapter:
                def doctor(self, *, capture=True, output=None):
                    calls["capture"] = capture
                    calls["output"] = output
                    return {"schema_version": 2, "status": "ok", "app_id": "wechat"}

            with patch("dating_boost.cli.create_adapter", return_value=FakeAdapter()):
                with redirect_stdout(StringIO()) as output:
                    exit_code = main([
                        "harness",
                        "doctor",
                        "--app-id",
                        "wechat",
                        "--data-dir",
                        str(data_dir),
                        "--no-capture",
                        "--json",
                    ])

        self.assertEqual(select_exit, 0)
        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "ok")
        self.assertEqual(calls, {"capture": False, "output": None})

    def test_cli_action_uses_registry_adapter_and_options_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            options_path = Path(temp_dir) / "options.json"
            data_dir = Path(temp_dir) / "data"
            options_path.write_text(json.dumps({"visible_name": "Ada", "y_ratio": 0.71}), encoding="utf-8")
            with redirect_stdout(StringIO()):
                select_exit = main([
                    "runtime",
                    "select",
                    "--data-dir",
                    str(data_dir),
                    "--app-id",
                    "tinder",
                    "--json",
                ])
            calls: dict[str, object] = {}

            class FakeAdapter:
                def run_action(self, action, *, dry_run=False, output_dir=None, **options):
                    calls["action"] = action
                    calls["dry_run"] = dry_run
                    calls["output_dir"] = output_dir
                    calls["options"] = options
                    return {"schema_version": 2, "status": "ok", "app_id": "tinder", "action": action}

            with patch("dating_boost.cli.create_adapter", return_value=FakeAdapter()):
                with redirect_stdout(StringIO()):
                    exit_code = main([
                        "harness",
                        "tinder",
                        "action",
                        "open-conversation",
                        "--options-json",
                        str(options_path),
                        "--data-dir",
                        str(data_dir),
                        "--dry-run",
                        "--json",
                    ])

        self.assertEqual(select_exit, 0)
        self.assertEqual(exit_code, 0)
        self.assertEqual(calls["action"], "open-conversation")
        self.assertTrue(calls["dry_run"])
        self.assertEqual(calls["options"], {"visible_name": "Ada", "y_ratio": 0.71})

    def test_cli_harness_unknown_app_returns_structured_block(self):
        with redirect_stdout(StringIO()) as output:
            exit_code = main(["harness", "hinge", "observe", "--json"])

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "unsupported_native_harness_for_app")
        self.assertEqual(payload["app_id"], "hinge")


if __name__ == "__main__":
    unittest.main()

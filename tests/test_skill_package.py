import json
import tempfile
import tomllib
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from dating_boost import __version__
from dating_boost.cli import main


SKILL_DIR = Path("skills/dating-booster-codex")


class SkillPackageTests(unittest.TestCase):
    def test_skill_package_metadata_is_compatible_with_capabilities(self):
        package_path = SKILL_DIR / "skill-package.json"
        metadata = json.loads(package_path.read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as temp_dir:
            output = StringIO()
            with redirect_stdout(output):
                exit_code = main(["capabilities", "--json", "--data-dir", temp_dir])

        capabilities = json.loads(output.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(metadata["package_name"], "dating-booster-codex-skill")
        self.assertEqual(metadata["target_host"], "codex")
        self.assertEqual(metadata["package_version"], __version__)
        self.assertEqual(metadata["dating_boost_min_version"], __version__)
        self.assertEqual(metadata["source_repo"], "cyberpinkman/dating-booster")
        self.assertEqual(metadata["skill_path"], "skills/dating-booster-codex")
        self.assertEqual(metadata["source_ref"], _expected_source_ref(__version__))
        self.assertEqual(metadata["source_spec_commit"], _expected_source_ref(__version__))
        if ".dev" not in __version__:
            self.assertRegex(metadata["source_ref"], r"^v\d+\.\d+\.\d+(?:-rc\.\d+)?$")
        self.assertEqual(metadata["cli_command"], "dating-boost")
        self.assertEqual(metadata["host_loop_command"], "dating-boost-host-loop")
        self.assertEqual(metadata["bootstrap_script"], "scripts/bootstrap_cli.py")
        self.assertEqual(metadata["doctor_script"], "scripts/doctor.py")
        self.assertLessEqual(_version_tuple(metadata["dating_boost_min_version"]), _version_tuple(__version__))
        self.assertTrue(set(metadata["required_commands"]).issubset(set(capabilities["supported_commands"])))
        self.assertEqual(metadata["required_schema_versions"]["reply_draft"], 2)
        self.assertEqual(metadata["required_schema_versions"]["user_disclosure_profile"], 1)
        self.assertEqual(metadata["required_schema_versions"]["user_readiness"], 1)
        self.assertEqual(metadata["required_schema_versions"]["workflow_result"], 1)
        self.assertEqual(metadata["required_schema_versions"]["automation_session"], 1)
        self.assertEqual(metadata["required_schema_versions"]["appointment_ledger"], 1)
        self.assertEqual(metadata["required_schema_versions"]["progress_report"], 1)
        self.assertEqual(metadata["required_schema_versions"]["planner_assessment"], 1)
        self.assertEqual(metadata["required_schema_versions"]["goal_plan"], 1)
        self.assertEqual(metadata["required_schema_versions"]["planner_recommendation"], 1)
        self.assertEqual(metadata["required_schema_versions"]["data_store"], 2)
        self.assertEqual(metadata["required_schema_versions"]["migration"], 1)
        self.assertEqual(metadata["required_schema_versions"]["automation_lock"], 1)
        self.assertEqual(metadata["required_schema_versions"]["confirmation"], 1)
        self.assertEqual(metadata["required_schema_versions"]["production_smoke"], 1)
        self.assertEqual(metadata["required_schema_versions"]["backup_recovery_key"], 1)
        for command in ("planner update", "planner get", "planner recommend", "planner event-log"):
            self.assertIn(command, metadata["required_commands"])
        for schema_name, schema_version in metadata["required_schema_versions"].items():
            self.assertEqual(capabilities["schema_versions"][schema_name], schema_version)
        for spec_path in metadata["source_specs"]:
            self.assertTrue(Path(spec_path).exists(), spec_path)
        source_specs_text = "\n".join(metadata["source_specs"])
        for source_spec_keyword in (
            "agent-native-launch-strategy",
            "product-architecture-blueprint",
            "intelligence-layer-design",
            "automation-phase-b",
            "goal-oriented-conversation-agent",
            "self-disclosure-low-investment",
            "tinder-host-loop",
        ):
            self.assertIn(source_spec_keyword, source_specs_text)
        for reference_path in metadata["references"]:
            self.assertTrue((SKILL_DIR / reference_path).exists(), reference_path)
        self.assertIn("references/drafting-framework.md", metadata["references"])
        self.assertIn("references/naturalness-checklist.md", metadata["references"])
        self.assertIn("references/host-loop.md", metadata["references"])
        self.assertTrue((SKILL_DIR / metadata["bootstrap_script"]).exists())
        self.assertTrue((SKILL_DIR / metadata["doctor_script"]).exists())

    def test_host_loop_supervisor_is_exposed_as_installable_console_command(self):
        pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
        scripts = pyproject["project"]["scripts"]

        self.assertEqual(scripts["dating-boost"], "dating_boost.cli:main")
        self.assertEqual(scripts["dating-boost-host-loop"], "dating_boost.host_loop:main")

    def test_skill_markdown_contains_required_operational_guards(self):
        skill_text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8").lower()

        self.assertIn("dating-boost capabilities --json --data-dir", skill_text)
        self.assertIn("skill-package.json", skill_text)
        self.assertIn("dating_boost_min_version", skill_text)
        self.assertIn("required_schema_versions", skill_text)
        self.assertIn("required_commands", skill_text)
        self.assertIn("source_spec_commit", skill_text)
        self.assertIn("warning", skill_text)
        self.assertIn("stop", skill_text)
        self.assertIn("privacy", skill_text)
        self.assertIn("visible dating app content", skill_text)
        self.assertIn("high-risk", skill_text)
        self.assertIn("post-action verification", skill_text)
        self.assertIn("record-result", skill_text)
        self.assertIn("automation session", skill_text)
        self.assertIn("planner_assessment", skill_text)
        self.assertIn("goal-oriented", skill_text)
        self.assertIn("doctor.py", skill_text)
        self.assertIn("bootstrap_cli.py", skill_text)
        self.assertLess(skill_text.index("doctor.py"), skill_text.index("visible dating app content"))
        self.assertIn("host agent", skill_text)
        self.assertIn("drafting-framework.md", skill_text)
        self.assertIn("naturalness-checklist.md", skill_text)
        self.assertIn("long-press", skill_text)
        self.assertIn("paste", skill_text)
        self.assertIn("verify staged text", skill_text)
        self.assertIn("support session start", skill_text)
        self.assertIn("support bundle", skill_text)
        self.assertIn("position drift", skill_text)
        self.assertIn("reopen the chat thread", skill_text)
        self.assertIn("foreground app copy", skill_text)
        self.assertIn("user readiness", skill_text)
        self.assertIn("needs_user_profile", skill_text)
        self.assertIn("low_investment_repair", skill_text)
        self.assertIn("harness wechat stage-draft --text-file", skill_text)
        self.assertIn("harness wechat send-message --text-file", skill_text)
        self.assertIn("dismiss-subscription-paywall", skill_text)
        self.assertIn("subscription purchase", skill_text)
        self.assertIn("plan selection is never an agent action", skill_text)
        self.assertNotIn("harness wechat stage-draft --text ", skill_text)

    def test_agent_facing_docs_do_not_present_handcrafted_live_send_requests(self):
        docs = [
            Path("AGENTS.md"),
            Path("skills/dating-booster-codex/SKILL.md"),
            Path("skills/dating-booster-codex/INSTALL.md"),
            Path("skills/dating-booster-codex/references/workflows.md"),
            Path("skills/dating-booster-codex/references/host-loop.md"),
            Path("skills/dating-booster-codex/references/production-stage-runbook.md"),
            Path("agent_adapters/claude-code/skills/dating-booster/SKILL.md"),
            Path("agent_adapters/openclaw/skills/dating-booster/SKILL.md"),
            Path("agent_adapters/shared/references/workflows.md"),
            Path("dating_boost/resources/agent_adapters/codex/dating-booster-codex/SKILL.md"),
            Path("dating_boost/resources/agent_adapters/codex/dating-booster-codex/INSTALL.md"),
            Path("dating_boost/resources/agent_adapters/codex/dating-booster-codex/references/workflows.md"),
            Path("dating_boost/resources/agent_adapters/codex/dating-booster-codex/references/host-loop.md"),
            Path("dating_boost/resources/agent_adapters/codex/dating-booster-codex/references/production-stage-runbook.md"),
            Path("dating_boost/resources/agent_adapters/claude-code/skills/dating-booster/SKILL.md"),
            Path("dating_boost/resources/agent_adapters/openclaw/skills/dating-booster/SKILL.md"),
            Path("dating_boost/resources/agent_adapters/shared/references/workflows.md"),
        ]
        forbidden = (
            "--action-request action_request.json",
            "--action-request action-request.json",
            "cat > /tmp",
            "harness <app> send-message --text-file ... --data-dir ... --authorization ... --action-request",
            "execute `send_message` only through\ngated app-specific `harness <app> send-message` paths",
            "execute `send_message` only through gated app-specific `harness <app> send-message` paths",
            "managed send requires `harness <app> send-message",
            "fully managed sending also requires `--managed-gui-send` or the explicit `harness",
        )

        for path in docs:
            text = path.read_text(encoding="utf-8").lower()
            with self.subTest(path=str(path)):
                self.assertIn("do not handcraft", text)
                self.assertIn("executor-internal", text)
                for phrase in forbidden:
                    self.assertNotIn(phrase, text)

    def test_skill_reference_files_describe_reusable_workflows_and_contracts(self):
        workflows_text = (SKILL_DIR / "references" / "workflows.md").read_text(encoding="utf-8").lower()
        contracts_text = (SKILL_DIR / "references" / "contracts.md").read_text(encoding="utf-8").lower()
        drafting_text = (SKILL_DIR / "references" / "drafting-framework.md").read_text(
            encoding="utf-8"
        ).lower()
        checklist_text = (SKILL_DIR / "references" / "naturalness-checklist.md").read_text(
            encoding="utf-8"
        ).lower()
        host_loop_text = (SKILL_DIR / "references" / "host-loop.md").read_text(encoding="utf-8").lower()

        for workflow_name in ("draft", "profile refresh", "send", "feedback"):
            self.assertIn(workflow_name, workflows_text)
        for harness_phrase in (
            "self-profile-read",
            "chat-read-match-profile",
            "new-match-open",
            "new-match-read-profile",
            "profile-photo-next",
            "open-conversation",
            "return-to-chats",
            "open-thread-profile",
            "expand-visible-profile-section",
        ):
            self.assertIn(harness_phrase, workflows_text)
        for command in (
            "memory ingest-observation",
            "memory update-match",
            "context build",
            "policy check-draft",
            "policy check-action",
            "action record-result",
            "feedback record",
            "user interview template",
            "user ingest-profile",
            "user ingest-interview",
            "user disclosure-profile",
            "user readiness",
            "workflow draft",
            "automation session start",
            "automation session step",
            "automation session stop",
            "automation report latest",
            "automation scan template",
            "automation scan validate",
            "automation scan normalize",
            "automation scan assemble",
            "planner update",
            "planner recommend",
            "skill doctor",
            "operator session start",
            "operator next",
            "operator ingest-observation",
            "operator record-action-result",
            "operator stop",
            "operator report latest",
            "dating-boost-host-loop",
            "data doctor",
            "data migrate",
            "data export",
            "data delete",
            "confirmation create",
            "confirmation confirm",
            "confirmation validate",
            "support session start",
            "support session stop",
            "support record-event",
            "support bundle",
            "harness doctor",
            "harness screenshot",
            "harness tinder launch",
            "harness tinder open-profile",
            "harness tinder observe",
            "harness tinder action",
            "harness tinder action dismiss-subscription-paywall",
            "harness tinder action dismiss-feedback-survey",
            "harness tinder workflow",
            "harness tinder send-message",
            "harness bumble launch",
            "harness bumble observe",
            "harness bumble action",
            "harness bumble workflow",
            "harness tashuo stage-draft",
            "harness tashuo send-message",
            "harness wechat launch",
            "harness wechat observe",
            "harness wechat stage-draft",
            "harness wechat send-message",
        ):
            self.assertTrue(command in workflows_text or command in host_loop_text, command)
        for phrase in (
            "iphone mirroring",
            "long-press",
            "paste",
            "verify staged text",
            "do not send",
            "position drift",
            "reopen the chat thread",
            "foreground app copy",
            "--text-file",
            "shell history",
            "result_status",
            "subscription_paywall",
            "do not ask the user whether to subscribe",
            "feedback_survey",
            "rating_submitted",
            "target-binding",
        ):
            self.assertIn(phrase, workflows_text)

        for field_name in (
            "observation_id",
            "match_identity_hints",
            "profile_observation",
            "conversation_observation",
            "latest_inbound_messages",
            "best_reply",
            "situation_read",
            "conversation_move",
            "hook_source",
            "naturalness_notes",
            "followup_if_match_replies",
            "payload_hash",
            "result_status",
            "evidence",
            "scan_batch",
            "action_request_id",
            "machine_report",
            "doctor",
            "message_list_snapshot",
            "thread_observations",
            "planner_assessment",
            "goal_plan",
            "planner_recommendation",
            "conversation_scores",
            "topic_lifecycle",
            "soft_invite_allowed",
            "staged_verification",
            "message_list_observation.template.json",
        ):
            self.assertIn(field_name, contracts_text)
        for phrase in (
            "tinder host loop",
            "--send-mode stage",
            "--send-mode live",
            "staged_verification.json",
            "action_result.json",
            "do not click send",
            "re-locate the current input box",
        ):
            self.assertIn(phrase, host_loop_text)
        for phrase in (
            "对方投入度",
            "最后一句",
            "latest_inbound_messages",
            "turn boundary",
            "after the user's latest outbound",
            "old visible messages are background",
            "连续输出",
            "未知细节",
            "question is optional",
            "answer_or_riff",
            "take_the_lead",
            "do not force a question",
            "对方把选择权交给你",
            "不要继续反问",
            "一句为主",
            "topic_saturation",
            "soft_invite_probe",
            "next_milestone",
            "bridge_topic",
            "给/问/接/转/停",
            "low_investment_repair",
            "self-disclosure",
        ):
            self.assertIn(phrase, drafting_text)
        self.assertNotIn("deepen_hook", drafting_text)
        self.assertNotIn("bridge_from_latest", drafting_text)
        self.assertIn("deepen_current", drafting_text)
        self.assertIn("bridge_topic", drafting_text)
        for phrase in (
            "偏 a 还是 b",
            "a 还是 b 还是 c",
            "标签堆叠",
            "抽象词",
            "已知标签",
            "强行提问",
            "继续反问",
            "都行",
            "看情况",
        ):
            self.assertIn(phrase, checklist_text)

    def test_tinder_new_match_workflows_are_documented_for_agents(self):
        docs = {
            "agents": Path("AGENTS.md").read_text(encoding="utf-8").lower(),
            "skill": (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8").lower(),
            "workflows": (SKILL_DIR / "references" / "workflows.md").read_text(encoding="utf-8").lower(),
            "host_loop": (SKILL_DIR / "references" / "host-loop.md").read_text(encoding="utf-8").lower(),
            "runbook": (SKILL_DIR / "references" / "production-stage-runbook.md").read_text(encoding="utf-8").lower(),
        }

        for name, text in docs.items():
            self.assertIn("new-match-open", text, name)
            self.assertIn("new-match-read-profile", text, name)
            self.assertNotIn("chat-read-match-profile --dry-run --carousel-swipes", text, name)
            self.assertNotIn("chat-read-match-profile --carousel-swipes", text, name)

    def test_managed_session_docs_require_host_loop_resume_after_host_work(self):
        docs = {
            "agents": Path("AGENTS.md").read_text(encoding="utf-8").lower(),
            "codex_skill": (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8").lower(),
            "codex_workflows": (SKILL_DIR / "references" / "workflows.md").read_text(encoding="utf-8").lower(),
            "claude_skill": Path("agent_adapters/claude-code/skills/dating-booster/SKILL.md").read_text(
                encoding="utf-8"
            ).lower(),
            "openclaw_skill": Path("agent_adapters/openclaw/skills/dating-booster/SKILL.md").read_text(
                encoding="utf-8"
            ).lower(),
            "shared_workflows": Path("agent_adapters/shared/references/workflows.md").read_text(
                encoding="utf-8"
            ).lower(),
        }

        for name, text in docs.items():
            self.assertIn("managed-session run --wait", text, name)
            self.assertIn("dating-boost-host-loop resume", text, name)
            self.assertIn("managed-session run --wait", text.split("dating-boost-host-loop resume", 1)[-1], name)

    def test_tinder_app_profile_exposes_split_new_match_harness_contract(self):
        profile = json.loads(Path("app_profiles/tinder.json").read_text(encoding="utf-8"))
        harness = profile["native_gui_harness"]

        self.assertIn("new-match-open", harness["high_level_workflows"])
        self.assertIn("new-match-read-profile", harness["high_level_workflows"])
        self.assertIn("return_to_chats", harness["supported_stage_actions"])
        self.assertEqual(
            harness["launch_navigation"]["steps"],
            ["open_iphone_home_screen", "open_ios_spotlight", "type_app_name_verified", "tap_search_result_icon"],
        )
        self.assertIn("new_matches_carousel_wheel_left", harness["chat_navigation"])
        self.assertEqual(harness["chat_navigation"]["new_match_card_base_tap_ratio"], {"x": 0.42, "y": 0.30})
        self.assertEqual(harness["chat_navigation"]["thread_profile_avatar_tap_ratio"], {"x": 0.50, "y": 0.14})

    def test_naturalness_check_is_internal_by_default(self):
        skill_text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8").lower()
        workflows_text = (SKILL_DIR / "references" / "workflows.md").read_text(encoding="utf-8").lower()
        checklist_text = (SKILL_DIR / "references" / "naturalness-checklist.md").read_text(
            encoding="utf-8"
        ).lower()

        for text in (skill_text, workflows_text, checklist_text):
            self.assertIn("internal", text)
            self.assertIn("do not show", text)
            self.assertIn("explicitly asks", text)
            self.assertIn("debug", text)

        self.assertIn("show only the final draft", skill_text)
        self.assertIn("do not list checklist results", workflows_text)
        self.assertIn("not a default user-facing output format", checklist_text)

    def test_human_report_contract_keeps_match_identity_visible(self):
        contracts_text = (SKILL_DIR / "references" / "contracts.md").read_text(encoding="utf-8").lower()

        self.assertIn("user-facing markdown report", contracts_text)
        self.assertIn("match identifiers visible", contracts_text)
        self.assertIn("should not hide who the agent", contracts_text)
        self.assertIn("talked to by default", contracts_text)
        self.assertNotIn("show a redacted markdown report", contracts_text)


def _version_tuple(version: str) -> tuple[int, ...]:
    values: list[int] = []
    for part in version.replace("-rc.", ".").split("."):
        digits = "".join(character for character in part if character.isdigit())
        values.append(int(digits or "0"))
    return tuple(values)


def _expected_source_ref(version: str) -> str:
    return "main" if ".dev" in version else f"v{version}"


if __name__ == "__main__":
    unittest.main()

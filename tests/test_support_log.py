import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from contextlib import contextmanager, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from dating_boost.cli import main
from dating_boost.core.production_store import ProductionDataStore


@contextmanager
def _patch_cli_adapter():
    with patch("dating_boost.cli.create_adapter") as adapter_factory:
        adapter = adapter_factory.return_value
        adapter.stage_draft.side_effect = adapter.stage_wechat_draft
        adapter.observe.side_effect = adapter.observe_tinder_screen
        yield adapter_factory


class SupportLogTests(unittest.TestCase):
    def setUp(self):
        self._env = patch.dict(
            os.environ,
            {
                "DATING_BOOST_NOW": "2026-06-04T00:00:00Z",
                "DATING_BOOST_KEY_PROVIDER": "local",
            },
        )
        self._env.start()

    def tearDown(self):
        self._env.stop()

    def test_capabilities_expose_support_log_and_evidence_vault(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            exit_code, payload = self._run(["capabilities", "--data-dir", temp_dir, "--json"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["schema_versions"]["support_log"], 1)
        self.assertEqual(payload["schema_versions"]["support_evidence"], 1)
        self.assertIn("support session start", payload["supported_commands"])
        self.assertIn("support session stop", payload["supported_commands"])
        self.assertIn("support record-event", payload["supported_commands"])
        self.assertIn("support bundle", payload["supported_commands"])
        self.assertTrue(payload["diagnostic_capabilities"]["support_log"])
        self.assertTrue(payload["diagnostic_capabilities"]["encrypted_evidence_vault"])
        self.assertTrue(payload["diagnostic_capabilities"]["clipboard_fingerprint"])

    def test_support_bundle_strict_redacts_sensitive_evidence_but_keeps_topic_provenance(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            strict_bundle = root / "support-strict.zip"
            sensitive_bundle = root / "support-sensitive.zip"
            preference_path = root / "preference.json"
            preference_sensitive_path = root / "preference-sensitive.json"
            draft_path = root / "draft-event.json"
            draft_sensitive_path = root / "draft-sensitive.json"
            clipboard_path = root / "clipboard-event.json"
            clipboard_sensitive_path = root / "clipboard-sensitive.json"
            preference_path.write_text(
                json.dumps({"allowed_topics": ["dogs"], "source": "chat_preference"}, ensure_ascii=False),
                encoding="utf-8",
            )
            preference_sensitive_path.write_text(
                json.dumps({"preference_text": "可以聊小狗相关的内容"}, ensure_ascii=False),
                encoding="utf-8",
            )
            draft_path.write_text(
                json.dumps({"draft_id": "draft_1", "target_match_id": "match_iris"}, ensure_ascii=False),
                encoding="utf-8",
            )
            draft_sensitive_path.write_text(
                json.dumps({"draft_text": "我最近在做AI内测项目，工作节奏有点满"}, ensure_ascii=False),
                encoding="utf-8",
            )
            clipboard_path.write_text(
                json.dumps({"clipboard_role": "before_stage"}, ensure_ascii=False),
                encoding="utf-8",
            )
            clipboard_sensitive_path.write_text(
                json.dumps({"clipboard_text": "公司项目排期今晚要改"}, ensure_ascii=False),
                encoding="utf-8",
            )

            start_exit, start_payload = self._run([
                "support",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--host",
                "claude-code",
                "--app-id",
                "tinder",
                "--json",
            ])
            session_id = start_payload["session_id"]
            self._run([
                "support",
                "record-event",
                "--data-dir",
                str(data_dir),
                "--session-id",
                session_id,
                "--event-type",
                "preference_ingested",
                "--payload",
                str(preference_path),
                "--sensitive",
                str(preference_sensitive_path),
                "--sensitive-kind",
                "preference",
                "--json",
            ])
            self._run([
                "support",
                "record-event",
                "--data-dir",
                str(data_dir),
                "--session-id",
                session_id,
                "--event-type",
                "draft_generated",
                "--payload",
                str(draft_path),
                "--sensitive",
                str(draft_sensitive_path),
                "--sensitive-kind",
                "draft",
                "--json",
            ])
            self._run([
                "support",
                "record-event",
                "--data-dir",
                str(data_dir),
                "--session-id",
                session_id,
                "--event-type",
                "clipboard_before_stage",
                "--payload",
                str(clipboard_path),
                "--sensitive",
                str(clipboard_sensitive_path),
                "--sensitive-kind",
                "clipboard_before",
                "--json",
            ])
            strict_exit, strict_payload = self._run([
                "support",
                "bundle",
                "--data-dir",
                str(data_dir),
                "--session-id",
                session_id,
                "--output",
                str(strict_bundle),
                "--redaction",
                "strict",
                "--json",
            ])
            sensitive_exit, sensitive_payload = self._run([
                "support",
                "bundle",
                "--data-dir",
                str(data_dir),
                "--session-id",
                session_id,
                "--output",
                str(sensitive_bundle),
                "--redaction",
                "full-with-consent",
                "--include-sensitive",
                "draft,clipboard_before",
                "--confirm",
                f"export-sensitive:{session_id}",
                "--json",
            ])
            strict_names, strict_joined = self._read_zip(strict_bundle)
            sensitive_names, sensitive_joined = self._read_zip(sensitive_bundle)
            database_bytes = (data_dir / "dating_boost.sqlite3").read_bytes()

        self.assertEqual(start_exit, 0)
        self.assertEqual(strict_exit, 0)
        self.assertEqual(strict_payload["redaction"], "strict")
        self.assertIn("manifest.json", strict_names)
        self.assertIn("support/events.redacted.jsonl", strict_names)
        self.assertIn("support/evidence_manifest.redacted.json", strict_names)
        self.assertIn(b"draft_generated", strict_joined)
        self.assertIn(b"work", strict_joined)
        self.assertIn(b"dogs", strict_joined)
        self.assertIn(b"clipboard_before", strict_joined)
        self.assertNotIn("可以聊小狗".encode("utf-8"), strict_joined)
        self.assertNotIn("AI内测项目".encode("utf-8"), strict_joined)
        self.assertNotIn("公司项目排期".encode("utf-8"), strict_joined)
        self.assertNotIn("AI内测项目".encode("utf-8"), database_bytes)

        self.assertEqual(sensitive_exit, 0)
        self.assertEqual(sensitive_payload["redaction"], "full-with-consent")
        self.assertIn("support/sensitive/draft.json", sensitive_names)
        self.assertIn("support/sensitive/clipboard_before.json", sensitive_names)
        self.assertNotIn("可以聊小狗".encode("utf-8"), sensitive_joined)
        self.assertIn("AI内测项目".encode("utf-8"), sensitive_joined)
        self.assertIn("公司项目排期".encode("utf-8"), sensitive_joined)

    def test_active_support_session_auto_logs_cli_command_boundaries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            bundle_path = root / "support.zip"
            _, start_payload = self._run([
                "support",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--host",
                "codex",
                "--app-id",
                "tinder",
                "--json",
            ])
            session_id = start_payload["session_id"]

            capabilities_exit, _ = self._run(["capabilities", f"--data-dir={data_dir}", "--json"])
            stop_exit, stop_payload = self._run([
                "support",
                "session",
                "stop",
                "--data-dir",
                str(data_dir),
                "--session-id",
                session_id,
                "--json",
            ])
            bundle_exit, _ = self._run([
                "support",
                "bundle",
                "--data-dir",
                str(data_dir),
                "--session-id",
                session_id,
                "--output",
                str(bundle_path),
                "--redaction",
                "strict",
                "--json",
            ])
            _names, joined = self._read_zip(bundle_path)

        self.assertEqual(capabilities_exit, 0)
        self.assertEqual(stop_exit, 0)
        self.assertEqual(stop_payload["status"], "stopped")
        self.assertEqual(bundle_exit, 0)
        self.assertIn(b"command_started", joined)
        self.assertIn(b"command_finished", joined)
        self.assertIn(b"capabilities", joined)
        self.assertIn(b"--data-dir=[redacted]", joined)
        self.assertNotIn(str(data_dir).encode("utf-8"), joined)
        self.assertIn(b"exit_code", joined)

    def test_support_session_blocks_nonempty_sqlite_that_still_requires_migration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            ProductionDataStore(data_dir).upsert_document(
                "support-test/existing.json",
                {"schema_version": 1, "value": "keep"},
            )

            exit_code, payload = self._run([
                "support",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--host",
                "codex",
                "--app-id",
                "tinder",
                "--json",
            ])

        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "data_migration_required_before_support_logging")

    def test_strict_bundle_redacts_unknown_string_payload_keys_by_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            payload_path = root / "payload.json"
            bundle_path = root / "support.zip"
            payload_path.write_text(
                json.dumps({"reply": "我最近在做AI内测项目，工作节奏有点满"}, ensure_ascii=False),
                encoding="utf-8",
            )
            _, start_payload = self._run([
                "support",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--host",
                "codex",
                "--app-id",
                "tinder",
                "--json",
            ])
            session_id = start_payload["session_id"]
            record_exit, _ = self._run([
                "support",
                "record-event",
                "--data-dir",
                str(data_dir),
                "--session-id",
                session_id,
                "--event-type",
                "draft_generated",
                "--payload",
                str(payload_path),
                "--json",
            ])
            bundle_exit, _ = self._run([
                "support",
                "bundle",
                "--data-dir",
                str(data_dir),
                "--session-id",
                session_id,
                "--output",
                str(bundle_path),
                "--redaction",
                "strict",
                "--json",
            ])
            _names, joined = self._read_zip(bundle_path)

        self.assertEqual(record_exit, 0)
        self.assertEqual(bundle_exit, 0)
        self.assertIn(b"reply_hash", joined)
        self.assertIn(b"work", joined)
        self.assertNotIn("AI内测项目".encode("utf-8"), joined)

    def test_policy_check_draft_records_sensitive_draft_and_topic_manifest_when_support_session_active(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            context_path = root / "context.json"
            draft_path = root / "draft.json"
            strict_bundle = root / "support-strict.zip"
            sensitive_bundle = root / "support-sensitive.zip"
            context_path.write_text(
                json.dumps(
                    {
                        "context_pack": {
                            "schema_version": 1,
                            "match_id": "match_iris",
                            "items": [
                                {
                                    "kind": "preference",
                                    "content": {"allowed_topics": ["dogs"]},
                                    "source_id": "pref_dogs",
                                }
                            ],
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            draft_path.write_text(
                json.dumps(_full_draft("我最近在做AI内测项目，工作节奏有点满"), ensure_ascii=False),
                encoding="utf-8",
            )
            _, start_payload = self._run([
                "support",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--host",
                "claude-code",
                "--app-id",
                "tinder",
                "--json",
            ])
            session_id = start_payload["session_id"]

            policy_exit, policy_payload = self._run([
                "policy",
                "check-draft",
                "--data-dir",
                str(data_dir),
                "--input",
                str(draft_path),
                "--context",
                str(context_path),
            ])
            strict_exit, _ = self._run([
                "support",
                "bundle",
                "--data-dir",
                str(data_dir),
                "--session-id",
                session_id,
                "--output",
                str(strict_bundle),
                "--redaction",
                "strict",
                "--json",
            ])
            sensitive_exit, _ = self._run([
                "support",
                "bundle",
                "--data-dir",
                str(data_dir),
                "--session-id",
                session_id,
                "--output",
                str(sensitive_bundle),
                "--redaction",
                "full-with-consent",
                "--include-sensitive",
                "draft",
                "--confirm",
                f"export-sensitive:{session_id}",
                "--json",
            ])
            _strict_names, strict_joined = self._read_zip(strict_bundle)
            _sensitive_names, sensitive_joined = self._read_zip(sensitive_bundle)

        self.assertIn(policy_exit, {0, 2})
        self.assertIn("policy", policy_payload)
        self.assertEqual(strict_exit, 0)
        self.assertIn(b"policy_check_draft", strict_joined)
        self.assertIn(b"draft_generated", strict_joined)
        self.assertIn(b"context_source_manifest", strict_joined)
        self.assertIn(b"dogs", strict_joined)
        self.assertIn(b"work", strict_joined)
        self.assertNotIn("AI内测项目".encode("utf-8"), strict_joined)
        self.assertEqual(sensitive_exit, 0)
        self.assertIn("AI内测项目".encode("utf-8"), sensitive_joined)

    def test_harness_stage_records_redacted_action_and_sensitive_draft_when_support_session_active(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            draft_path = root / "wechat-draft.txt"
            strict_bundle = root / "support-strict.zip"
            sensitive_bundle = root / "support-sensitive.zip"
            draft_path.write_text("我最近在做AI内测项目，工作节奏有点满", encoding="utf-8")
            _, start_payload = self._run([
                "support",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--host",
                "claude-code",
                "--app-id",
                "wechat",
                "--json",
            ])
            session_id = start_payload["session_id"]

            with _patch_cli_adapter() as harness_class:
                harness_class.return_value.stage_wechat_draft.return_value = {
                    "schema_version": 2,
                    "status": "ok",
                    "app_id": "wechat",
                    "action": "stage_draft",
                    "mode": "dry_run",
                    "draft_fingerprint": "fixture_hash",
                    "draft_character_count": 20,
                    "previous_clipboard_fingerprint": "clipboard_hash",
                    "previous_clipboard_character_count": 6,
                    "previous_clipboard_topic_labels": ["dogs"],
                    "clipboard_restored": True,
                }
                stage_exit, stage_payload = self._run([
                    "harness",
                    "wechat",
                    "stage-draft",
                    "--data-dir",
                    str(data_dir),
                    "--text-file",
                    str(draft_path),
                    "--dry-run",
                    "--json",
                ])

            strict_exit, _ = self._run([
                "support",
                "bundle",
                "--data-dir",
                str(data_dir),
                "--session-id",
                session_id,
                "--output",
                str(strict_bundle),
                "--redaction",
                "strict",
                "--json",
            ])
            sensitive_exit, _ = self._run([
                "support",
                "bundle",
                "--data-dir",
                str(data_dir),
                "--session-id",
                session_id,
                "--output",
                str(sensitive_bundle),
                "--redaction",
                "full-with-consent",
                "--include-sensitive",
                "draft",
                "--confirm",
                f"export-sensitive:{session_id}",
                "--json",
            ])
            _strict_names, strict_joined = self._read_zip(strict_bundle)
            _sensitive_names, sensitive_joined = self._read_zip(sensitive_bundle)

        self.assertEqual(stage_exit, 0)
        self.assertEqual(stage_payload["status"], "ok")
        self.assertEqual(strict_exit, 0)
        self.assertIn(b"harness_wechat_stage_draft", strict_joined)
        self.assertIn(b"draft_topic_labels", strict_joined)
        self.assertIn(b"work", strict_joined)
        self.assertIn(b"dogs", strict_joined)
        self.assertIn(b"previous_clipboard_fingerprint", strict_joined)
        self.assertNotIn("AI内测项目".encode("utf-8"), strict_joined)
        self.assertEqual(sensitive_exit, 0)
        self.assertIn("AI内测项目".encode("utf-8"), sensitive_joined)

    def test_harness_observe_records_result_when_data_dir_is_supplied(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            bundle_path = root / "support.zip"
            _, start_payload = self._run([
                "support",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--host",
                "codex",
                "--app-id",
                "tinder",
                "--json",
            ])
            session_id = start_payload["session_id"]

            with _patch_cli_adapter() as harness_class:
                harness_class.return_value.observe_tinder_screen.return_value = {
                    "schema_version": 2,
                    "status": "ok",
                    "app_id": "tinder",
                    "action": "observe",
                    "screen_state": "tinder_messages",
                    "layout_hints": {"page": "chats"},
                }
                observe_exit, observe_payload = self._run([
                    "harness",
                    "tinder",
                    "observe",
                    "--data-dir",
                    str(data_dir),
                    "--json",
                ])

            bundle_exit, _ = self._run([
                "support",
                "bundle",
                "--data-dir",
                str(data_dir),
                "--session-id",
                session_id,
                "--output",
                str(bundle_path),
                "--redaction",
                "strict",
                "--json",
            ])
            _names, joined = self._read_zip(bundle_path)

        self.assertEqual(observe_exit, 0)
        self.assertEqual(observe_payload["status"], "ok")
        self.assertEqual(bundle_exit, 0)
        self.assertIn(b"harness_tinder_observe", joined)
        self.assertIn(b"tinder_messages", joined)
        self.assertIn(b"chats", joined)

    def test_host_loop_records_timeline_and_command_boundaries_when_support_session_active(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            bundle_path = root / "support.zip"
            fixture_dir = Path("tests/fixtures/host_loop/tinder")
            _, start_payload = self._run([
                "support",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--host",
                "codex",
                "--app-id",
                "tinder",
                "--json",
            ])
            session_id = start_payload["session_id"]

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "dating_boost.host_loop",
                    "run",
                    "--fixture-host",
                    str(fixture_dir),
                    "--data-dir",
                    str(data_dir),
                    "--work-dir",
                    str(work_dir),
                    "--send-mode",
                    "stage",
                    "--max-steps",
                    "8",
                    "--json",
                ],
                cwd=Path.cwd(),
                env={**os.environ, "DATING_BOOST_NOW": "2026-05-26T00:00:00Z"},
                check=False,
                capture_output=True,
                text=True,
            )
            host_payload = json.loads(result.stdout)
            bundle_exit, _ = self._run([
                "support",
                "bundle",
                "--data-dir",
                str(data_dir),
                "--session-id",
                session_id,
                "--output",
                str(bundle_path),
                "--redaction",
                "strict",
                "--json",
            ])
            _names, joined = self._read_zip(bundle_path)

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertEqual(host_payload["status"], "staged_waiting_user_confirmation")
        self.assertEqual(bundle_exit, 0)
        self.assertIn(b"command_started", joined)
        self.assertIn(b"command_finished", joined)
        self.assertIn(b"dating-boost-host-loop", joined)
        self.assertIn(b'"--data-dir", "[redacted]"', joined)
        self.assertIn(b'"--fixture-host", "[redacted]"', joined)
        self.assertIn(b'"--work-dir", "[redacted]"', joined)
        self.assertNotIn(str(data_dir).encode("utf-8"), joined)
        self.assertNotIn(str(work_dir).encode("utf-8"), joined)
        self.assertIn(b"host_loop_work_item", joined)
        self.assertIn(b"host_loop_observation", joined)
        self.assertIn(b"host_loop_staged_verification", joined)
        self.assertIn(b"host_loop_command_result", joined)
        self.assertIn(b"staged_waiting_user_confirmation", joined)
        self.assertNotIn("那先欠你一顿好吃的".encode("utf-8"), joined)

    def _run(self, argv: list[str]) -> tuple[int, dict[str, object]]:
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(argv)
        return exit_code, json.loads(output.getvalue())

    def _read_zip(self, path: Path) -> tuple[set[str], bytes]:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            joined = b"\n".join(archive.read(name) for name in sorted(names))
        return names, joined


def _full_draft(best_reply: str) -> dict[str, object]:
    return {
        "schema_version": 2,
        "best_reply": best_reply,
        "safer_reply": best_reply,
        "bolder_reply": best_reply,
        "why_this_works": "Keeps the test focused on support logging.",
        "situation_read": "Test fixture.",
        "conversation_move": "bridge_topic",
        "hook_source": "fixture",
        "naturalness_notes": ["fixture"],
        "followup_if_match_replies": "Continue normally.",
        "risk_flags": [],
        "missing_info": [],
        "mode_notes": "adaptive",
        "persona_divergence": "low",
        "stance_divergence": "low",
    }

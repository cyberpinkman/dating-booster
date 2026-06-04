import json
import os
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
import zipfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from dating_boost.cli import main
from dating_boost.core import release as release_core


class PublicProductionTests(unittest.TestCase):
    def setUp(self):
        self._env = patch.dict(
            os.environ,
            {
                "DATING_BOOST_NOW": "2026-06-03T00:00:00Z",
                "DATING_BOOST_KEY_PROVIDER": "local",
            },
        )
        self._env.start()

    def tearDown(self):
        self._env.stop()

    def test_migration_encrypts_sqlite_payloads_and_reports_v2_capabilities(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            secret = "Ada private London detail"
            self._write_json(
                data_dir / "matches" / "match_ada" / "match.json",
                {"schema_version": 1, "match_id": "match_ada", "display_name": secret},
            )

            migrate_exit, migrate_payload, _ = self._run(["data", "migrate", "--data-dir", str(data_dir), "--json"])
            doctor_exit, doctor_payload, _ = self._run(["data", "doctor", "--data-dir", str(data_dir), "--json"])
            caps_exit, caps_payload, _ = self._run(["capabilities", "--data-dir", str(data_dir), "--json"])
            export_path = root / "export.json"
            export_exit, _, _ = self._run(
                ["data", "export", "--data-dir", str(data_dir), "--output", str(export_path), "--json"]
            )

            self.assertEqual(migrate_exit, 0)
            self.assertEqual(migrate_payload["schema_version"], 2)
            self.assertEqual(migrate_payload["encryption"]["status"], "encrypted")
            self.assertEqual(doctor_exit, 0)
            self.assertEqual(doctor_payload["schema_version"], 2)
            self.assertTrue(doctor_payload["checks"]["encryption_ok"])
            self.assertEqual(caps_exit, 0)
            self.assertTrue(caps_payload["storage_capabilities"]["encrypted_default"])
            self.assertTrue(caps_payload["storage_capabilities"]["keychain"])
            self.assertEqual(export_exit, 0)
            self.assertIn(secret, export_path.read_text(encoding="utf-8"))
            self.assertNotIn(secret.encode("utf-8"), (data_dir / "dating_boost.sqlite3").read_bytes())

    def test_backup_restore_and_rekey_preserve_export_without_plaintext_db(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            restore_dir = root / "restore"
            backup_path = root / "backup.zip"
            passphrase_file = root / "passphrase.txt"
            wrong_passphrase_file = root / "wrong-passphrase.txt"
            passphrase_file.write_text("correct horse battery staple\n", encoding="utf-8")
            wrong_passphrase_file.write_text("wrong passphrase\n", encoding="utf-8")
            self._write_json(
                data_dir / "matches" / "match_ada" / "match.json",
                {"schema_version": 1, "match_id": "match_ada", "display_name": "Ada private London detail"},
            )
            self._run(["data", "migrate", "--data-dir", str(data_dir), "--json"])
            before_export = root / "before.json"
            self._run(["data", "export", "--data-dir", str(data_dir), "--output", str(before_export), "--json"])
            before_payload = json.loads(before_export.read_text(encoding="utf-8"))
            before_db = (data_dir / "dating_boost.sqlite3").read_bytes()

            backup_without_key_exit, backup_without_key_payload, _ = self._run(
                ["data", "backup", "--data-dir", str(data_dir), "--output", str(backup_path), "--json"]
            )
            with patch.dict(os.environ, {"DATING_BOOST_RECOVERY_PASSPHRASE": "correct horse battery staple"}):
                backup_exit, backup_payload, _ = self._run(
                    [
                        "data",
                        "backup",
                        "--data-dir",
                        str(data_dir),
                        "--output",
                        str(backup_path),
                        "--json",
                    ]
                )
            rekey_exit, rekey_payload, _ = self._run(["data", "rekey", "--data-dir", str(data_dir), "--json"])
            after_export = root / "after.json"
            self._run(["data", "export", "--data-dir", str(data_dir), "--output", str(after_export), "--json"])
            wrong_restore_exit, wrong_restore_payload, _ = self._run(
                [
                    "data",
                    "restore",
                    "--data-dir",
                    str(root / "wrong-restore"),
                    "--input",
                    str(backup_path),
                    "--confirm",
                    "restore",
                    "--recovery-passphrase-file",
                    str(wrong_passphrase_file),
                    "--json",
                ]
            )
            restore_exit, restore_payload, _ = self._run(
                [
                    "data",
                    "restore",
                    "--data-dir",
                    str(restore_dir),
                    "--input",
                    str(backup_path),
                    "--confirm",
                    "restore",
                    "--recovery-passphrase-file",
                    str(passphrase_file),
                    "--json",
                ]
            )
            restored_export = root / "restored.json"
            self._run(["data", "export", "--data-dir", str(restore_dir), "--output", str(restored_export), "--json"])

            self.assertEqual(backup_without_key_exit, 2)
            self.assertEqual(backup_without_key_payload["reason"], "recovery_passphrase_required")
            self.assertEqual(backup_exit, 0)
            self.assertEqual(backup_payload["status"], "ok")
            self.assertEqual(backup_payload["key_recovery"], "passphrase")
            self.assertTrue(backup_path.exists())
            with zipfile.ZipFile(backup_path) as archive:
                self.assertIn("manifest.json", archive.namelist())
                manifest = json.loads(archive.read("manifest.json"))
            self.assertTrue(manifest["encrypted"])
            self.assertIn("recovery_key", manifest)
            self.assertNotIn("local_key_material", manifest)
            self.assertEqual(rekey_exit, 0)
            self.assertEqual(rekey_payload["status"], "ok")
            self.assertNotEqual(before_db, (data_dir / "dating_boost.sqlite3").read_bytes())
            after_payload = json.loads(after_export.read_text(encoding="utf-8"))
            restored_payload = json.loads(restored_export.read_text(encoding="utf-8"))
            self.assertEqual(before_payload["documents"], after_payload["documents"])
            self.assertEqual(before_payload["documents"], restored_payload["documents"])
            self.assertEqual(wrong_restore_exit, 2)
            self.assertEqual(wrong_restore_payload["reason"], "recovery_passphrase_invalid")
            self.assertEqual(restore_exit, 0)
            self.assertEqual(restore_payload["status"], "ok")

    def test_doctor_and_export_block_when_encrypted_payloads_cannot_decrypt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            export_path = root / "export.json"
            self._write_json(
                data_dir / "matches" / "match_ada" / "match.json",
                {"schema_version": 1, "match_id": "match_ada", "display_name": "Ada private London detail"},
            )
            self._run(["data", "migrate", "--data-dir", str(data_dir), "--json"])
            (data_dir / ".dating_boost_key").unlink()

            doctor_exit, doctor_payload, _ = self._run(["data", "doctor", "--data-dir", str(data_dir), "--json"])
            export_exit, export_payload, _ = self._run(
                ["data", "export", "--data-dir", str(data_dir), "--output", str(export_path), "--json"]
            )

            self.assertEqual(doctor_exit, 2)
            self.assertEqual(doctor_payload["status"], "blocked")
            self.assertEqual(doctor_payload["reason"], "payload_decryption_failed")
            self.assertFalse(doctor_payload["checks"]["encryption_ok"])
            self.assertEqual(export_exit, 2)
            self.assertEqual(export_payload["status"], "blocked")
            self.assertEqual(export_payload["reason"], "payload_decryption_failed")
            self.assertFalse(export_path.exists())

    def test_restore_corrupt_backup_is_blocked_without_destroying_existing_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "source"
            restore_dir = root / "restore"
            backup_path = root / "backup.zip"
            corrupt_backup_path = root / "corrupt-backup.zip"
            existing_export_path = root / "existing.json"
            passphrase_file = root / "passphrase.txt"
            passphrase_file.write_text("correct horse battery staple\n", encoding="utf-8")
            self._write_json(
                source_dir / "matches" / "match_ada" / "match.json",
                {"schema_version": 1, "match_id": "match_ada", "display_name": "Ada private London detail"},
            )
            self._write_json(
                restore_dir / "matches" / "match_existing" / "match.json",
                {"schema_version": 1, "match_id": "match_existing", "display_name": "Existing private detail"},
            )
            self._run(["data", "migrate", "--data-dir", str(source_dir), "--json"])
            self._run(["data", "migrate", "--data-dir", str(restore_dir), "--json"])
            with patch.dict(os.environ, {"DATING_BOOST_RECOVERY_PASSPHRASE": "correct horse battery staple"}):
                self._run(
                    [
                        "data",
                        "backup",
                        "--data-dir",
                        str(source_dir),
                        "--output",
                        str(backup_path),
                        "--json",
                    ]
                )
            with zipfile.ZipFile(backup_path) as archive:
                manifest_bytes = archive.read("manifest.json")
            with zipfile.ZipFile(corrupt_backup_path, "w") as archive:
                archive.writestr("manifest.json", manifest_bytes)
                archive.writestr("dating_boost.sqlite3", b"not a sqlite database")

            restore_exit, restore_payload, _ = self._run(
                [
                    "data",
                    "restore",
                    "--data-dir",
                    str(restore_dir),
                    "--input",
                    str(corrupt_backup_path),
                    "--confirm",
                    "restore",
                    "--recovery-passphrase-file",
                    str(passphrase_file),
                    "--json",
                ]
            )
            export_exit, _, _ = self._run(
                ["data", "export", "--data-dir", str(restore_dir), "--output", str(existing_export_path), "--json"]
            )

            self.assertEqual(restore_exit, 2)
            self.assertEqual(restore_payload["status"], "blocked")
            self.assertEqual(restore_payload["reason"], "backup_sqlite_integrity_failed")
            self.assertEqual(export_exit, 0)
            self.assertIn("Existing private detail", existing_export_path.read_text(encoding="utf-8"))

    def test_backup_restore_support_recovery_passphrase_env_and_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            restore_dir = root / "restore"
            backup_path = root / "backup.zip"
            passphrase_file = root / "passphrase.txt"
            export_path = root / "restored.json"
            passphrase_file.write_text("correct horse battery staple\n", encoding="utf-8")
            self._write_json(
                data_dir / "matches" / "match_ada" / "match.json",
                {"schema_version": 1, "match_id": "match_ada", "display_name": "Ada private London detail"},
            )
            self._run(["data", "migrate", "--data-dir", str(data_dir), "--json"])

            with patch.dict(os.environ, {"DATING_BOOST_RECOVERY_PASSPHRASE": "correct horse battery staple"}):
                backup_exit, backup_payload, _ = self._run(
                    ["data", "backup", "--data-dir", str(data_dir), "--output", str(backup_path), "--json"]
                )
            restore_exit, restore_payload, _ = self._run(
                [
                    "data",
                    "restore",
                    "--data-dir",
                    str(restore_dir),
                    "--input",
                    str(backup_path),
                    "--confirm",
                    "restore",
                    "--recovery-passphrase-file",
                    str(passphrase_file),
                    "--json",
                ]
            )
            export_exit, _, _ = self._run(
                ["data", "export", "--data-dir", str(restore_dir), "--output", str(export_path), "--json"]
            )

            self.assertEqual(backup_exit, 0)
            self.assertEqual(backup_payload["status"], "ok")
            self.assertEqual(restore_exit, 0)
            self.assertEqual(restore_payload["status"], "ok")
            self.assertEqual(export_exit, 0)
            self.assertIn("Ada private London detail", export_path.read_text(encoding="utf-8"))

    def test_safety_pause_blocks_autonomous_action(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"

            pause_exit, pause_payload, _ = self._run(
                ["safety", "pause", "--data-dir", str(data_dir), "--reason", "manual-stop", "--json"]
            )
            action_exit, action_payload, _ = self._run(
                ["policy", "check-action", "send_message", "--autonomous", "--data-dir", str(data_dir)]
            )
            status_exit, status_payload, _ = self._run(["safety", "status", "--data-dir", str(data_dir), "--json"])

            self.assertEqual(pause_exit, 0)
            self.assertEqual(pause_payload["status"], "paused")
            self.assertEqual(action_exit, 2)
            self.assertFalse(action_payload["allowed"])
            self.assertEqual(action_payload["reason"], "safety_paused")
            self.assertEqual(status_exit, 0)
            self.assertTrue(status_payload["paused"])

    def test_daemon_run_status_and_launchd_dry_run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"

            install_exit, install_payload, _ = self._run(
                ["daemon", "install", "--data-dir", str(data_dir), "--dry-run", "--json"]
            )
            run_exit, run_payload, _ = self._run(["daemon", "run", "--data-dir", str(data_dir), "--once", "--json"])
            status_exit, status_payload, _ = self._run(["daemon", "status", "--data-dir", str(data_dir), "--json"])

            self.assertEqual(install_exit, 0)
            self.assertIn("dating-boostd", install_payload["plist"])
            self.assertEqual(run_exit, 0)
            self.assertEqual(run_payload["status"], "stopped")
            self.assertEqual(run_payload["stop_reason"], "once_completed")
            self.assertEqual(status_exit, 0)
            self.assertEqual(status_payload["state"]["status"], "stopped")

    def test_daemon_foreground_run_stays_alive_until_stop_and_releases_lock(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            env = {
                **os.environ,
                "DATING_BOOST_KEY_PROVIDER": "local",
                "DATING_BOOST_DAEMON_HEARTBEAT_INTERVAL": "0.05",
            }
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "dating_boost.cli",
                    "daemon",
                    "run",
                    "--data-dir",
                    str(data_dir),
                    "--json",
                ],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                time.sleep(0.2)
                if process.poll() is not None:
                    stdout, stderr = process.communicate()
                    self.fail(f"daemon exited before stop\nstdout={stdout}\nstderr={stderr}")

                stop_exit, stop_payload, _ = self._run(["daemon", "stop", "--data-dir", str(data_dir), "--json"])
                stdout, stderr = process.communicate(timeout=3)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()

            run_exit, run_payload, _ = self._run(["daemon", "run", "--data-dir", str(data_dir), "--once", "--json"])

            self.assertEqual(stop_exit, 0)
            self.assertEqual(stop_payload["status"], "stopped")
            self.assertEqual(stderr, "")
            self.assertIn('"stop_reason": "manual_stop"', stdout)
            self.assertEqual(run_exit, 0)
            self.assertEqual(run_payload["status"], "stopped")

    def test_diagnostics_bundle_is_redacted_and_local_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            bundle_path = root / "diagnostics.zip"
            secret = "Ada private London detail"
            self._write_json(
                data_dir / "matches" / "match_ada" / "match.json",
                {"schema_version": 1, "match_id": "match_ada", "display_name": secret},
            )
            self._run(["data", "migrate", "--data-dir", str(data_dir), "--json"])

            exit_code, payload, _ = self._run(
                ["diagnostics", "bundle", "--data-dir", str(data_dir), "--output", str(bundle_path), "--json"]
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["status"], "ok")
            self.assertTrue(bundle_path.exists())
            with zipfile.ZipFile(bundle_path) as archive:
                names = set(archive.namelist())
                joined = b"\n".join(archive.read(name) for name in names)
            self.assertIn("manifest.json", names)
            self.assertIn("capabilities.redacted.json", names)
            self.assertNotIn(secret.encode("utf-8"), joined)
            self.assertNotIn(b"best_reply", joined)

    def test_release_doctor_validates_public_release_manifest(self):
        exit_code, payload, _ = self._run(["release", "doctor", "--json"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["tool_version"], "1.0.0-rc.1")
        self.assertEqual(payload["artifacts"]["wheel"], "dating_booster-1.0.0rc1-py3-none-any.whl")
        self.assertEqual(payload["artifacts"]["sdist"], "dating_booster-1.0.0rc1.tar.gz")
        self.assertTrue(payload["release_capabilities"]["pypi"])
        self.assertTrue(payload["release_capabilities"]["github_release"])
        self.assertTrue(payload["release_capabilities"]["skill_package"])

    def test_repository_declares_mit_license(self):
        license_text = Path("LICENSE").read_text(encoding="utf-8")
        pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

        self.assertTrue(license_text.startswith("MIT License"))
        self.assertIn("Permission is hereby granted, free of charge", license_text)
        self.assertEqual(pyproject["project"]["license"]["text"], "MIT")
        self.assertIn("License :: OSI Approved :: MIT License", pyproject["project"]["classifiers"])

    def test_release_doctor_blocks_tag_mismatch_in_strict_release_mode(self):
        with patch.dict(os.environ, {"DATING_BOOST_RELEASE_STRICT": "1", "GITHUB_REF_NAME": "v9.9.9"}):
            with patch.object(release_core, "_git_dirty", return_value=False):
                payload = release_core.release_doctor()

        self.assertEqual(payload["status"], "blocked")
        self.assertIn("release_tag_mismatch", payload["issues"])

    def test_release_doctor_blocks_dirty_source_in_strict_release_mode(self):
        with patch.dict(os.environ, {"DATING_BOOST_RELEASE_STRICT": "1", "GITHUB_REF_NAME": "v1.0.0-rc.1"}):
            with patch.object(release_core, "_git_dirty", return_value=True):
                payload = release_core.release_doctor()

        self.assertEqual(payload["status"], "blocked")
        self.assertIn("dirty_source_tree", payload["issues"])

    def test_release_doctor_is_not_strict_for_regular_ci_branch_checks(self):
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true", "GITHUB_REF_TYPE": "branch", "GITHUB_REF_NAME": "main"}):
            with patch.object(release_core, "_git_dirty", return_value=True):
                payload = release_core.release_doctor()

        self.assertEqual(payload["status"], "ok")
        self.assertNotIn("dirty_source_tree", payload["issues"])

    def _run(self, argv):
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(argv)
        text = output.getvalue()
        return exit_code, json.loads(text), text

    def _write_json(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()

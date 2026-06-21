import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


def _load_smoke_module():
    path = Path("scripts/tashuo_mac_ios_standalone_smoke.py")
    spec = importlib.util.spec_from_file_location("tashuo_mac_ios_standalone_smoke", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TaShuoStandaloneSmokeScriptTests(unittest.TestCase):
    def test_smoke_runs_stage_only_standalone_commands(self):
        module = _load_smoke_module()
        calls = []

        def fake_run(cmd, check=False, capture_output=False, text=False, cwd=None):
            calls.append(cmd)
            payload = {"status": "ok"}
            if "tick" in cmd:
                payload = {"status": "stage_recorded", "reason": "stage_recorded"}
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

        original_run = module.subprocess.run
        module.subprocess.run = fake_run
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                auth = root / "auth.json"
                auth.write_text("{}", encoding="utf-8")
                vision = root / "vision.json"
                vision.write_text(json.dumps({"status": "ok", "rows": []}), encoding="utf-8")
                backend = root / "backend.json"
                backend.write_text(json.dumps({"best_reply": "你好"}), encoding="utf-8")
                exit_code = module.main(
                    [
                        "--data-dir",
                        str(root / "data"),
                        "--output-dir",
                        str(root / "harness"),
                        "--authorization",
                        str(auth),
                        "--vision-backend",
                        "scripted",
                        "--scripted-vision-output",
                        str(vision),
                        "--backend",
                        "scripted",
                        "--scripted-backend-output",
                        str(backend),
                        "--json",
                    ]
                )
        finally:
            module.subprocess.run = original_run

        command_args = [call[3:] for call in calls]
        self.assertEqual(exit_code, 0)
        self.assertIn(["runtime", "select", "--data-dir", str(root / "data"), "--app-id", "tashuo", "--runtime", "mac-ios-app", "--json"], command_args)
        self.assertTrue(
            any(
                command[:2] == ["standalone-session", "start"]
                and "--app-id" in command
                and "tashuo" in command
                and "--runtime" in command
                and "mac-ios-app" in command
                and "--observation-source" in command
                and "live-gui" in command
                and "--send-mode" in command
                and "stage" in command
                for command in command_args
            )
        )
        self.assertIn(["standalone-session", "tick", "--data-dir", str(root / "data"), "--json"], command_args)
        self.assertIn(
            ["standalone-session", "stop", "--data-dir", str(root / "data"), "--reason", "smoke_complete", "--json"],
            command_args,
        )
        flattened = [item for command in command_args for item in command]
        self.assertNotIn("--managed-gui-send", flattened)


if __name__ == "__main__":
    unittest.main()

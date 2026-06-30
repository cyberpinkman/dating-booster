from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from dating_boost.cli import main
from dating_boost.core.standalone_provider_factory import build_standalone_runtime_ports


class StandaloneProviderFactoryTests(unittest.TestCase):
    def test_tashuo_live_gui_source_builds_ports(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            vision = Path(temp_dir) / "vision.json"
            vision.write_text(json.dumps({"status": "ok", "rows": []}), encoding="utf-8")
            ports = build_standalone_runtime_ports(
                Path(temp_dir) / "data",
                {
                    "app_id": "tashuo",
                    "runtime": "mac-ios-app",
                    "send_mode": "stage",
                    "managed_gui_send": False,
                    "observation_source": {
                        "type": "live_gui",
                        "app_id": "tashuo",
                        "runtime": "mac-ios-app",
                        "output_dir": str(Path(temp_dir) / "harness"),
                    },
                    "vision_backend": {"type": "scripted", "path": str(vision)},
                },
            )
        self.assertEqual(ports["status"], "ok")
        self.assertEqual(ports["observation_source_type"], "live_gui")
        self.assertIsNotNone(ports["observation_provider"])
        self.assertIsNotNone(ports["harness_factory"])
        self.assertIsNotNone(ports["action_executor"])

    def test_live_gui_blocks_non_tashuo_runtime(self):
        ports = build_standalone_runtime_ports(
            Path("data"),
            {
                "app_id": "tinder",
                "runtime": "default",
                "send_mode": "stage",
                "managed_gui_send": False,
                "observation_source": {"type": "live_gui", "app_id": "tinder", "runtime": "default"},
                "vision_backend": {"type": "scripted", "path": "missing.json"},
            },
        )
        self.assertEqual(ports["status"], "blocked")
        self.assertEqual(ports["reason"], "unsupported_live_gui_observation_source")


class StandaloneTaShuoCliTests(unittest.TestCase):
    def _run_cli(self, argv):
        buffer = StringIO()
        with redirect_stdout(buffer):
            code = main(argv)
        return code, json.loads(buffer.getvalue())

    def test_cli_blocks_live_gui_without_vision_backend(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            auth = root / "auth.json"
            auth.write_text(
                '{"schema_version":1,"authorization_id":"auth","app_id":"tashuo","send_mode":"stage"}',
                encoding="utf-8",
            )
            code, payload = self._run_cli(
                [
                    "standalone-session",
                    "start",
                    "--data-dir",
                    str(root / "data"),
                    "--authorization",
                    str(auth),
                    "--app-id",
                    "tashuo",
                    "--runtime",
                    "mac-ios-app",
                    "--send-mode",
                    "stage",
                    "--observation-source",
                    "live-gui",
                    "--json",
                ]
            )
        self.assertEqual(code, 2)
        self.assertEqual(payload["reason"], "vision_backend_required_for_live_gui_source")

    def test_cli_persists_minimax_live_gui_vision_backend(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            auth = root / "auth.json"
            auth.write_text(
                '{"schema_version":1,"authorization_id":"auth","app_id":"tashuo","send_mode":"stage"}',
                encoding="utf-8",
            )
            start_args = [
                "standalone-session",
                "start",
                "--data-dir",
                str(root / "data"),
                "--authorization",
                str(auth),
                "--app-id",
                "tashuo",
                "--runtime",
                "mac-ios-app",
                "--send-mode",
                "stage",
                "--observation-source",
                "live-gui",
                "--output-dir",
                str(root / "harness"),
                "--vision-backend",
                "minimax",
                "--vision-model",
                "MiniMax-M3",
                "--backend",
                "minimax",
                "--minimax-api-key-env",
                "MINIMAX_API_KEY",
                "--minimax-request-timeout-seconds",
                "19",
                "--json",
            ]
            class FakeMiniMaxVisionBackend:
                def __init__(self, **kwargs):
                    self.kwargs = kwargs

            with patch("dating_boost.intelligence.vision_backend_factory.MiniMaxVisionBackend", FakeMiniMaxVisionBackend):
                confirm_exit, confirm_payload = self._run_cli(start_args)
                start_exit, start_payload = self._run_cli(
                    start_args[:-1] + ["--config-confirm", confirm_payload["required_confirm_token"], "--json"]
                )

        self.assertEqual(confirm_exit, 2)
        self.assertEqual(confirm_payload["reason"], "managed_session_config_confirmation_required")
        self.assertEqual(start_exit, 0)
        self.assertEqual(start_payload["status"], "active")
        self.assertEqual(
            start_payload["session"]["vision_backend"],
            {
                "type": "minimax",
                "model": "MiniMax-M3",
                "base_url": "https://api.minimaxi.com/v1",
                "api_key_env": "MINIMAX_API_KEY",
                "timeout_seconds": 19.0,
            },
        )
        self.assertEqual(start_payload["session"]["backend"]["timeout_seconds"], 19.0)

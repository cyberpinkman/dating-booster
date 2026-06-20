import inspect
import unittest
from pathlib import Path
from typing import Any, get_type_hints

from dating_boost.core.managed_gui_send import ManagedGuiSendArgsPort, ManagedGuiSendHostPort


class ManagedGuiSendPortTests(unittest.TestCase):
    def test_protocol_declares_required_state(self):
        host_hints = get_type_hints(ManagedGuiSendHostPort)
        args_hints = get_type_hints(ManagedGuiSendArgsPort)

        self.assertIs(host_hints["args"], ManagedGuiSendArgsPort)
        self.assertIs(host_hints["data_dir"], Path)
        self.assertIs(host_hints["work_dir"], Path)
        self.assertIn("staged_verifications", host_hints)
        self.assertIn("action_results_recorded", host_hints)
        self.assertIn("app_id", args_hints)
        self.assertIn("harness_runtime", args_hints)

    def test_protocol_declares_required_method_signatures(self):
        required_methods = {
            "_finish",
            "_runtime_live_send_block_reason",
            "_target_profile_block_reason",
            "_authorization_path",
            "_live_send_action_request",
            "_run_cli_json",
            "_append_timeline",
            "_work_file",
            "_clear_host_work_item",
        }

        for name in required_methods:
            self.assertTrue(callable(getattr(ManagedGuiSendHostPort, name)))

        finish_params = inspect.signature(ManagedGuiSendHostPort._finish).parameters
        self.assertEqual(list(finish_params), ["self", "status", "reason", "current", "extra"])
        self.assertEqual(finish_params["current"].kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertEqual(finish_params["extra"].kind, inspect.Parameter.KEYWORD_ONLY)

        run_params = inspect.signature(ManagedGuiSendHostPort._run_cli_json).parameters
        self.assertEqual(run_params["args"].kind, inspect.Parameter.VAR_POSITIONAL)
        self.assertEqual(run_params["allow_error"].kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertEqual(run_params["timeout_seconds"].kind, inspect.Parameter.KEYWORD_ONLY)

        finish_hints = get_type_hints(ManagedGuiSendHostPort._finish)
        run_hints = get_type_hints(ManagedGuiSendHostPort._run_cli_json)
        self.assertEqual(finish_hints["status"], str)
        self.assertEqual(finish_hints["reason"], str)
        self.assertEqual(finish_hints["return"], dict[str, Any])
        self.assertEqual(run_hints["return"], dict[str, Any])


if __name__ == "__main__":
    unittest.main()

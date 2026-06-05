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
                self.assertEqual(profile["schema_version"], 1)
                self.assertEqual(profile["app_id"], path.stem)
                if profile["host_loop_supported"]:
                    self.assertTrue(profile["host_loop_send_modes"], path.name)
                self.assertIn("native_gui_harness", profile)
                self.assertTrue(profile["native_gui_harness"]["supported_stage_actions"])
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


if __name__ == "__main__":
    unittest.main()

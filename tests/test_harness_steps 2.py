import unittest

from dating_boost.core.gui_harness import NativeGuiHarness
from dating_boost.core.harness_steps import (
    harness_step_validation_reason,
    marker_step,
    swipe_step,
    tap_step,
    wheel_step,
)
from dating_boost.harness.base import WindowInfo


class HarnessStepTests(unittest.TestCase):
    def test_tap_step_preserves_existing_payload_shape_and_extra_guards(self):
        step = tap_step(
            "tap_bumble_chats_tab",
            x=0.89,
            y=0.93,
            requires_verified_bumble_screen=True,
            requires_bumble_top_level_tab_bar=True,
            expected_bumble_states=["bumble_chat_list"],
        )

        self.assertEqual(
            step,
            {
                "intent": "tap_bumble_chats_tab",
                "tap_ratio": {"x": 0.89, "y": 0.93},
                "risk": "navigation_only",
                "requires_verified_bumble_screen": True,
                "requires_bumble_top_level_tab_bar": True,
                "expected_bumble_states": ["bumble_chat_list"],
            },
        )

    def test_wheel_and_swipe_steps_share_operation_contract(self):
        self.assertEqual(
            wheel_step("wheel_messages", x=0.5, y=0.78, delta_y=-18, repeats=14),
            {
                "intent": "wheel_messages",
                "wheel": {
                    "x": 0.5,
                    "y": 0.78,
                    "delta_y": -18,
                    "delta_x": 0,
                    "repeats": 14,
                    "interval_us": 18000,
                },
                "risk": "navigation_only",
            },
        )
        self.assertEqual(
            swipe_step("swipe_card", from_x=0.8, from_y=0.5, to_x=0.2, to_y=0.5),
            {
                "intent": "swipe_card",
                "swipe": {
                    "from": {"x": 0.8, "y": 0.5},
                    "to": {"x": 0.2, "y": 0.5},
                    "duration_ms": 350,
                },
                "risk": "navigation_only",
            },
        )

    def test_marker_step_supports_non_input_executor_intents(self):
        self.assertEqual(
            marker_step("type_app_name_verified", text="Tinder", wait_after_seconds=0.2),
            {
                "intent": "type_app_name_verified",
                "risk": "navigation_only",
                "text": "Tinder",
                "wait_after_seconds": 0.2,
            },
        )

    def test_validation_rejects_ambiguous_or_malformed_operations(self):
        self.assertEqual(
            harness_step_validation_reason(
                {
                    "intent": "ambiguous",
                    "tap_ratio": {"x": 0.5, "y": 0.5},
                    "wheel": {"x": 0.5, "y": 0.5},
                }
            ),
            "gui_step_has_multiple_operations",
        )
        self.assertEqual(
            harness_step_validation_reason({"intent": "bad_tap", "tap_ratio": {"x": 1.2, "y": 0.5}}),
            "gui_step_tap_ratio_x_out_of_range",
        )
        self.assertEqual(
            harness_step_validation_reason({"intent": "bad_swipe", "swipe": {"from": {"x": 0.1, "y": 0.2}}}),
            "gui_step_swipe_to_not_mapping",
        )
        self.assertEqual(
            harness_step_validation_reason({"intent": "bad_wheel", "wheel": {"x": 0.5, "y": 0.5, "repeats": 0}}),
            "gui_step_wheel_repeats_not_positive",
        )
        self.assertEqual(
            harness_step_validation_reason({"intent": "bool_tap", "tap_ratio": {"x": True, "y": 0.5}}),
            "gui_step_tap_ratio_x_not_numeric",
        )
        self.assertEqual(
            harness_step_validation_reason(
                {
                    "intent": "float_repeats",
                    "wheel": {"x": 0.5, "y": 0.5, "delta_y": -18, "repeats": 14.0},
                }
            ),
            "gui_step_wheel_repeats_not_integer",
        )
        self.assertEqual(
            harness_step_validation_reason(
                {
                    "intent": "float_duration",
                    "swipe": {"from": {"x": 0.1, "y": 0.2}, "to": {"x": 0.3, "y": 0.4}, "duration_ms": 350.5},
                }
            ),
            "gui_step_swipe_duration_ms_not_integer",
        )

    def test_execute_step_blocks_invalid_payload_but_preserves_unknown_intent_reason(self):
        harness = NativeGuiHarness(runner=object())
        window = WindowInfo(x=0, y=0, width=100, height=200, name="iPhone Mirroring", frontmost=True)

        invalid = harness._execute_step(window, {"intent": "bad_tap", "tap_ratio": {"x": -0.1, "y": 0.5}})
        self.assertEqual(invalid["status"], "blocked")
        self.assertEqual(invalid["reason"], "gui_step_tap_ratio_x_out_of_range")

        unknown = harness._execute_step(window, {"intent": "unknown_no_input_step"})
        self.assertEqual(unknown["status"], "blocked")
        self.assertEqual(unknown["reason"], "unknown_gui_step")


if __name__ == "__main__":
    unittest.main()

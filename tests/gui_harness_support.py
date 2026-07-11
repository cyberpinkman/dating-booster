import json
import hashlib
import re
import struct
import tempfile
import unittest
import zlib
from contextlib import contextmanager, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from dating_boost.apps.registry import create_adapter
from dating_boost.apps.tashuo import native as tashuo_native
from dating_boost.cli import SUPPORTED_NATIVE_HARNESS_APPS, main
from dating_boost.core.gui_harness import (
    classify_bumble_screen_text,
    classify_screen_text,
    classify_wechat_screen_text,
)
from dating_boost.apps.tashuo.screen_state import (
    classify_tashuo_capture, classify_tashuo_screen_image, classify_tashuo_screen_text, combine_tashuo_screen_states,
    tashuo_layout_hints, tashuo_thread_cues_from_text,
)
from dating_boost.harness.input_backends import core_graphics_command_v, core_graphics_drag
from dating_boost.harness.base import WindowInfo
from dating_boost.core.storage import JsonStorage


class FakeRunner:
    def __init__(
        self,
        *,
        ocr_text: str | list[str],
        frontmost: bool = True,
        screenshot_bytes: bytes | list[bytes] | None = None,
        missing_commands: set[str] | None = None,
        window_name: str = "iPhone Mirroring",
        paste_focus_override: str | None = None,
        return_key_clears_focus: bool = True,
        screenshot_fail_at: set[int] | None = None,
        window_info_stdout: str | list[str] | None = None,
        ax_text_area_value: str | None = None,
        ax_static_text_values: list[str] | None = None,
        ax_navback_stdout: str = "clicked",
    ):
        self.ocr_texts = list(ocr_text) if isinstance(ocr_text, list) else [ocr_text]
        self.frontmost = frontmost
        if isinstance(screenshot_bytes, list):
            self.screenshot_bytes = None
            self.screenshot_byte_outputs = list(screenshot_bytes)
        else:
            self.screenshot_bytes = screenshot_bytes
            self.screenshot_byte_outputs = []
        self.missing_commands = missing_commands or set()
        self.window_name = window_name
        self.commands: list[list[str]] = []
        self.command_inputs: list[tuple[list[str], str | None]] = []
        self.clipboard_text = "previous clipboard"
        self.focused_text = ""
        self.paste_focus_override = paste_focus_override
        self.return_key_clears_focus = return_key_clears_focus
        self.screenshot_fail_at = screenshot_fail_at or set()
        self.screenshot_calls = 0
        self.ax_text_area_value = ax_text_area_value
        self.ax_static_text_values = ax_static_text_values or []
        self.ax_navback_clicks = 0
        self.ax_navback_stdout = ax_navback_stdout
        if isinstance(window_info_stdout, list):
            self.window_info_outputs = list(window_info_stdout)
        elif isinstance(window_info_stdout, str):
            self.window_info_outputs = [window_info_stdout]
        else:
            self.window_info_outputs = []

    def run(self, command: list[str], *, input: str | None = None):
        self.commands.append(command)
        self.command_inputs.append((command, input))
        if command[:2] == ["command", "-v"]:
            if command[2] in self.missing_commands:
                return _result(returncode=1)
            return _result(stdout=f"/usr/bin/{command[2]}\n")
        if command and command[0] == "osascript" and any("get {frontmost" in item for item in command):
            if self.window_info_outputs:
                if len(self.window_info_outputs) > 1:
                    return _result(stdout=self.window_info_outputs.pop(0))
                return _result(stdout=self.window_info_outputs[0])
            frontmost = "true" if self.frontmost else "false"
            return _result(stdout=f"{frontmost}, 100, 50, 350, 760, {self.window_name}\n")
        if command and command[0] == "osascript" and any("DATING_BOOST_AX_TEXT_AREA_VALUE" in item for item in command):
            if self.ax_text_area_value is None:
                return _result(stdout="__DATING_BOOST_TEXT_AREA_NOT_FOUND__\n")
            return _result(stdout=f"{self.ax_text_area_value}\n")
        if command and command[0] == "osascript" and any("DATING_BOOST_AX_STATIC_TEXT_VALUES" in item for item in command):
            return _result(stdout=json.dumps(self.ax_static_text_values, ensure_ascii=False))
        if command and command[0] == "osascript" and any("DATING_BOOST_AX_SET_TEXT_AREA_VALUE" in item for item in command):
            if self.ax_text_area_value is None:
                return _result(stdout="not_found\n")
            script = " ".join(command)
            match = re.search(r'setTextAreaValue\(window 1, 0, "((?:[^"\\]|\\.)*)"\)', script)
            if match:
                try:
                    self.ax_text_area_value = json.loads(f'"{match.group(1)}"')
                except json.JSONDecodeError:
                    self.ax_text_area_value = match.group(1)
            else:
                self.ax_text_area_value = "ax-set-text"
            self.focused_text = self.ax_text_area_value
            return _result(stdout="set\n")
        if command and command[0] == "osascript" and any("DATING_BOOST_AX_CLEAR_TEXT_AREA" in item for item in command):
            if self.ax_text_area_value is None:
                return _result(stdout="not_found\n")
            self.ax_text_area_value = ""
            return _result(stdout="cleared\n")
        if command and command[0] == "osascript" and any("thin left navback" in item for item in command):
            self.ax_navback_clicks += 1
            return _result(stdout=f"{self.ax_navback_stdout}\n")
        if command and command[0] == "osascript" and any("DATING_BOOST_TASHUO_DISMISS_NOTIFICATION_PROMPT" in item for item in command):
            return _result(stdout="clicked\n")
        if command and command[0] == "osascript" and any("focused UI element" in item for item in command):
            return _result(stdout=f"{self.focused_text}\n")
        if command and command[0] == "osascript" and any('keystroke "v"' in item for item in command):
            self.focused_text = self.clipboard_text if self.paste_focus_override is None else self.paste_focus_override
            if self.ax_text_area_value is not None:
                self.ax_text_area_value = self.focused_text
            return _result(stdout="")
        if command[:2] == ["xcrun", "swift"] and "dating_boost_core_graphics_command_v" in str(command[-1]):
            self.focused_text = self.clipboard_text if self.paste_focus_override is None else self.paste_focus_override
            if self.ax_text_area_value is not None:
                self.ax_text_area_value = self.focused_text
            return _result(stdout="")
        if command and command[0] == "osascript" and any("key code 36" in item for item in command):
            if self.return_key_clears_focus:
                self.focused_text = ""
                if self.ax_text_area_value is not None:
                    self.ax_text_area_value = ""
            return _result(stdout="")
        if command and command[0] == "osascript":
            return _result(stdout="")
        if command and command[0] == "screencapture":
            self.screenshot_calls += 1
            if self.screenshot_calls in self.screenshot_fail_at:
                return _result(stderr="screen permission denied", returncode=1)
            output = Path(command[-1])
            output.parent.mkdir(parents=True, exist_ok=True)
            if self.screenshot_byte_outputs:
                if len(self.screenshot_byte_outputs) > 1:
                    screenshot_bytes = self.screenshot_byte_outputs.pop(0)
                else:
                    screenshot_bytes = self.screenshot_byte_outputs[0]
            else:
                screenshot_bytes = self.screenshot_bytes or b"fake png"
            output.write_bytes(screenshot_bytes)
            return _result(stdout="")
        if command and command[0] == "tesseract":
            if len(self.ocr_texts) > 1:
                return _result(stdout=self.ocr_texts.pop(0))
            return _result(stdout=self.ocr_texts[0])
        if command and command[0] == "pbpaste":
            return _result(stdout=self.clipboard_text)
        if command and command[0] == "pbcopy":
            self.clipboard_text = input or ""
            return _result(stdout="")
        return _result(stdout="")


def _result(*, stdout: str = "", stderr: str = "", returncode: int = 0):
    return type(
        "FakeCompletedProcess",
        (),
        {"stdout": stdout, "stderr": stderr, "returncode": returncode},
    )()


def _run_cli_json(argv: list[str]) -> tuple[int, dict[str, object]]:
    output = StringIO()
    with redirect_stdout(output):
        exit_code = main(argv)
    return exit_code, json.loads(output.getvalue())


def _select_runtime_scope(data_dir: Path, app_id: str, runtime: str = "default") -> None:
    exit_code, payload = _run_cli_json([
        "runtime",
        "select",
        "--data-dir",
        str(data_dir),
        "--app-id",
        app_id,
        "--runtime",
        runtime,
        "--json",
    ])
    if exit_code != 0:
        raise AssertionError(payload)


@contextmanager
def _patch_cli_adapter():
    with patch("dating_boost.cli.create_adapter") as adapter_factory:
        adapter = adapter_factory.return_value
        adapter.session = adapter

        def current_app_id() -> str:
            call_args = adapter_factory.call_args
            if call_args is None:
                return "tinder"
            if call_args.args:
                return str(call_args.args[0])
            return str(call_args.kwargs.get("app_id") or "tinder")

        adapter.launch.side_effect = lambda *args, **kwargs: getattr(adapter, f"launch_{current_app_id()}")(
            *args,
            **kwargs,
        )
        adapter.observe.side_effect = lambda *args, **kwargs: getattr(adapter, f"observe_{current_app_id()}_screen")(
            *args,
            **kwargs,
        )
        adapter.run_action.side_effect = lambda *args, **kwargs: getattr(adapter, f"run_{current_app_id()}_action")(
            *args,
            **kwargs,
        )
        adapter.run_workflow.side_effect = lambda *args, **kwargs: getattr(adapter, f"run_{current_app_id()}_workflow")(
            *args,
            **kwargs,
        )
        adapter.stage_draft.side_effect = lambda *args, **kwargs: getattr(adapter, f"stage_{current_app_id()}_draft")(
            *args,
            **kwargs,
        )
        adapter.send_message.side_effect = lambda *args, **kwargs: getattr(adapter, f"send_{current_app_id()}_message")(
            *args,
            **kwargs,
        )
        adapter.open_profile.side_effect = lambda *args, **kwargs: adapter.open_tinder_profile(*args, **kwargs)
        yield adapter_factory


def _ocr_tsv_for_line(text: str, *, top: int = 235, height: int = 28, left: int = 80, width: int = 60) -> str:
    return "\n".join(
        [
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext",
            f"5\t1\t1\t1\t1\t1\t{left}\t{top}\t{width}\t{height}\t93\t{text}",
            "",
        ]
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_draft_review_audit(
    data_dir: Path,
    *,
    target_match_id: str,
    payload_hash: str,
    review_id: str = "draft_review_fixture",
) -> None:
    record = {
        "schema_version": 1,
        "review_id": review_id,
        "created_at": "2026-05-26T00:00:00Z",
        "mode": "managed_live",
        "target_match_id": target_match_id,
        "payload_hash": payload_hash,
        "payload_format": "single_message",
        "message_count": 1,
        "status": "ok",
        "allowed_for_display": True,
        "allowed_for_stage": True,
        "allowed_for_managed_send": True,
        "requires_user_confirmation": False,
        "primary_reason": "passed",
        "finding_codes": [],
        "findings": [],
        "revision_hint_count": 0,
        "context_manifest": [],
        "draft_payload_hash": payload_hash,
        "context_pack_hash": "context_fixture",
        "draft_topic_labels": [],
        "draft_character_count": 0,
    }
    storage = JsonStorage(data_dir)
    storage.append_jsonl(Path("audit/draft_reviews.jsonl"), record)
    generation_record = {
        "schema_version": 1,
        "generation_id": "draft_generation_fixture",
        "evidence_id": "draft_evidence_fixture",
        "prompt_id": "prompt_fixture",
        "status": "ok",
        "primary_reason": None,
        "prompt_hash": "prompt_hash_fixture",
        "context_hash": "context_hash_fixture",
        "draft_hash": payload_hash,
        "attempt_count": 1,
        "self_review_attempts": [
            {
                "ai_or_weird_probability": 20,
                "reason": "fixture_passed",
                "supplemental_prompt_hash": "",
            }
        ],
        "created_at": "2026-05-26T00:00:00Z",
    }
    storage.append_jsonl(Path("audit/draft_generations.jsonl"), generation_record)


def _live_send_auth(app_id: str, *, authorization_id: str, allowed_match_ids: list[str] | None = None) -> dict[str, object]:
    return {
        "schema_version": 1,
        "authorization_id": authorization_id,
        "scope": "send_chat_messages",
        "app_id": app_id,
        "expires_at": "2099-01-01T00:00:00Z",
        "allowed_match_ids": allowed_match_ids or [],
        "allowed_actions": ["send_message"],
        "autonomous_send": True,
        "live_send": True,
        "requires_post_action_verification": True,
        "revoked_at": None,
    }


def _autonomous_audit_binding(
    *,
    authorization_id: str,
    target_match_id: str,
    payload_hash: str,
    precondition_hash: str = "pre_hash",
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "binding_type": "autonomous_authorization",
        "authorization_id": authorization_id,
        "action": "send_message",
        "target_match_id": target_match_id,
        "payload_hash": payload_hash,
        "precondition_hash": precondition_hash,
    }


def _planner_evidence() -> dict[str, object]:
    return {
        "planner_alignment": "ok",
        "conversation_stage": "rapport_building",
        "conversation_move": "warm_reciprocal_question",
    }


def _draft_generation_binding() -> dict[str, object]:
    return {
        "draft_evidence_id": "draft_evidence_fixture",
        "draft_generation_id": "draft_generation_fixture",
        "latest_turn_id": "latest_turn_fixture",
        "conversation_thread_revision": 1,
        "draft_self_review_summary": {
            "schema_version": 1,
            "status": "ok",
            "ai_or_weird_probability": 20,
            "attempts": 1,
            "source": "unit_fixture",
        },
    }

class GuiHarnessTestCase(unittest.TestCase):
    def setUp(self):
        self._sleep_patchers = [
            patch("dating_boost.apps.native_gui_session.time.sleep", return_value=None),
            patch("dating_boost.apps.tashuo.native.time.sleep", return_value=None),
        ]
        for patcher in self._sleep_patchers:
            patcher.start()
            self.addCleanup(patcher.stop)




def _profile_top_structure_png() -> bytes:
    width, height = 200, 400
    pixels = [[(0, 0, 0, 255) for _ in range(width)] for _ in range(height)]

    def fill(x1: float, y1: float, x2: float, y2: float, color: tuple[int, int, int, int]) -> None:
        for y in range(int(y1 * height), int(y2 * height)):
            for x in range(int(x1 * width), int(x2 * width)):
                pixels[y][x] = color

    fill(0.05, 0.08, 0.20, 0.18, (190, 120, 80, 255))
    fill(0.25, 0.13, 0.58, 0.19, (245, 245, 245, 255))
    fill(0.84, 0.10, 0.94, 0.18, (20, 20, 20, 255))
    fill(0.88, 0.13, 0.91, 0.15, (245, 245, 245, 255))
    fill(0.78, 0.89, 0.96, 0.97, (80, 80, 80, 255))
    fill(0.87, 0.91, 0.89, 0.95, (245, 245, 245, 255))

    raw_rows = []
    for row in pixels:
        raw_rows.append(b"\x00" + b"".join(bytes(pixel) for pixel in row))
    raw = b"".join(raw_rows)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            _png_chunk(b"IHDR", ihdr),
            _png_chunk(b"IDAT", zlib.compress(raw)),
            _png_chunk(b"IEND", b""),
        ]
    )


def _profile_tab_active_png() -> bytes:
    width, height = 200, 400
    pixels = [[(0, 0, 0, 255) for _ in range(width)] for _ in range(height)]

    def fill(x1: float, y1: float, x2: float, y2: float, color: tuple[int, int, int, int]) -> None:
        for y in range(int(y1 * height), int(y2 * height)):
            for x in range(int(x1 * width), int(x2 * width)):
                pixels[y][x] = color

    fill(0.03, 0.89, 0.97, 0.98, (18, 18, 18, 255))
    fill(0.78, 0.90, 0.96, 0.97, (82, 82, 82, 255))
    fill(0.86, 0.91, 0.90, 0.96, (246, 246, 246, 255))
    raw_rows = [b"\x00" + b"".join(bytes(pixel) for pixel in row) for row in pixels]
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            _png_chunk(b"IHDR", ihdr),
            _png_chunk(b"IDAT", zlib.compress(b"".join(raw_rows))),
            _png_chunk(b"IEND", b""),
        ]
    )


def _tinder_bottom_nav_png(active_tab: str) -> bytes:
    width, height = 200, 400
    pixels = [[(0, 0, 0, 255) for _ in range(width)] for _ in range(height)]

    def fill(x1: float, y1: float, x2: float, y2: float, color: tuple[int, int, int, int]) -> None:
        for y in range(int(y1 * height), int(y2 * height)):
            for x in range(int(x1 * width), int(x2 * width)):
                pixels[y][x] = color

    fill(0.04, 0.895, 0.96, 0.985, (18, 18, 18, 255))
    slots = [
        ("home", 0.07, 0.25),
        ("explore", 0.25, 0.41),
        ("likes", 0.41, 0.57),
        ("chats", 0.57, 0.74),
        ("profile", 0.74, 0.93),
    ]
    for name, x1, x2 in slots:
        center = (x1 + x2) / 2
        if name == active_tab:
            fill(x1 + 0.01, 0.905, x2 - 0.01, 0.972, (82, 82, 82, 255))
        fill(center - 0.025, 0.925, center + 0.025, 0.940, (238, 238, 238, 255))
        fill(center - 0.040, 0.952, center + 0.040, 0.965, (238, 238, 238, 255))
        if name == "likes":
            fill(center + 0.018, 0.920, center + 0.045, 0.940, (245, 210, 70, 255))

    return _png_from_pixels(pixels, width, height)


def _bumble_browse_png() -> bytes:
    width, height = 200, 400
    pixels = [[(255, 255, 255, 255) for _ in range(width)] for _ in range(height)]

    def fill(x1: float, y1: float, x2: float, y2: float, color: tuple[int, int, int, int]) -> None:
        for y in range(int(y1 * height), int(y2 * height)):
            for x in range(int(x1 * width), int(x2 * width)):
                pixels[y][x] = color

    fill(0.05, 0.10, 0.23, 0.13, (18, 18, 18, 255))
    fill(0.04, 0.18, 0.96, 0.88, (83, 132, 176, 255))
    fill(0.06, 0.73, 0.20, 0.81, (250, 214, 70, 255))
    fill(0.76, 0.70, 0.96, 0.82, (250, 214, 70, 255))
    fill(0.06, 0.89, 0.94, 0.98, (255, 255, 255, 255))
    for center in (0.11, 0.26, 0.50, 0.68, 0.88):
        fill(center - 0.020, 0.905, center + 0.020, 0.930, (80, 80, 80, 255))
        fill(center - 0.040, 0.948, center + 0.040, 0.965, (45, 45, 45, 255))
    return _png_from_pixels(pixels, width, height)


def _bumble_chat_list_png() -> bytes:
    width, height = 200, 400
    pixels = [[(255, 255, 255, 255) for _ in range(width)] for _ in range(height)]

    def fill(x1: float, y1: float, x2: float, y2: float, color: tuple[int, int, int, int]) -> None:
        for y in range(int(y1 * height), int(y2 * height)):
            for x in range(int(x1 * width), int(x2 * width)):
                pixels[y][x] = color

    fill(0.05, 0.105, 0.16, 0.135, (18, 18, 18, 255))
    fill(0.04, 0.20, 0.18, 0.30, (150, 105, 80, 255))
    fill(0.23, 0.20, 0.37, 0.30, (75, 130, 180, 255))
    fill(0.43, 0.20, 0.57, 0.30, (120, 120, 120, 255))
    fill(0.05, 0.36, 0.95, 0.45, (245, 245, 245, 255))
    fill(0.08, 0.38, 0.52, 0.43, (230, 230, 230, 255))
    fill(0.06, 0.50, 0.18, 0.59, (105, 160, 115, 255))
    fill(0.28, 0.50, 0.45, 0.52, (28, 28, 28, 255))
    fill(0.28, 0.535, 0.36, 0.55, (80, 80, 80, 255))
    fill(0.06, 0.89, 0.94, 0.98, (255, 255, 255, 255))
    for center in (0.11, 0.26, 0.50, 0.68):
        fill(center - 0.020, 0.905, center + 0.020, 0.930, (105, 105, 105, 255))
        fill(center - 0.040, 0.948, center + 0.040, 0.965, (90, 90, 90, 255))
    fill(0.86, 0.902, 0.92, 0.935, (18, 18, 18, 255))
    fill(0.84, 0.948, 0.92, 0.965, (18, 18, 18, 255))
    return _png_from_pixels(pixels, width, height)


def _bumble_conversation_png(*, active_send_button: bool = False, outgoing_bubble: bool = True) -> bytes:
    width, height = 200, 400
    pixels = [[(255, 255, 255, 255) for _ in range(width)] for _ in range(height)]

    def fill(x1: float, y1: float, x2: float, y2: float, color: tuple[int, int, int, int]) -> None:
        for y in range(int(y1 * height), int(y2 * height)):
            for x in range(int(x1 * width), int(x2 * width)):
                pixels[y][x] = color

    fill(0.15, 0.095, 0.23, 0.155, (105, 160, 115, 255))
    fill(0.27, 0.112, 0.40, 0.137, (25, 25, 25, 255))
    fill(0.66, 0.105, 0.72, 0.145, (35, 35, 35, 255))
    fill(0.79, 0.105, 0.86, 0.145, (35, 35, 35, 255))
    fill(0.92, 0.105, 0.96, 0.145, (35, 35, 35, 255))
    fill(0.40, 0.18, 0.96, 0.27, (245, 245, 245, 255))
    fill(0.05, 0.27, 0.18, 0.32, (245, 245, 245, 255))
    if outgoing_bubble:
        fill(0.80, 0.34, 0.96, 0.40, (248, 211, 59, 255))
    fill(0.12, 0.90, 0.88, 0.955, (248, 248, 248, 255))
    fill(0.16, 0.92, 0.21, 0.94, (95, 95, 95, 255))
    fill(0.93 if active_send_button else 0.91, 0.90, 0.98, 0.955, (248, 211, 59, 255) if active_send_button else (225, 225, 225, 255))
    return _png_from_pixels(pixels, width, height)


def _iphone_message_list_with_target_row_png(
    *,
    target_center_y: float,
    target_accent: tuple[int, int, int, int] = (92, 168, 126, 255),
) -> bytes:
    width, height = 200, 400
    pixels = [[(255, 255, 255, 255) for _ in range(width)] for _ in range(height)]

    def fill(x1: float, y1: float, x2: float, y2: float, color: tuple[int, int, int, int]) -> None:
        for y in range(max(0, int(y1 * height)), min(height, int(y2 * height))):
            for x in range(max(0, int(x1 * width)), min(width, int(x2 * width))):
                pixels[y][x] = color

    fill(0.00, 0.00, 1.00, 1.00, (255, 255, 255, 255))
    for center_y, accent, is_target in (
        (0.34, (190, 120, 90, 255), False),
        (target_center_y, target_accent, True),
        (0.82, (120, 130, 190, 255), False),
    ):
        y1 = center_y - 0.05
        y2 = center_y + 0.05
        fill(0.05, y1, 0.95, y2, (248, 248, 252, 255))
        if is_target:
            fill(0.08, y1 + 0.014, 0.20, y1 + 0.074, accent)
            fill(0.25, y1 + 0.014, 0.62, y1 + 0.036, (42, 42, 48, 255))
            fill(0.25, y1 + 0.055, 0.88, y1 + 0.074, accent)
            fill(0.70, y1 + 0.016, 0.88, y1 + 0.034, (245, 219, 70, 255))
        else:
            fill(0.08, y1 + 0.020, 0.18, y1 + 0.062, (220, 222, 232, 255))
            fill(0.25, y1 + 0.024, 0.76, y1 + 0.040, (190, 192, 202, 255))
    fill(0.00, 0.90, 1.00, 1.00, (255, 255, 255, 255))
    return _png_from_pixels(pixels, width, height)


def _tashuo_conversation_toolbar_png() -> bytes:
    width, height = 200, 400
    pixels = [[(255, 255, 255, 255) for _ in range(width)] for _ in range(height)]

    def fill(x1: float, y1: float, x2: float, y2: float, color: tuple[int, int, int, int]) -> None:
        for y in range(int(y1 * height), int(y2 * height)):
            for x in range(int(x1 * width), int(x2 * width)):
                pixels[y][x] = color

    fill(0.06, 0.845, 0.94, 0.902, (240, 240, 246, 255))
    for center in (0.14, 0.38, 0.62, 0.86):
        fill(center - 0.035, 0.920, center + 0.035, 0.945, (222, 222, 230, 255))
    return _png_from_pixels(pixels, width, height)


def _tashuo_mac_ios_app_conversation_toolbar_png() -> bytes:
    width, height = 288, 541
    pixels = [[(255, 255, 255, 255) for _ in range(width)] for _ in range(height)]

    def fill(x1: float, y1: float, x2: float, y2: float, color: tuple[int, int, int, int]) -> None:
        for y in range(int(y1 * height), int(y2 * height)):
            for x in range(int(x1 * width), int(x2 * width)):
                pixels[y][x] = color

    fill(0.03, 0.855, 0.97, 0.930, (246, 246, 250, 255))
    for x1, x2 in ((0.07, 0.20), (0.30, 0.43), (0.54, 0.67), (0.78, 0.93)):
        fill(x1 + 0.035, 0.944, x2 - 0.035, 0.979, (238, 238, 246, 255))
    return _png_from_pixels(pixels, width, height)


def _tashuo_mac_ios_app_conversation_with_title_chrome_png() -> bytes:
    width, height = 288, 541
    pixels = [[(255, 255, 255, 255) for _ in range(width)] for _ in range(height)]

    def fill(x1: float, y1: float, x2: float, y2: float, color: tuple[int, int, int, int]) -> None:
        for y in range(int(y1 * height), int(y2 * height)):
            for x in range(int(x1 * width), int(x2 * width)):
                pixels[y][x] = color

    fill(0.0, 0.0, 1.0, 0.055, (246, 242, 244, 255))
    fill(0.04, 0.095, 0.095, 0.135, (35, 35, 35, 255))
    fill(0.42, 0.105, 0.58, 0.128, (25, 25, 25, 255))
    fill(0.84, 0.110, 0.94, 0.126, (35, 35, 35, 255))
    fill(0.07, 0.25, 0.30, 0.31, (246, 246, 250, 255))
    fill(0.72, 0.48, 0.94, 0.55, (210, 242, 252, 255))
    fill(0.07, 0.61, 0.34, 0.68, (246, 246, 250, 255))
    fill(0.62, 0.73, 0.96, 0.80, (210, 242, 252, 255))
    fill(0.03, 0.805, 0.97, 0.888, (246, 246, 250, 255))
    for x1, x2 in ((0.07, 0.20), (0.30, 0.43), (0.54, 0.67), (0.78, 0.93)):
        fill(x1 + 0.035, 0.940, x2 - 0.035, 0.975, (226, 226, 236, 255))
    return _png_from_pixels(pixels, width, height)


def _tashuo_mac_ios_app_conversation_with_messages_png(
    *,
    accent: tuple[int, int, int, int] = (92, 168, 126, 255),
    outgoing_bubble: bool = True,
    outgoing_color: tuple[int, int, int, int] = (248, 211, 59, 255),
) -> bytes:
    width, height = 288, 541
    pixels = [[(255, 255, 255, 255) for _ in range(width)] for _ in range(height)]

    def fill(x1: float, y1: float, x2: float, y2: float, color: tuple[int, int, int, int]) -> None:
        for y in range(int(y1 * height), int(y2 * height)):
            for x in range(int(x1 * width), int(x2 * width)):
                pixels[y][x] = color

    fill(0.04, 0.095, 0.095, 0.135, (35, 35, 35, 255))
    fill(0.42, 0.105, 0.58, 0.128, (25, 25, 25, 255))
    fill(0.07, 0.23, 0.49, 0.30, (246, 246, 250, 255))
    if outgoing_bubble:
        fill(0.72, 0.36, 0.93, 0.42, outgoing_color)
    fill(0.07, 0.50, 0.56, 0.58, (246, 246, 250, 255))
    fill(0.10, 0.515, 0.42, 0.535, accent)
    fill(0.10, 0.545, 0.30, 0.560, accent)
    fill(0.03, 0.855, 0.97, 0.930, (246, 246, 250, 255))
    for x1, x2 in ((0.07, 0.20), (0.30, 0.43), (0.54, 0.67), (0.78, 0.93)):
        fill(x1 + 0.035, 0.944, x2 - 0.035, 0.979, (238, 238, 246, 255))
    return _png_from_pixels(pixels, width, height)


def _tashuo_mac_ios_app_conversation_notification_prompt_png() -> bytes:
    width, height = 288, 541
    pixels = [[(255, 255, 255, 255) for _ in range(width)] for _ in range(height)]

    def fill(x1: float, y1: float, x2: float, y2: float, color: tuple[int, int, int, int]) -> None:
        for y in range(int(y1 * height), int(y2 * height)):
            for x in range(int(x1 * width), int(x2 * width)):
                pixels[y][x] = color

    fill(0.04, 0.095, 0.095, 0.135, (35, 35, 35, 255))
    fill(0.37, 0.098, 0.45, 0.145, (28, 28, 32, 255))
    fill(0.47, 0.110, 0.63, 0.132, (28, 28, 32, 255))
    fill(0.84, 0.115, 0.94, 0.128, (35, 35, 35, 255))
    fill(0.00, 0.155, 1.00, 0.340, (255, 255, 255, 255))
    fill(0.29, 0.190, 0.71, 0.218, (24, 24, 28, 255))
    fill(0.23, 0.232, 0.77, 0.258, (132, 132, 145, 255))
    fill(0.34, 0.262, 0.66, 0.305, (111, 74, 237, 255))
    fill(0.90, 0.165, 0.94, 0.190, (205, 205, 212, 255))
    fill(0.00, 0.340, 1.00, 1.00, (249, 249, 253, 255))
    return _png_from_pixels(pixels, width, height)


def _tashuo_mac_ios_app_message_list_with_target_row_png(
    *,
    target_center_y: float,
    target_accent: tuple[int, int, int, int] = (92, 168, 126, 255),
) -> bytes:
    width, height = 288, 541
    pixels = [[(255, 255, 255, 255) for _ in range(width)] for _ in range(height)]

    def fill(x1: float, y1: float, x2: float, y2: float, color: tuple[int, int, int, int]) -> None:
        for y in range(int(y1 * height), int(y2 * height)):
            for x in range(int(x1 * width), int(x2 * width)):
                pixels[y][x] = color

    fill(0.00, 0.00, 1.00, 1.00, (255, 255, 255, 255))
    fill(0.04, 0.08, 0.30, 0.12, (25, 25, 25, 255))
    for center_y, accent, is_target in (
        (0.26, (190, 120, 90, 255), False),
        (target_center_y, target_accent, True),
        (0.78, (120, 130, 190, 255), False),
    ):
        y1 = center_y - 0.05
        y2 = center_y + 0.05
        fill(0.05, y1, 0.95, y2, (248, 248, 252, 255))
        if is_target:
            fill(0.08, y1 + 0.014, 0.20, y1 + 0.074, accent)
            fill(0.25, y1 + 0.014, 0.62, y1 + 0.036, (42, 42, 48, 255))
            fill(0.25, y1 + 0.055, 0.88, y1 + 0.074, accent)
            fill(0.70, y1 + 0.016, 0.88, y1 + 0.034, (245, 219, 70, 255))
        else:
            fill(0.08, y1 + 0.020, 0.18, y1 + 0.062, (220, 222, 232, 255))
            fill(0.25, y1 + 0.024, 0.76, y1 + 0.040, (190, 192, 202, 255))
    fill(0.00, 0.90, 1.00, 1.00, (255, 255, 255, 255))
    fill(0.56, 0.93, 0.66, 0.985, (111, 74, 237, 255))
    return _png_from_pixels(pixels, width, height)


def _tashuo_mac_ios_app_profile_png() -> bytes:
    width, height = 288, 541
    pixels = [[(255, 255, 255, 255) for _ in range(width)] for _ in range(height)]

    def fill(x1: float, y1: float, x2: float, y2: float, color: tuple[int, int, int, int]) -> None:
        for y in range(int(y1 * height), int(y2 * height)):
            for x in range(int(x1 * width), int(x2 * width)):
                pixels[y][x] = color

    fill(0.00, 0.08, 1.00, 0.76, (72, 92, 118, 255))
    fill(0.12, 0.12, 0.94, 0.58, (134, 82, 72, 255))
    fill(0.06, 0.12, 0.11, 0.18, (245, 245, 245, 255))
    fill(0.08, 0.66, 0.34, 0.70, (245, 245, 245, 255))
    fill(0.08, 0.72, 0.42, 0.75, (245, 245, 245, 255))
    fill(0.00, 0.76, 1.00, 1.00, (255, 255, 255, 255))
    fill(0.05, 0.80, 0.95, 0.985, (244, 246, 255, 255))
    fill(0.10, 0.88, 0.31, 0.94, (234, 238, 252, 255))
    fill(0.38, 0.88, 0.62, 0.94, (234, 238, 252, 255))
    fill(0.69, 0.88, 0.92, 0.94, (234, 238, 252, 255))
    return _png_from_pixels(pixels, width, height)


def _tashuo_mac_ios_app_pending_question_list_png() -> bytes:
    width, height = 288, 541
    pixels = [[(255, 255, 255, 255) for _ in range(width)] for _ in range(height)]

    def fill(x1: float, y1: float, x2: float, y2: float, color: tuple[int, int, int, int]) -> None:
        for y in range(int(y1 * height), int(y2 * height)):
            for x in range(int(x1 * width), int(x2 * width)):
                pixels[y][x] = color

    fill(0.00, 0.00, 1.00, 1.00, (248, 249, 253, 255))
    fill(0.04, 0.095, 0.095, 0.135, (28, 28, 32, 255))
    fill(0.42, 0.105, 0.58, 0.132, (28, 28, 32, 255))
    fill(0.26, 0.185, 0.42, 0.215, (106, 68, 238, 255))
    fill(0.33, 0.224, 0.40, 0.232, (106, 68, 238, 255))
    fill(0.62, 0.185, 0.78, 0.215, (28, 28, 32, 255))
    fill(0.27, 0.335, 0.73, 0.55, (210, 218, 236, 255))
    fill(0.32, 0.37, 0.44, 0.50, (80, 98, 126, 255))
    fill(0.26, 0.59, 0.74, 0.635, (28, 28, 32, 255))
    fill(0.28, 0.67, 0.72, 0.72, (116, 120, 132, 255))
    return _png_from_pixels(pixels, width, height)


def _tashuo_mac_ios_app_profile_mid_png() -> bytes:
    return _tashuo_mac_ios_app_profile_png()


def _tashuo_mac_ios_app_profile_bottom_png() -> bytes:
    width, height = 288, 541
    pixels = [[(255, 255, 255, 255) for _ in range(width)] for _ in range(height)]

    def fill(x1: float, y1: float, x2: float, y2: float, color: tuple[int, int, int, int]) -> None:
        for y in range(int(y1 * height), int(y2 * height)):
            for x in range(int(x1 * width), int(x2 * width)):
                pixels[y][x] = color

    fill(0.00, 0.08, 1.00, 0.47, (236, 240, 252, 255))
    fill(0.08, 0.12, 0.48, 0.16, (154, 170, 235, 255))
    fill(0.08, 0.20, 0.22, 0.30, (180, 120, 95, 255))
    fill(0.25, 0.20, 0.39, 0.30, (195, 75, 60, 255))
    fill(0.42, 0.20, 0.56, 0.30, (76, 126, 196, 255))
    fill(0.59, 0.20, 0.73, 0.30, (70, 158, 196, 255))
    fill(0.76, 0.20, 0.84, 0.30, (224, 229, 248, 255))
    fill(0.00, 0.47, 1.00, 0.86, (236, 240, 252, 255))
    fill(0.08, 0.56, 0.44, 0.60, (154, 170, 235, 255))
    fill(0.08, 0.64, 0.42, 0.70, (32, 34, 40, 255))
    fill(0.08, 0.92, 0.92, 0.965, (248, 250, 255, 255))
    fill(0.40, 0.938, 0.60, 0.948, (96, 102, 126, 255))
    return _png_from_pixels(pixels, width, height)


def _tashuo_mac_ios_app_profile_closing_transition_png() -> bytes:
    width, height = 288, 541
    pixels = [[(248, 248, 252, 255) for _ in range(width)] for _ in range(height)]

    def fill(x1: float, y1: float, x2: float, y2: float, color: tuple[int, int, int, int]) -> None:
        for y in range(int(y1 * height), int(y2 * height)):
            for x in range(int(x1 * width), int(x2 * width)):
                pixels[y][x] = color

    fill(0.00, 0.08, 0.62, 0.78, (248, 248, 252, 255))
    fill(0.62, 0.08, 1.00, 0.76, (104, 82, 76, 255))
    fill(0.68, 0.66, 0.96, 0.75, (245, 245, 245, 255))
    fill(0.62, 0.80, 1.00, 1.00, (255, 255, 255, 255))
    return _png_from_pixels(pixels, width, height)


def _tashuo_recommend_bottom_nav_png() -> bytes:
    return _tashuo_top_level_bottom_nav_png("recommend")


def _tashuo_messages_bottom_nav_png() -> bytes:
    return _tashuo_top_level_bottom_nav_png("messages")


def _tashuo_messages_top_anchor_png() -> bytes:
    width, height = 288, 541
    pixels = [[(255, 255, 255, 255) for _ in range(width)] for _ in range(height)]

    def fill(x1: float, y1: float, x2: float, y2: float, color: tuple[int, int, int, int]) -> None:
        for y in range(int(y1 * height), int(y2 * height)):
            for x in range(int(x1 * width), int(x2 * width)):
                pixels[y][x] = color

    fill(0.00, 0.90, 1.00, 1.00, (255, 255, 255, 255))
    fill(0.08, 0.46, 0.22, 0.58, (154, 130, 112, 255))
    fill(0.27, 0.49, 0.74, 0.52, (30, 30, 34, 255))
    fill(0.27, 0.55, 0.62, 0.57, (180, 182, 192, 255))
    slots = {
        "recommend": 0.15,
        "flight": 0.38,
        "messages": 0.60,
        "mine": 0.86,
    }
    for name, center in slots.items():
        active = name == "messages"
        color = (111, 74, 237, 255) if active else (145, 145, 160, 255)
        icon_half_width = 0.030 if active else 0.020
        label_half_width = 0.030 if active else 0.018
        fill(center - icon_half_width, 0.930, center + icon_half_width, 0.968, color)
        fill(center - label_half_width, 0.980, center + label_half_width, 0.990, color)
    return _png_from_pixels(pixels, width, height)


def _tashuo_liked_you_modal_png() -> bytes:
    width, height = 288, 541
    pixels = [[(18, 18, 22, 255) for _ in range(width)] for _ in range(height)]

    def fill(x1: float, y1: float, x2: float, y2: float, color: tuple[int, int, int, int]) -> None:
        for y in range(int(y1 * height), int(y2 * height)):
            for x in range(int(x1 * width), int(x2 * width)):
                pixels[y][x] = color

    fill(0.08, 0.25, 0.92, 0.80, (255, 255, 255, 255))
    fill(0.34, 0.30, 0.66, 0.36, (42, 42, 48, 255))
    fill(0.18, 0.41, 0.82, 0.47, (236, 236, 242, 255))
    fill(0.22, 0.50, 0.78, 0.55, (236, 236, 242, 255))
    fill(0.14, 0.62, 0.86, 0.72, (111, 74, 237, 255))
    fill(0.30, 0.72, 0.70, 0.80, (255, 255, 255, 255))
    fill(0.40, 0.745, 0.60, 0.765, (70, 70, 78, 255))
    return _png_from_pixels(pixels, width, height)


def _tashuo_recommend_content_with_messages_tab_png() -> bytes:
    width, height = 288, 541
    pixels = [[(255, 255, 255, 255) for _ in range(width)] for _ in range(height)]

    def fill(x1: float, y1: float, x2: float, y2: float, color: tuple[int, int, int, int]) -> None:
        for y in range(int(y1 * height), int(y2 * height)):
            for x in range(int(x1 * width), int(x2 * width)):
                pixels[y][x] = color

    fill(0.04, 0.16, 0.96, 0.88, (88, 138, 185, 255))
    fill(0.08, 0.22, 0.92, 0.72, (126, 172, 198, 255))
    fill(0.08, 0.70, 0.48, 0.84, (34, 44, 48, 255))
    fill(0.78, 0.44, 0.96, 0.56, (111, 74, 237, 255))
    fill(0.78, 0.66, 0.96, 0.78, (245, 70, 96, 255))
    fill(0.00, 0.90, 1.00, 1.00, (255, 255, 255, 255))
    slots = {
        "recommend": 0.15,
        "flight": 0.38,
        "messages": 0.60,
        "mine": 0.86,
    }
    for name, center in slots.items():
        active = name == "messages"
        color = (111, 74, 237, 255) if active else (145, 145, 160, 255)
        icon_half_width = 0.030 if active else 0.020
        label_half_width = 0.030 if active else 0.018
        fill(center - icon_half_width, 0.930, center + icon_half_width, 0.968, color)
        fill(center - label_half_width, 0.980, center + label_half_width, 0.990, color)
    return _png_from_pixels(pixels, width, height)


def _tashuo_top_level_bottom_nav_png(active_tab: str) -> bytes:
    width, height = 288, 541
    pixels = [[(255, 255, 255, 255) for _ in range(width)] for _ in range(height)]

    def fill(x1: float, y1: float, x2: float, y2: float, color: tuple[int, int, int, int]) -> None:
        for y in range(int(y1 * height), int(y2 * height)):
            for x in range(int(x1 * width), int(x2 * width)):
                pixels[y][x] = color

    fill(0.00, 0.90, 1.00, 1.00, (255, 255, 255, 255))
    slots = {
        "recommend": 0.15,
        "flight": 0.38,
        "messages": 0.60,
        "mine": 0.86,
    }
    for name, center in slots.items():
        active = name == active_tab
        color = (111, 74, 237, 255) if active else (145, 145, 160, 255)
        icon_half_width = 0.030 if active else 0.020
        label_half_width = 0.030 if active else 0.018
        fill(center - icon_half_width, 0.930, center + icon_half_width, 0.968, color)
        fill(center - label_half_width, 0.980, center + label_half_width, 0.990, color)
    return _png_from_pixels(pixels, width, height)


def _spotlight_search_bottom_png() -> bytes:
    width, height = 200, 400
    pixels = [[(0, 0, 0, 255) for _ in range(width)] for _ in range(height)]

    def fill(x1: float, y1: float, x2: float, y2: float, color: tuple[int, int, int, int]) -> None:
        for y in range(int(y1 * height), int(y2 * height)):
            for x in range(int(x1 * width), int(x2 * width)):
                pixels[y][x] = color

    fill(0.06, 0.905, 0.94, 0.955, (34, 34, 34, 255))
    fill(0.10, 0.922, 0.14, 0.937, (235, 235, 235, 255))
    fill(0.18, 0.923, 0.37, 0.938, (235, 235, 235, 255))
    fill(0.86, 0.918, 0.90, 0.942, (235, 235, 235, 255))
    fill(0.12, 0.958, 0.32, 0.990, (35, 115, 245, 255))
    fill(0.35, 0.958, 0.45, 0.990, (190, 190, 190, 255))
    return _png_from_pixels(pixels, width, height)


def _tinder_conversation_send_button_png() -> bytes:
    width, height = 200, 400
    pixels = [[(0, 0, 0, 255) for _ in range(width)] for _ in range(height)]

    def fill(x1: float, y1: float, x2: float, y2: float, color: tuple[int, int, int, int]) -> None:
        for y in range(int(y1 * height), int(y2 * height)):
            for x in range(int(x1 * width), int(x2 * width)):
                pixels[y][x] = color

    fill(0.04, 0.90, 0.13, 0.98, (35, 35, 35, 255))
    fill(0.15, 0.91, 0.86, 0.975, (25, 25, 25, 255))
    fill(0.20, 0.93, 0.72, 0.95, (230, 230, 230, 255))
    fill(0.875, 0.905, 0.955, 0.985, (12, 116, 235, 255))
    fill(0.905, 0.925, 0.925, 0.965, (245, 245, 245, 255))
    return _png_from_pixels(pixels, width, height)


def _png_from_pixels(pixels: list[list[tuple[int, int, int, int]]], width: int, height: int) -> bytes:
    raw_rows = [b"\x00" + b"".join(bytes(pixel) for pixel in row) for row in pixels]
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            _png_chunk(b"IHDR", ihdr),
            _png_chunk(b"IDAT", zlib.compress(b"".join(raw_rows))),
            _png_chunk(b"IEND", b""),
        ]
    )


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)


def _png_average_hash(png: bytes, *, region: dict[str, float], grid_size: int = 8) -> str:
    width, height, rows = _read_test_png_pixels(png)
    x1 = max(0, min(width - 1, int(float(region["x1"]) * width)))
    x2 = max(x1 + 1, min(width, int(float(region["x2"]) * width)))
    y1 = max(0, min(height - 1, int(float(region["y1"]) * height)))
    y2 = max(y1 + 1, min(height, int(float(region["y2"]) * height)))
    values: list[float] = []
    for cell_y in range(grid_size):
        start_y = y1 + int((y2 - y1) * cell_y / grid_size)
        end_y = y1 + int((y2 - y1) * (cell_y + 1) / grid_size)
        for cell_x in range(grid_size):
            start_x = x1 + int((x2 - x1) * cell_x / grid_size)
            end_x = x1 + int((x2 - x1) * (cell_x + 1) / grid_size)
            total = 0.0
            count = 0
            for y in range(start_y, max(start_y + 1, end_y)):
                for x in range(start_x, max(start_x + 1, end_x)):
                    r, g, b, _a = rows[y][x]
                    total += (0.299 * r) + (0.587 * g) + (0.114 * b)
                    count += 1
            values.append(total / max(1, count))
    average = sum(values) / len(values)
    bits = "".join("1" if value >= average else "0" for value in values)
    return f"{int(bits, 2):0{grid_size * grid_size // 4}x}"


def _read_test_png_pixels(png: bytes) -> tuple[int, int, list[list[tuple[int, int, int, int]]]]:
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("not a png")
    pos = 8
    width = height = channels = None
    raw = b""
    while pos < len(png):
        length = struct.unpack(">I", png[pos : pos + 4])[0]
        pos += 4
        chunk_type = png[pos : pos + 4]
        pos += 4
        chunk = png[pos : pos + length]
        pos += length + 4
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(
                ">IIBBBBB",
                chunk,
            )
            if bit_depth != 8 or color_type != 6 or compression != 0 or filter_method != 0 or interlace != 0:
                raise ValueError("unsupported png")
            channels = 4
        elif chunk_type == b"IDAT":
            raw += chunk
        elif chunk_type == b"IEND":
            break
    if width is None or height is None or channels is None:
        raise ValueError("missing png header")
    scanlines = zlib.decompress(raw)
    rows: list[list[tuple[int, int, int, int]]] = []
    index = 0
    for _ in range(height):
        filter_type = scanlines[index]
        index += 1
        if filter_type != 0:
            raise ValueError("unsupported png filter")
        row_bytes = scanlines[index : index + width * channels]
        index += width * channels
        row = [
            tuple(row_bytes[column : column + channels])  # type: ignore[misc]
            for column in range(0, len(row_bytes), channels)
        ]
        rows.append(row)
    return width, height, rows


if __name__ == "__main__":
    unittest.main()

__all__ = [
    'json', 'hashlib', 're', 'struct',
    'tempfile', 'unittest', 'zlib', 'contextmanager',
    'redirect_stdout', 'StringIO', 'Path', 'patch',
    'create_adapter', 'tashuo_native', 'SUPPORTED_NATIVE_HARNESS_APPS', 'main',
    'classify_bumble_screen_text', 'classify_screen_text', 'classify_wechat_screen_text', 'classify_tashuo_capture',
    'classify_tashuo_screen_image', 'classify_tashuo_screen_text', 'combine_tashuo_screen_states', 'tashuo_layout_hints',
    'tashuo_thread_cues_from_text', 'core_graphics_command_v', 'core_graphics_drag', 'WindowInfo',
    'FakeRunner', '_result', '_run_cli_json', '_select_runtime_scope',
    '_patch_cli_adapter', '_ocr_tsv_for_line', '_write_json', '_write_draft_review_audit',
    '_live_send_auth', '_autonomous_audit_binding', '_planner_evidence', '_draft_generation_binding',
    'GuiHarnessTestCase', '_profile_top_structure_png', '_profile_tab_active_png', '_tinder_bottom_nav_png',
    '_bumble_browse_png', '_bumble_chat_list_png', '_bumble_conversation_png', '_iphone_message_list_with_target_row_png',
    '_tashuo_conversation_toolbar_png', '_tashuo_mac_ios_app_conversation_toolbar_png', '_tashuo_mac_ios_app_conversation_with_title_chrome_png', '_tashuo_mac_ios_app_conversation_with_messages_png',
    '_tashuo_mac_ios_app_conversation_notification_prompt_png', '_tashuo_mac_ios_app_message_list_with_target_row_png', '_tashuo_mac_ios_app_profile_png', '_tashuo_mac_ios_app_pending_question_list_png',
    '_tashuo_mac_ios_app_profile_mid_png', '_tashuo_mac_ios_app_profile_bottom_png', '_tashuo_mac_ios_app_profile_closing_transition_png', '_tashuo_recommend_bottom_nav_png',
    '_tashuo_messages_bottom_nav_png', '_tashuo_messages_top_anchor_png', '_tashuo_liked_you_modal_png', '_tashuo_recommend_content_with_messages_tab_png',
    '_tashuo_top_level_bottom_nav_png', '_spotlight_search_bottom_png', '_tinder_conversation_send_button_png', '_png_from_pixels',
    '_png_chunk', '_png_average_hash', '_read_test_png_pixels',
]

from pathlib import Path
from dataclasses import replace

import pytest

from dating_boost.harness.base import WindowInfo, parse_window_info, window_from_payload
from dating_boost.harness.native_gui import NativeGuiHarness
from dating_boost.harness.window_capture import capture_window_image, core_graphics_window_lookup_script
from tests.gui_harness_support import FakeRunner, create_adapter, _result


WINDOW = WindowInfo(
    frontmost=True, x=100, y=50, width=350, height=760, name="她说", process_pid=35218,
)


def cg_row(window=WINDOW, window_id=1713):
    return (
        f"{window.x}\t{window.y}\t{window.width}\t{window.height}\t{window_id}\t"
        f"{window.process_pid}\t{str(window.frontmost).lower()}\t{window.name}\n"
    )


class WindowRunner(FakeRunner):
    def __init__(self, responses):
        super().__init__(ocr_text="", window_name="她说")
        self.responses = list(responses)

    def run(self, command, *, input=None):
        if command[:3] == ["xcrun", "swift", "-e"] and "CGWindowListCopyWindowInfo" in command[-1]:
            self.commands.append(command)
            value = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
            return _result(stdout=value)
        return super().run(command, input=input)


@pytest.mark.parametrize("app_specific", [False, True])
def test_mac_ios_capture_requires_process_identity(tmp_path: Path, app_specific: bool):
    runner = FakeRunner(ocr_text="", window_name="她说")
    harness = (
        create_adapter(app_id="tashuo", runtime="mac_ios_app", platform="darwin", runner=runner)
        if app_specific else NativeGuiHarness(
            platform="darwin", runner=runner, runtime="mac_ios_app", window_title="她说",
        )
    )
    window = WindowInfo(frontmost=True, x=100, y=50, width=350, height=760, name="她说")

    result = harness.capture_window(output=tmp_path / "capture.png", window=window, ocr=False)

    assert result["status"] == "blocked"
    assert result["reason"] == "mac_ios_window_process_identity_missing"
    assert not any(command[0] == "screencapture" for command in runner.commands)


@pytest.mark.parametrize("app_specific", [False, True])
def test_both_capture_entries_bind_owner_and_geometry_without_shadow(tmp_path, app_specific):
    runner = WindowRunner([cg_row()])
    harness = (
        create_adapter(app_id="tashuo", runtime="mac_ios_app", platform="darwin", runner=runner)
        if app_specific else NativeGuiHarness(platform="darwin", runner=runner, runtime="mac_ios_app")
    )
    result = harness.capture_window(output=tmp_path / "capture.png", window=WINDOW, ocr=False)
    assert result["status"] == "ok"
    captures = [command for command in runner.commands if command[0] == "screencapture"]
    assert captures == [["screencapture", "-x", "-o", "-l", "1713", str(tmp_path / "capture.png")]]
    assert sum("CGWindowListCopyWindowInfo" in command[-1] for command in runner.commands) == 2
    assert not any("NSWorkspace.shared.runningApplications" in command[-1] for command in runner.commands)


@pytest.mark.parametrize(("rows", "reason"), [
    (cg_row(replace(WINDOW, process_pid=999)), "mac_ios_window_binding_changed"),
    (cg_row(replace(WINDOW, x=101)), "mac_ios_window_binding_changed"),
    (cg_row(replace(WINDOW, width=351)), "mac_ios_window_binding_changed"),
    (cg_row() + cg_row(window_id=1714), "mac_ios_window_binding_ambiguous"),
    ("", "mac_ios_window_binding_changed"),
    ("100\t50\t350\t760\t1713\t她说\n", "mac_ios_window_lookup_failed"),
])
@pytest.mark.parametrize("after_capture", [False, True])
def test_capture_rejects_mismatched_or_ambiguous_binding(tmp_path, rows, reason, after_capture):
    runner = WindowRunner(([cg_row()] if after_capture else []) + [rows])
    output = tmp_path / "capture.png"
    result = capture_window_image(runner, WINDOW, output, require_process_binding=True)
    assert result == {"status": "blocked", "reason": reason}
    assert runner.screenshot_calls == int(after_capture)
    assert not output.exists()


def test_supplied_window_id_is_revalidated_and_cannot_select_among_duplicates(tmp_path):
    runner = WindowRunner([cg_row(window_id=1714)])
    result = capture_window_image(
        runner, replace(WINDOW, window_id=1713), tmp_path / "capture.png", require_process_binding=True,
    )
    assert result["reason"] == "mac_ios_window_binding_changed"
    assert runner.screenshot_calls == 0


def test_replacement_with_same_owner_and_geometry_during_capture_is_rejected(tmp_path):
    runner = WindowRunner([cg_row(), cg_row(window_id=1714)])
    result = capture_window_image(runner, WINDOW, tmp_path / "capture.png", require_process_binding=True)
    assert result["reason"] == "mac_ios_window_binding_changed"
    assert runner.screenshot_calls == 1


def test_window_id_capture_remains_bound_when_another_app_is_frontmost(tmp_path):
    runner = WindowRunner([cg_row(replace(WINDOW, frontmost=False))])
    assert capture_window_image(runner, WINDOW, tmp_path / "capture.png", require_process_binding=True)["status"] == "ok"


def test_unrelated_runtime_keeps_rectangle_capture(tmp_path):
    runner = FakeRunner(ocr_text="")
    result = capture_window_image(runner, WINDOW, tmp_path / "capture.png", require_process_binding=False)
    assert result["status"] == "ok"
    assert runner.commands == [["screencapture", "-x", "-R", "100,50,350,760", str(tmp_path / "capture.png")]]


def test_ax_window_pid_is_from_same_observation_and_roundtrips():
    window = parse_window_info("true, 100, 50, 350, 760, title, with comma, 35218", include_process_pid=True)
    assert window is not None
    assert window.name == "title, with comma"
    assert window.process_pid == 35218
    assert window_from_payload(window.to_dict()) == window
    assert parse_window_info("true, 100, 50, 350, 760, title", include_process_pid=True) is None


@pytest.mark.parametrize("suffix", [cg_row(window_id=1714), cg_row(replace(WINDOW, process_pid=999))])
def test_cg_fallback_requires_single_eligible_window_owned_by_resolved_pid(suffix):
    runner = WindowRunner([cg_row(replace(WINDOW, frontmost=False)) + suffix])
    harness = NativeGuiHarness(platform="darwin", runner=runner, runtime="mac_ios_app")
    window = harness._mac_ios_core_graphics_window_info(["她说"])
    if "\t999\t" in suffix:
        assert window is not None and window.frontmost is False and window.process_pid == 35218
    else:
        assert window is None


def test_cg_fallback_ignores_small_overlay_without_inventing_frontmost():
    overlay = replace(WINDOW, width=100, height=20)
    runner = WindowRunner([cg_row(overlay, 1714) + cg_row(replace(WINDOW, frontmost=False))])
    harness = NativeGuiHarness(platform="darwin", runner=runner, runtime="mac_ios_app")
    window = harness._mac_ios_core_graphics_window_info(["她说"])
    assert window is not None and window.window_id == 1713 and window.frontmost is False


def test_lookup_script_has_strict_pid_layer_and_real_frontmost_contract():
    script = core_graphics_window_lookup_script(pids=[35218], candidates=["same name"])
    assert "targetPids.contains(pid)" in script
    assert "exactInt(window[kCGWindowLayer as String]) == 0" in script
    assert "NSWorkspace.shared.frontmostApplication?.processIdentifier" in script
    assert "same name" not in script
    assert "haystack" not in script


def test_doctor_propagates_capture_binding_failure():
    runner = WindowRunner([cg_row(replace(WINDOW, process_pid=999))])
    harness = create_adapter(app_id="tashuo", runtime="mac_ios_app", platform="darwin", runner=runner)
    result = harness.doctor(capture=True)
    assert result["status"] == "blocked"
    assert result["reason"] == "mac_ios_window_binding_changed"

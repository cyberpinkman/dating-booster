"""Capture a native app window by its observed owner and exact geometry."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dating_boost.harness.base import WindowInfo, short


def core_graphics_window_lookup_script(*, pids: list[int], candidates: list[str] | None = None) -> str:
    # Names are deliberately not capture identities. Keep the optional argument
    # for callers of the historical lookup helper.
    pid_literal = ", ".join(str(pid) for pid in pids if type(pid) is int and pid > 0)
    return r'''
import AppKit
import CoreGraphics
import Foundation

let targetPids = Set<Int>([PID_VALUES])
let frontPid = NSWorkspace.shared.frontmostApplication?.processIdentifier
let options = CGWindowListOption(arrayLiteral: [.optionOnScreenOnly, .excludeDesktopElements])
let windows = (CGWindowListCopyWindowInfo(options, CGWindowID(0)) as? [[String: Any]]) ?? []

func exactInt(_ value: Any?) -> Int? {
    guard let number = value as? NSNumber else { return nil }
    let value = number.doubleValue
    guard value.isFinite && value.rounded() == value else { return nil }
    return Int(exactly: value)
}

func cleaned(_ value: String) -> String {
    return value.replacingOccurrences(of: "\t", with: " ").replacingOccurrences(of: "\n", with: " ")
}

for window in windows {
    guard exactInt(window[kCGWindowLayer as String]) == 0,
          let pid = exactInt(window[kCGWindowOwnerPID as String]), targetPids.contains(pid),
          let bounds = window[kCGWindowBounds as String] as? [String: Any],
          let x = exactInt(bounds["X"]), let y = exactInt(bounds["Y"]),
          let width = exactInt(bounds["Width"]), let height = exactInt(bounds["Height"]),
          let windowNumber = exactInt(window[kCGWindowNumber as String]),
          width > 0, height > 0, windowNumber > 0 else { continue }
    let owner = (window[kCGWindowOwnerName as String] as? String) ?? ""
    let title = (window[kCGWindowName as String] as? String) ?? ""
    let name = cleaned(title.isEmpty ? owner : title)
    let frontmost = frontPid == pid_t(pid)
    print("\(x)\t\(y)\t\(width)\t\(height)\t\(windowNumber)\t\(pid)\t\(frontmost)\t\(name)")
}
'''.replace("PID_VALUES", pid_literal)


def parse_core_graphics_windows(stdout: str) -> list[WindowInfo] | None:
    windows = []
    for line in stdout.splitlines():
        parts = line.split("\t", 7)
        if len(parts) != 8 or parts[6] not in {"true", "false"}:
            return None
        try:
            x, y, width, height, window_id, pid = (int(value) for value in parts[:6])
        except ValueError:
            return None
        if min(width, height, window_id, pid) <= 0:
            return None
        windows.append(WindowInfo(
            frontmost=parts[6] == "true", x=x, y=y, width=width, height=height,
            name=parts[7].strip() or "mac_ios_app", window_id=window_id, process_pid=pid,
        ))
    return windows


def _bound_window(runner: Any, expected: WindowInfo) -> WindowInfo:
    if type(expected.process_pid) is not int or expected.process_pid <= 0:
        raise ValueError("mac_ios_window_process_identity_missing")
    script = core_graphics_window_lookup_script(pids=[expected.process_pid])
    result = runner.run(["xcrun", "swift", "-e", script])
    windows = parse_core_graphics_windows(result.stdout) if result.returncode == 0 else None
    if windows is None:
        raise ValueError("mac_ios_window_lookup_failed")
    matching = [window for window in windows if (
        window.process_pid == expected.process_pid
        and (window.x, window.y, window.width, window.height)
        == (expected.x, expected.y, expected.width, expected.height)
    )]
    if not matching:
        raise ValueError("mac_ios_window_binding_changed")
    if len(matching) != 1:
        raise ValueError("mac_ios_window_binding_ambiguous")
    selected = matching[0]
    if expected.window_id is not None and selected.window_id != expected.window_id:
        raise ValueError("mac_ios_window_binding_changed")
    return selected


def capture_window_image(
    runner: Any, window: WindowInfo, output: Path, *, require_process_binding: bool,
) -> dict[str, Any]:
    """Return success only when one owner/window/rectangle brackets capture.

    mac-ios-app never falls back to a desktop rectangle, which can contain an
    unrelated foreground app even when AX reports the target as frontmost.
    """
    if require_process_binding:
        if type(window.process_pid) is not int or window.process_pid <= 0:
            return {"status": "blocked", "reason": "mac_ios_window_process_identity_missing"}
        try:
            window = _bound_window(runner, window)
        except ValueError as error:
            return {"status": "blocked", "reason": str(error)}
    output.parent.mkdir(parents=True, exist_ok=True)
    if window.window_id is not None:
        flags = ["-o"] if require_process_binding else []
        command = ["screencapture", "-x", *flags, "-l", str(window.window_id), str(output)]
    else:
        command = ["screencapture", "-x", "-R", f"{window.x},{window.y},{window.width},{window.height}", str(output)]
    result = runner.run(command)
    if result.returncode != 0:
        return {"status": "blocked", "reason": "screenshot_failed", "stderr": short(result.stderr)}
    if require_process_binding:
        try:
            _bound_window(runner, window)
        except ValueError as error:
            output.unlink(missing_ok=True)
            return {"status": "blocked", "reason": str(error)}
    return {"status": "ok"}

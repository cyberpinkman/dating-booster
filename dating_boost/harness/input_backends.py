from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from dating_boost.harness.base import short


INPUT_BACKEND_CONTRACT_SCHEMA_VERSION = 2


def _backend_contract() -> dict[str, int]:
    return {"input_backend_contract_schema_version": INPUT_BACKEND_CONTRACT_SCHEMA_VERSION}


def core_graphics_click(runner: Any, x: int, y: int) -> dict[str, Any]:
    script_path = _core_graphics_click_script_path()
    script_path.write_text(CORE_GRAPHICS_CLICK_SWIFT, encoding="utf-8")
    result = runner.run(["xcrun", "swift", str(script_path), str(x), str(y)])
    if result.returncode != 0:
        return {
            "status": "blocked",
            "reason": "core_graphics_click_failed",
            "stderr": short(result.stderr),
            **_backend_contract(),
        }
    return {"status": "ok", "point": {"x": x, "y": y}, "input_backend": "core_graphics", **_backend_contract()}


def core_graphics_drag(
    runner: Any,
    *,
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    duration_seconds: float,
) -> dict[str, Any]:
    script_path = _core_graphics_drag_script_path()
    script_path.write_text(CORE_GRAPHICS_DRAG_SWIFT, encoding="utf-8")
    result = runner.run(
        [
            "xcrun",
            "swift",
            str(script_path),
            str(start_x),
            str(start_y),
            str(end_x),
            str(end_y),
            str(max(0.05, duration_seconds)),
        ]
    )
    if result.returncode != 0:
        return {
            "status": "blocked",
            "reason": "core_graphics_drag_failed",
            "stderr": short(result.stderr),
            **_backend_contract(),
        }
    return {
        "status": "ok",
        "from": {"x": start_x, "y": start_y},
        "to": {"x": end_x, "y": end_y},
        "duration_seconds": duration_seconds,
        "input_backend": "core_graphics",
        **_backend_contract(),
    }


def core_graphics_wheel(
    runner: Any,
    *,
    x: int,
    y: int,
    delta_y: int,
    delta_x: int,
    repeats: int,
    interval_us: int,
) -> dict[str, Any]:
    script_path = _core_graphics_wheel_script_path()
    script_path.write_text(CORE_GRAPHICS_WHEEL_SWIFT, encoding="utf-8")
    result = runner.run(
        [
            "xcrun",
            "swift",
            str(script_path),
            str(x),
            str(y),
            str(delta_y),
            str(delta_x),
            str(repeats),
            str(interval_us),
        ]
    )
    if result.returncode != 0:
        return {
            "status": "blocked",
            "reason": "core_graphics_wheel_failed",
            "stderr": short(result.stderr),
            **_backend_contract(),
        }
    return {
        "status": "ok",
        "point": {"x": x, "y": y},
        "delta": {"x": delta_x, "y": delta_y},
        "repeats": repeats,
        "input_backend": "core_graphics_wheel",
        **_backend_contract(),
    }


def core_graphics_command_v(runner: Any) -> dict[str, Any]:
    script_path = _core_graphics_command_v_script_path()
    script_path.write_text(CORE_GRAPHICS_COMMAND_V_SWIFT, encoding="utf-8")
    result = runner.run(["xcrun", "swift", str(script_path)])
    if result.returncode != 0:
        return {
            "status": "blocked",
            "reason": "core_graphics_command_v_failed",
            "stderr": short(result.stderr),
            **_backend_contract(),
        }
    return {"status": "ok", "input_backend": "core_graphics_keyboard", **_backend_contract()}


def click_iphone_mirroring_view_menu_item(runner: Any, *, window_title: str, item_name: str) -> dict[str, Any]:
    result = runner.run(
        [
            "osascript",
            "-e",
            (
                f'tell application "System Events" to tell process "{window_title}" '
                f'to click menu item "{item_name}" of menu "View" of menu bar 1'
            ),
        ]
    )
    if result.returncode != 0:
        return {
            "status": "blocked",
            "reason": "iphone_mirroring_view_menu_failed",
            "stderr": short(result.stderr),
            **_backend_contract(),
        }
    return {"status": "ok", "menu_item": item_name, "input_backend": "applescript_menu", **_backend_contract()}


def _core_graphics_click_script_path() -> Path:
    return Path(tempfile.gettempdir()) / "dating_boost_core_graphics_click.swift"


def _core_graphics_drag_script_path() -> Path:
    return Path(tempfile.gettempdir()) / "dating_boost_core_graphics_drag.swift"


def _core_graphics_wheel_script_path() -> Path:
    return Path(tempfile.gettempdir()) / "dating_boost_core_graphics_wheel.swift"


def _core_graphics_command_v_script_path() -> Path:
    return Path(tempfile.gettempdir()) / "dating_boost_core_graphics_command_v.swift"


CORE_GRAPHICS_CLICK_SWIFT = """\
import CoreGraphics
import Foundation

let x = Double(CommandLine.arguments[1])!
let y = Double(CommandLine.arguments[2])!
let point = CGPoint(x: x, y: y)
let source = CGEventSource(stateID: .hidSystemState)
let down = CGEvent(mouseEventSource: source, mouseType: .leftMouseDown, mouseCursorPosition: point, mouseButton: .left)
down?.post(tap: .cghidEventTap)
usleep(70000)
let up = CGEvent(mouseEventSource: source, mouseType: .leftMouseUp, mouseCursorPosition: point, mouseButton: .left)
up?.post(tap: .cghidEventTap)
"""


CORE_GRAPHICS_DRAG_SWIFT = """\
import CoreGraphics
import Foundation

let startX = Double(CommandLine.arguments[1])!
let startY = Double(CommandLine.arguments[2])!
let endX = Double(CommandLine.arguments[3])!
let endY = Double(CommandLine.arguments[4])!
let duration = Double(CommandLine.arguments[5])!
let steps = max(4, Int(duration / 0.016))
let source = CGEventSource(stateID: .hidSystemState)
let start = CGPoint(x: startX, y: startY)
let down = CGEvent(mouseEventSource: source, mouseType: .leftMouseDown, mouseCursorPosition: start, mouseButton: .left)
down?.post(tap: .cghidEventTap)
for step in 1...steps {
    let t = Double(step) / Double(steps)
    let point = CGPoint(x: startX + (endX - startX) * t, y: startY + (endY - startY) * t)
    CGEvent(mouseEventSource: source, mouseType: .leftMouseDragged, mouseCursorPosition: point, mouseButton: .left)?
        .post(tap: .cghidEventTap)
    usleep(useconds_t(duration * 1_000_000.0 / Double(steps)))
}
let end = CGPoint(x: endX, y: endY)
let up = CGEvent(mouseEventSource: source, mouseType: .leftMouseUp, mouseCursorPosition: end, mouseButton: .left)
up?.post(tap: .cghidEventTap)
"""


CORE_GRAPHICS_WHEEL_SWIFT = """\
import CoreGraphics
import Foundation

let x = Double(CommandLine.arguments[1])!
let y = Double(CommandLine.arguments[2])!
let deltaY = Int32(CommandLine.arguments[3])!
let deltaX = Int32(CommandLine.arguments[4])!
let repeats = max(1, Int(CommandLine.arguments[5])!)
let intervalUs = useconds_t(max(1000, Int(CommandLine.arguments[6])!))
let point = CGPoint(x: x, y: y)
let source = CGEventSource(stateID: .hidSystemState)
CGEvent(mouseEventSource: source, mouseType: .mouseMoved, mouseCursorPosition: point, mouseButton: .left)?
    .post(tap: .cghidEventTap)
usleep(50000)
for _ in 0..<repeats {
    CGEvent(scrollWheelEvent2Source: source, units: .pixel, wheelCount: 2, wheel1: deltaY, wheel2: deltaX, wheel3: 0)?
        .post(tap: .cghidEventTap)
    usleep(intervalUs)
}
"""


CORE_GRAPHICS_COMMAND_V_SWIFT = """\
import CoreGraphics
import Foundation

let source = CGEventSource(stateID: .hidSystemState)
let keyCodeV = CGKeyCode(9)
let flags = CGEventFlags.maskCommand

let down = CGEvent(keyboardEventSource: source, virtualKey: keyCodeV, keyDown: true)
down?.flags = flags
down?.post(tap: .cghidEventTap)
usleep(80000)
let up = CGEvent(keyboardEventSource: source, virtualKey: keyCodeV, keyDown: false)
up?.flags = flags
up?.post(tap: .cghidEventTap)
"""

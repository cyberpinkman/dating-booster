from __future__ import annotations

from dataclasses import dataclass
import re
import shutil
import subprocess
from typing import Any


@dataclass(frozen=True)
class WindowInfo:
    frontmost: bool
    x: int
    y: int
    width: int
    height: int
    name: str
    window_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "frontmost": self.frontmost,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "name": self.name,
        }
        if self.window_id is not None:
            payload["window_id"] = self.window_id
        return payload


class SubprocessRunner:
    def run(self, command: list[str], *, input: str | None = None) -> subprocess.CompletedProcess[str]:
        if command[:2] == ["command", "-v"] and len(command) == 3:
            path = shutil.which(command[2])
            return subprocess.CompletedProcess(
                command,
                0 if path else 1,
                stdout=f"{path}\n" if path else "",
                stderr="",
            )
        return subprocess.run(command, input=input, capture_output=True, text=True, check=False)


def parse_window_info(stdout: str) -> WindowInfo | None:
    match = re.search(
        r"^\s*(true|false),\s*(-?\d+),\s*(-?\d+),\s*(\d+),\s*(\d+),\s*(.+?)\s*$",
        stdout.strip(),
        re.IGNORECASE,
    )
    if not match:
        return None
    return WindowInfo(
        frontmost=match.group(1).lower() == "true",
        x=int(match.group(2)),
        y=int(match.group(3)),
        width=int(match.group(4)),
        height=int(match.group(5)),
        name=match.group(6),
    )


def window_from_payload(payload: dict[str, Any]) -> WindowInfo:
    return WindowInfo(
        frontmost=bool(payload.get("frontmost")),
        x=int(payload["x"]),
        y=int(payload["y"]),
        width=int(payload["width"]),
        height=int(payload["height"]),
        name=str(payload["name"]),
        window_id=int(payload["window_id"]) if payload.get("window_id") is not None else None,
    )


def short(text: str, limit: int = 300) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "..."

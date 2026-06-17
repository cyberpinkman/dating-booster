from __future__ import annotations

from dataclasses import dataclass, field
from numbers import Real
from typing import Any, Mapping


STEP_OPERATION_KEYS = ("tap_ratio", "swipe", "wheel")


@dataclass(frozen=True)
class HarnessStep:
    intent: str
    tap_ratio: Mapping[str, Any] | None = None
    swipe: Mapping[str, Any] | None = None
    wheel: Mapping[str, Any] | None = None
    risk: str | None = "navigation_only"
    fields: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"intent": self.intent}
        if self.tap_ratio is not None:
            payload["tap_ratio"] = dict(self.tap_ratio)
        if self.swipe is not None:
            payload["swipe"] = _copy_nested_mapping(self.swipe)
        if self.wheel is not None:
            payload["wheel"] = dict(self.wheel)
        if self.risk is not None:
            payload["risk"] = self.risk
        payload.update(dict(self.fields))
        reason = harness_step_validation_reason(payload)
        if reason is not None:
            raise ValueError(reason)
        return payload


def tap_step(intent: str, *, x: float, y: float, risk: str | None = "navigation_only", **fields: Any) -> dict[str, Any]:
    return HarnessStep(intent=intent, tap_ratio={"x": x, "y": y}, risk=risk, fields=fields).to_dict()


def swipe_step(
    intent: str,
    *,
    from_x: float,
    from_y: float,
    to_x: float,
    to_y: float,
    duration_ms: int = 350,
    risk: str | None = "navigation_only",
    **fields: Any,
) -> dict[str, Any]:
    return HarnessStep(
        intent=intent,
        swipe={
            "from": {"x": from_x, "y": from_y},
            "to": {"x": to_x, "y": to_y},
            "duration_ms": duration_ms,
        },
        risk=risk,
        fields=fields,
    ).to_dict()


def wheel_step(
    intent: str,
    *,
    x: float,
    y: float,
    delta_y: int = 0,
    delta_x: int = 0,
    repeats: int = 18,
    interval_us: int = 18000,
    risk: str | None = "navigation_only",
    **fields: Any,
) -> dict[str, Any]:
    return HarnessStep(
        intent=intent,
        wheel={
            "x": x,
            "y": y,
            "delta_y": delta_y,
            "delta_x": delta_x,
            "repeats": repeats,
            "interval_us": interval_us,
        },
        risk=risk,
        fields=fields,
    ).to_dict()


def marker_step(intent: str, *, risk: str | None = "navigation_only", **fields: Any) -> dict[str, Any]:
    return HarnessStep(intent=intent, risk=risk, fields=fields).to_dict()


def harness_step_validation_reason(step: object) -> str | None:
    if not isinstance(step, Mapping):
        return "gui_step_not_mapping"
    intent = step.get("intent")
    if not isinstance(intent, str) or not intent.strip():
        return "gui_step_intent_required"
    operation_keys = [key for key in STEP_OPERATION_KEYS if key in step]
    if len(operation_keys) > 1:
        return "gui_step_has_multiple_operations"
    if not operation_keys:
        return None
    operation_key = operation_keys[0]
    if operation_key == "tap_ratio":
        return _validate_ratio_point(step.get("tap_ratio"), reason_prefix="gui_step_tap_ratio")
    if operation_key == "swipe":
        return _validate_swipe(step.get("swipe"))
    if operation_key == "wheel":
        return _validate_wheel(step.get("wheel"))
    return None


def _copy_nested_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    copied: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, Mapping):
            copied[str(key)] = dict(item)
        else:
            copied[str(key)] = item
    return copied


def _validate_ratio_point(value: Any, *, reason_prefix: str) -> str | None:
    if not isinstance(value, Mapping):
        return f"{reason_prefix}_not_mapping"
    for key in ("x", "y"):
        if key not in value:
            return f"{reason_prefix}_{key}_required"
        if not _is_real_number(value[key]):
            return f"{reason_prefix}_{key}_not_numeric"
        coordinate = float(value[key])
        if not 0.0 <= coordinate <= 1.0:
            return f"{reason_prefix}_{key}_out_of_range"
    return None


def _validate_swipe(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return "gui_step_swipe_not_mapping"
    for key in ("from", "to"):
        reason = _validate_ratio_point(value.get(key), reason_prefix=f"gui_step_swipe_{key}")
        if reason is not None:
            return reason
    if "duration_ms" in value:
        if not _is_integer_number(value["duration_ms"]):
            return "gui_step_swipe_duration_ms_not_integer"
        duration_ms = int(value["duration_ms"])
        if duration_ms < 0:
            return "gui_step_swipe_duration_ms_negative"
    return None


def _validate_wheel(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return "gui_step_wheel_not_mapping"
    reason = _validate_ratio_point(value, reason_prefix="gui_step_wheel")
    if reason is not None:
        return reason
    for key in ("delta_y", "delta_x", "repeats", "interval_us"):
        if key not in value:
            continue
        if not _is_integer_number(value[key]):
            return f"gui_step_wheel_{key}_not_integer"
        integer_value = int(value[key])
        if key in {"repeats", "interval_us"} and integer_value < 1:
            return f"gui_step_wheel_{key}_not_positive"
    return None


def _is_real_number(value: Any) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool)


def _is_integer_number(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)

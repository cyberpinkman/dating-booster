from datetime import datetime
import time

import pytest

from dating_boost.apps.tashuo.standalone_production_contract import ContractViolation, canonicalize_authorization
from dating_boost.core.automation_send_gate import _send_authorization_block_reason
from dating_boost.core.live_send_contract import (
    live_send_authorization_block_reason,
    live_send_authorization_quiet_hours_block_reason,
    managed_live_send_guidance,
)
from dating_boost.core.managed_run import ManagedAuthorization
from dating_boost.core.managed_session import _authorization_block_reason


pytestmark = pytest.mark.managed_critical


@pytest.fixture
def shanghai_clock(monkeypatch):
    if not hasattr(time, "tzset"):
        pytest.skip("process timezone control required")
    with monkeypatch.context() as environment:
        environment.setenv("TZ", "Asia/Shanghai")
        time.tzset()
        yield
    time.tzset()


def authorization(windows):
    return {
        "schema_version": 1, "authorization_id": "test", "app_id": "tashuo",
        "scope": "send_chat_messages", "allowed_actions": ["send_message"],
        "allowed_match_ids": [], "goal_ids": [], "autonomous_send": True, "live_send": True,
        "requires_post_action_verification": True, "created_at": "2026-01-01T00:00:00Z",
        "expires_at": "2027-01-01T00:00:00Z", "quiet_hours": windows,
    }


@pytest.mark.parametrize("instant,expected", [
    ("2026-11-06T14:59:59Z", None),
    ("2026-11-06T15:00:00Z", "authorization_quiet_hours"),
    ("2026-11-06T16:30:00Z", "authorization_quiet_hours"),
    ("2026-11-07T00:30:00+08:00", "authorization_quiet_hours"),
    ("2026-11-06T23:59:59Z", "authorization_quiet_hours"),
    ("2026-11-07T00:00:00Z", None),
])
def test_overnight_window_uses_host_local_half_open_interval(shanghai_clock, instant, expected):
    assert live_send_authorization_quiet_hours_block_reason(
        ("23:00-08:00",), now=instant,
    ) == expected


def test_approval_and_execution_check_the_same_local_clock(shanghai_clock):
    instant = "2026-11-06T16:30:00Z"
    now = datetime.fromisoformat(instant)
    auth = authorization([{"start_time": "23:00", "end_time": "08:00"}])
    expected = "authorization_quiet_hours"
    assert live_send_authorization_block_reason(auth, app_id="tashuo", now=instant) == expected
    assert _authorization_block_reason(auth, instant) == expected
    assert _send_authorization_block_reason(auth, match_id="row", app_id="tashuo", now=instant) == expected
    assert ManagedAuthorization.from_dict(auth).session_block_reason(
        app_id="tashuo", runtime="mac-ios-app", now=now,
    ) == expected
    stage_only = {**auth, "live_send": False}
    with pytest.raises(ContractViolation) as failure:
        canonicalize_authorization(stage_only, now=now)
    assert failure.value.details["field"] == "quiet_hours"
    assert canonicalize_authorization(stage_only, now=datetime.fromisoformat("2026-11-07T00:00:00Z"))


@pytest.mark.parametrize("bad", [False, 0, "", {}, "23:00-08:00"])
def test_malformed_serialized_container_cannot_disable_quiet_hours(bad):
    with pytest.raises(ValueError, match="^authorization_quiet_hours_invalid$"):
        ManagedAuthorization.from_dict(authorization(bad))


def test_invalid_later_window_is_rejected_even_when_first_is_active(shanghai_clock):
    windows = [{"start": "23:00", "end": "08:00"}, {"start": "08:00", "end": "08:00"}]
    assert live_send_authorization_quiet_hours_block_reason(
        windows, now="2026-11-06T23:10:00+08:00",
    ) == "authorization_quiet_hours_invalid"


def test_active_quiet_hours_give_wait_guidance():
    assert managed_live_send_guidance("authorization_quiet_hours")["next_host_action"] == "wait_until_quiet_hours_end"

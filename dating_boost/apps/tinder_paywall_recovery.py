from __future__ import annotations

from typing import Any


def apply_tinder_paywall_recovery_result(payload: dict[str, Any], recovery: dict[str, Any]) -> None:
    payload["subscription_paywall_recovery"] = recovery
    payload["next_host_action"] = "navigate_to_verified_tinder_conversation_and_retry_send"
    if recovery.get("status") == "ok":
        payload.update({"status": "blocked", "reason": "tinder_subscription_paywall_dismissed"})
    else:
        payload.update(
            {
                "status": "blocked",
                "reason": recovery.get("reason") or "tinder_subscription_paywall_recovery_failed",
            }
        )

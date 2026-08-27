from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest


pytestmark = pytest.mark.nightly_lab

from dating_boost.apps.tashuo.standalone_production_contract import (
    ATTEMPT_TIMEOUT_SECONDS,
    CANARY_CYCLE_COUNT,
    CANARY_VALIDITY_SECONDS,
    PROTOCOL_VERSION,
    REASON_SCHEMA_VERSION,
    SELECTION_PROBE_TIMEOUT_SECONDS,
    SOAK_CYCLE_COUNT,
    SOAK_INTERVAL_NS,
    SOAK_MIN_DURATION_NS,
    ContractViolation,
    QualificationBinding,
    SelectionProbeBinding,
    build_canary_schedule,
    build_soak_schedule,
    build_environment_fingerprint,
    can_retry_reason,
    canonical_digest,
    canonicalize_authorization,
    compute_canary_accept_token,
    compute_config_hash,
    derive_claim,
    derive_terminal_state,
    environment_fingerprints_match,
    transition_finalization,
    transition_outcome,
    validate_canary_metrics,
    validate_soak_metrics,
)


def _authorization(**overrides):
    payload = {
        "schema_version": 1,
        "authorization_id": "auth_qualification",
        "app_id": "tashuo",
        "scope": "send_chat_messages",
        "allowed_actions": ["send_message"],
        "allowed_match_ids": [],
        "goal_ids": [],
        "autonomous_send": True,
        "autonomous_nudge": False,
        "live_send": False,
        "requires_post_action_verification": True,
        "quiet_hours": [],
        "created_at": "2026-07-01T00:00:00Z",
        "expires_at": "2099-01-01T00:00:00Z",
        "revoked_at": None,
    }
    payload.update(overrides)
    return payload


def _canary_metrics(**overrides):
    metrics = {
        "committed_cycles": 10,
        "successful_cycles": 10,
        "first_attempt_successes": 10,
        "retried_cycles": 0,
        "total_attempts": 10,
        "message_list_cycles": 8,
        "current_thread_cycles": 2,
        "safety_violations": 0,
        "terminal_audits": 10,
        "completed_stage_results": 10,
        "attempt_outcomes": 10,
        "receipts": 10,
        "phase_cleanup_ok": True,
        "support_bundle_ok": True,
        "hash_chain_ok": True,
        "sqlite_quick_check": "ok",
    }
    metrics.update(overrides)
    return metrics


def _soak_metrics(**overrides):
    starts = [index * SOAK_INTERVAL_NS for index in range(SOAK_CYCLE_COUNT)]
    metrics = {
        "committed_cycles": 100,
        "terminal_cycle_successes": 100,
        "first_attempt_successes": 100,
        "retried_cycles": 0,
        "total_attempts": 100,
        "message_list_cycles": 80,
        "current_thread_cycles": 20,
        "safety_violations": 0,
        "actual_start_ns": starts,
        "boot_session_unchanged": True,
        "environment_matches_canary": True,
        "phase_cleanup_ok": True,
        "support_bundles_ok": True,
        "artifacts_ok": True,
        "hash_chain_ok": True,
        "sqlite_quick_check": "ok",
    }
    metrics.update(overrides)
    return metrics


def test_protocol_thresholds_are_fixed_and_not_rounding_down():
    assert PROTOCOL_VERSION
    assert REASON_SCHEMA_VERSION == 1
    assert CANARY_CYCLE_COUNT == 10
    assert SOAK_CYCLE_COUNT == 100
    assert SOAK_MIN_DURATION_NS == 8 * 60 * 60 * 1_000_000_000
    assert SOAK_INTERVAL_NS * 99 >= SOAK_MIN_DURATION_NS
    assert (SOAK_INTERVAL_NS - 1) * 99 < SOAK_MIN_DURATION_NS
    assert CANARY_VALIDITY_SECONDS == 24 * 60 * 60
    assert SELECTION_PROBE_TIMEOUT_SECONDS == 120
    assert ATTEMPT_TIMEOUT_SECONDS == 300


def test_canary_schedule_has_exact_surface_sequence_and_predecessors():
    schedule = build_canary_schedule("qual_1")

    assert len(schedule) == 10
    assert [slot["mode"] for slot in schedule].count("message-list") == 8
    assert [slot["mode"] for slot in schedule].count("current-thread") == 2
    assert schedule[2]["mode"] == "current-thread"
    assert schedule[2]["predecessor_planned_slot_id"] == schedule[1]["planned_slot_id"]
    assert schedule[7]["mode"] == "current-thread"
    assert schedule[7]["predecessor_planned_slot_id"] == schedule[6]["planned_slot_id"]
    assert len({slot["planned_slot_id"] for slot in schedule}) == 10


def test_soak_schedule_is_exactly_eighty_twenty_in_nominal_groups():
    schedule = build_soak_schedule("qual_1")

    assert len(schedule) == 100
    assert [slot["mode"] for slot in schedule].count("message-list") == 80
    assert [slot["mode"] for slot in schedule].count("current-thread") == 20
    for group in range(20):
        block = schedule[group * 5 : group * 5 + 5]
        assert [slot["mode"] for slot in block] == [
            "message-list",
            "message-list",
            "message-list",
            "message-list",
            "current-thread",
        ]
        assert block[-1]["predecessor_planned_slot_id"] == block[-2]["planned_slot_id"]


def test_outcome_state_machine_accepts_only_declared_edges():
    assert transition_outcome("created", "preflight_passed") == "preflight_passed"
    assert transition_outcome("preflight_passed", "canary_running") == "canary_running"
    assert transition_outcome("canary_running", "canary_passed") == "canary_passed"
    assert transition_outcome("canary_passed", "soak_running") == "soak_running"
    assert transition_outcome("soak_running", "soak_criteria_met") == "soak_criteria_met"
    assert transition_outcome("canary_running", "qualification_blocked") == "qualification_blocked"
    assert transition_outcome("canary_passed", "qualification_expired") == "qualification_expired"
    with pytest.raises(ContractViolation, match="outcome_transition_invalid"):
        transition_outcome("canary_passed", "soak_criteria_met")
    with pytest.raises(ContractViolation, match="outcome_terminal"):
        transition_outcome("qualification_blocked", "canary_running")


def test_finalization_state_machine_and_terminal_mapping_are_independent():
    states = [
        "open",
        "evidence_written",
        "provisional_validated",
        "purge_pending",
        "purged",
        "bundle_sealed",
        "bundle_validated",
        "manifest_published",
        "validated",
    ]
    current = states[0]
    for target in states[1:]:
        current = transition_finalization(current, target)
    assert current == "validated"
    assert derive_terminal_state("soak_criteria_met", "validated") == "protocol_passed"
    assert derive_terminal_state("qualification_blocked", "validated") == "blocked_finalized"
    assert derive_terminal_state("qualification_expired", "validated") == "expired_finalized"
    assert derive_terminal_state("canary_passed", "validated") is None


@pytest.mark.parametrize(
    "reason",
    [
        "model_timeout",
        "vision_timeout",
        "app_launch_transient",
        "capture_transient",
        "prepare_message_page_transient",
        "exact_target_relocation_transient",
        "worker_timeout_before_mutation",
    ],
)
def test_retry_allowlist_is_exact_before_mutation(reason):
    assert can_retry_reason(reason, mutation_phase="pre_stage_revalidated", safe_recovery_complete=False)


@pytest.mark.parametrize("reason", ["", "unknown", "command_failed:2", "target_mismatch"])
def test_unknown_or_parameterized_reason_is_never_retryable(reason):
    assert not can_retry_reason(reason, mutation_phase="not_started", safe_recovery_complete=True)


def test_post_mutation_retry_requires_complete_safe_recovery():
    assert not can_retry_reason(
        "model_timeout",
        mutation_phase="stage_mutation_intent",
        safe_recovery_complete=False,
    )
    assert can_retry_reason(
        "model_timeout",
        mutation_phase="stage_mutation_intent",
        safe_recovery_complete=True,
    )


def test_bindings_reject_missing_or_wrong_scope_fields():
    binding = QualificationBinding(
        qualification_id="qual_1",
        phase="canary",
        cycle_index=1,
        attempt_id="attempt_1",
        local_fencing_token=1,
        runtime_fencing_token=7,
    )
    assert QualificationBinding.from_dict(binding.to_dict()) == binding
    with pytest.raises(ContractViolation, match="qualification_binding_invalid"):
        QualificationBinding.from_dict({**binding.to_dict(), "attempt_id": ""})
    with pytest.raises(ContractViolation, match="qualification_binding_invalid"):
        QualificationBinding.from_dict({**binding.to_dict(), "phase": "other"})

    probe = SelectionProbeBinding(
        qualification_id="qual_1",
        phase="soak",
        planned_slot_id="slot_1",
        probe_id="probe_1",
        local_fencing_token=2,
        runtime_fencing_token=8,
    )
    assert SelectionProbeBinding.from_dict(probe.to_dict()) == probe


def test_authorization_is_canonical_and_stage_only():
    now = datetime(2026, 7, 13, tzinfo=UTC)
    result = canonicalize_authorization(_authorization(), now=now)

    assert result["payload"]["app_id"] == "tashuo"
    assert result["payload"]["live_send"] is False
    assert result["digest"] == canonical_digest(result["payload"])

    invalid = [
        _authorization(app_id="tinder"),
        _authorization(live_send=True),
        _authorization(autonomous_send=False),
        _authorization(requires_post_action_verification=False),
        _authorization(allowed_actions=[]),
        _authorization(revoked_at="2026-07-12T00:00:00Z"),
        _authorization(expires_at=(now - timedelta(seconds=1)).isoformat()),
    ]
    for payload in invalid:
        with pytest.raises(ContractViolation, match="authorization_invalid"):
            canonicalize_authorization(payload, now=now)


def test_config_hash_and_canary_token_are_canonical_and_bound():
    fingerprint = {"tool_version": "1", "python": {"version": "3.13"}}
    protocol = {"canary_cycles": 10, "soak_cycles": 100}
    config_hash = compute_config_hash(fingerprint, protocol)
    assert config_hash == compute_config_hash(
        {"python": {"version": "3.13"}, "tool_version": "1"},
        {"soak_cycles": 100, "canary_cycles": 10},
    )
    token = compute_canary_accept_token(
        qualification_id="qual_1",
        config_hash=config_hash,
        canary_chain_root="chain_1",
        canary_certificate_digest="cert_1",
    )
    assert token != compute_canary_accept_token(
        qualification_id="qual_2",
        config_hash=config_hash,
        canary_chain_root="chain_1",
        canary_certificate_digest="cert_1",
    )


def test_canary_metrics_reject_nine_of_ten_and_any_retry():
    assert validate_canary_metrics(_canary_metrics())["passed"] is True
    assert validate_canary_metrics(_canary_metrics(successful_cycles=9))["passed"] is False
    assert validate_canary_metrics(
        _canary_metrics(retried_cycles=1, total_attempts=11, first_attempt_successes=9)
    )["passed"] is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"terminal_cycle_successes": 98},
        {"first_attempt_successes": 98},
        {"retried_cycles": 2, "total_attempts": 102},
        {"message_list_cycles": 79, "current_thread_cycles": 21},
        {"environment_matches_canary": False},
        {"safety_violations": 1},
    ],
)
def test_soak_metrics_reject_counterexamples(overrides):
    assert validate_soak_metrics(_soak_metrics(**overrides))["passed"] is False


def test_soak_metrics_require_every_adjacent_interval_and_full_duration():
    assert validate_soak_metrics(_soak_metrics())["passed"] is True
    starts = _soak_metrics()["actual_start_ns"]
    starts[50] = starts[49] + SOAK_INTERVAL_NS - 1
    assert validate_soak_metrics(_soak_metrics(actual_start_ns=starts))["passed"] is False


def test_claim_is_derived_without_generalized_production_or_reliability_language():
    canary = derive_claim("canary_passed", qualification_id="qual_1", config_hash="cfg", manifest_digest="manifest")
    assert canary["claim_code"] == "CANARY_PASSED_SOAK_NOT_RUN"
    assert "soak not run; qualification not passed" in canary["text"]

    passed = derive_claim("protocol_passed", qualification_id="qual_1", config_hash="cfg", manifest_digest="manifest")
    assert passed["claim_code"] == "PROTOCOL_PASSED_PINNED_ENVIRONMENT"
    assert "qualification protocol passed for the pinned environment" in passed["text"]
    assert "production ready" not in passed["text"].lower()
    assert "99%" not in passed["text"]


def _environment_components(**overrides):
    components = {
        "tool_version": "1.0",
        "execution": {"mode": "source_checkout", "git_commit": "abc", "tree_digest": "tree", "clean": True},
        "loaded_package_digest": "package",
        "dependency_snapshot_digest": "dependencies",
        "python": {"implementation": "CPython", "version": "3.13.1"},
        "system": {"product_version": "15.5", "build_version": "24F74", "architecture": "arm64", "boot_session_id": "boot"},
        "display": {"logical_bounds": [0, 0, 1920, 1080], "pixel_bounds": [0, 0, 3840, 2160], "scale_factor": 2.0, "appearance": "dark", "locale": "zh_CN"},
        "permissions": {"accessibility": True, "screen_recording": True},
        "tashuo": {"bundle_id": "com.intelcupid.tashuo", "short_version": "1.2", "build_version": "3", "executable_digest": "app"},
        "runtime": {"app_id": "tashuo", "runtime": "mac-ios-app", "send_mode": "stage", "managed_gui_send": False, "staging_input_backend": "guarded_macos_accessibility", "runtime_lock_protocol_version": 1},
        "user_model_snapshot_digest": "snapshot",
        "model": {"backend": "minimax", "vision_backend": "minimax", "model_identifier": "MiniMax-M3", "vision_model_identifier": "MiniMax-M3", "base_url": "https://api.example/v1", "api_key_env": "MINIMAX_API_KEY", "provider_identifier": "deployment_1"},
        "authorization_digest": "authorization",
    }
    components.update(overrides)
    return components


def test_environment_fingerprint_binds_credential_without_exposing_key():
    fingerprint = build_environment_fingerprint(
        _environment_components(),
        qualification_salt="qualification-salt",
        credential="raw-secret-key",
    )

    assert fingerprint["credential_fingerprint"]
    assert "raw-secret-key" not in str(fingerprint)
    assert fingerprint["model_pin_level"] == "deployment_identifier"
    assert fingerprint["protocol"]["attempt_timeout_seconds"] == 300


def test_environment_fingerprint_rejects_dirty_source_and_missing_permissions():
    with pytest.raises(ContractViolation, match="environment_dirty_source_checkout"):
        build_environment_fingerprint(
            _environment_components(execution={"mode": "source_checkout", "clean": False}),
            qualification_salt="salt",
            credential="key",
        )
    with pytest.raises(ContractViolation, match="environment_permission_missing"):
        build_environment_fingerprint(
            _environment_components(permissions={"accessibility": True, "screen_recording": False}),
            qualification_salt="salt",
            credential="key",
        )


def test_environment_without_provider_revision_has_explicit_limited_pin_level():
    components = _environment_components()
    components["model"] = {**components["model"], "provider_identifier": None}
    fingerprint = build_environment_fingerprint(components, qualification_salt="salt", credential="key")
    assert fingerprint["model"]["provider_identifier"] == "revision_unavailable"
    assert fingerprint["model_pin_level"] == "endpoint_identifier_only"


def test_environment_equality_is_field_exact_and_reports_drift_fields():
    first = build_environment_fingerprint(_environment_components(), qualification_salt="salt", credential="key")
    second = build_environment_fingerprint(_environment_components(), qualification_salt="salt", credential="key")
    assert environment_fingerprints_match(first, second) == {"matches": True, "drift_fields": []}

    changed = {**second, "dependency_snapshot_digest": "changed"}
    result = environment_fingerprints_match(first, changed)
    assert result["matches"] is False
    assert "dependency_snapshot_digest" in result["drift_fields"]

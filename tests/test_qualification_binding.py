from __future__ import annotations

import pytest

from dating_boost.core.qualification_binding import normalize_qualification_binding


def _binding(**overrides):
    payload = {
        "schema_version": 1,
        "qualification_id": "qual_1",
        "phase": "canary",
        "cycle_index": 1,
        "attempt_id": "attempt_1",
        "local_fencing_token": 2,
        "runtime_fencing_token": 3,
    }
    payload.update(overrides)
    return payload


def test_neutral_qualification_binding_normalizer_preserves_canonical_fields():
    payload = _binding(extra_app_field="not-carried")

    result = normalize_qualification_binding(payload)

    assert result == _binding()


@pytest.mark.parametrize(
    "overrides",
    (
        {"schema_version": 2},
        {"phase": "other"},
        {"cycle_index": 0},
        {"attempt_id": ""},
        {"local_fencing_token": True},
        {"runtime_fencing_token": 0},
    ),
)
def test_neutral_qualification_binding_normalizer_rejects_invalid_scope(overrides):
    with pytest.raises(ValueError, match="qualification_binding_invalid"):
        normalize_qualification_binding(_binding(**overrides))

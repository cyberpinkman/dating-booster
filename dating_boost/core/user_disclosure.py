from __future__ import annotations

from pathlib import Path
from typing import Any

from dating_boost.core.storage import JsonStorage


USER_DISCLOSURE_PROFILE_SCHEMA_VERSION = 1
USER_READINESS_SCHEMA_VERSION = 1

DISCLOSURE_PROFILE_PATH = Path("user") / "disclosure_profile.json"
DATING_PROFILE_SOURCE_PATH = Path("user") / "dating_profile_source.json"
INTERVIEW_SOURCE_PATH = Path("user") / "self_interview_source.json"

SIMULATION_POLICIES = {
    "free_simulation_soft",
    "material_only",
    "user_confirmed_only",
}
MATERIAL_SENSITIVITIES = {"low", "medium", "high"}
AUTONOMOUS_MATERIAL_SENSITIVITIES = {"low", "medium"}
MATERIAL_RISK_LEVELS = {"low", "medium", "high"}
MIN_AUTONOMOUS_LOW_RISK_MATERIALS = 5
MIN_AUTONOMOUS_LOW_INVESTMENT_REPAIR_MATERIALS = 2
MIN_AUTONOMOUS_DATE_PREFERENCE_MATERIALS = 1


def interview_template() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "user_id": "user_local",
        "voice_samples": [],
        "hard_facts": [],
        "persona_style": {
            "baseline": "",
            "allowed_modulations": ["warmer", "more outgoing", "more playful"],
        },
        "shareable_material": [
            {
                "material_id": "mat_example",
                "type": "life_detail",
                "text": "",
                "tags": [],
                "risk_level": "low",
                "usable_moves": ["light_self_disclosure"],
                "hard_fact_dependencies": [],
                "example_phrasings": [],
                "sensitivity": "low",
                "source": "user_interview",
            }
        ],
        "boundaries": [],
        "simulation_policy": "free_simulation_soft",
    }


class UserDisclosureRepository:
    def __init__(self, root: Path):
        self.root = root
        self._storage = JsonStorage(root)

    def save_dating_profile(self, payload: dict[str, Any], *, updated_at: str) -> dict[str, Any]:
        self._storage.write_json(DATING_PROFILE_SOURCE_PATH, _source_document(payload, updated_at))
        existing = self.load_profile_or_default(updated_at=updated_at)
        merged = _merge_profile(existing, _profile_from_dating_profile(payload, updated_at))
        merged["source_completion"]["dating_profile"] = True
        merged["updated_at"] = updated_at
        self._write_profile(merged)
        return {
            "schema_version": 1,
            "status": "ok",
            "path": str(DISCLOSURE_PROFILE_PATH),
            "source": "dating_profile",
            "profile": merged,
        }

    def save_interview(self, payload: dict[str, Any], *, updated_at: str) -> dict[str, Any]:
        self._storage.write_json(INTERVIEW_SOURCE_PATH, _source_document(payload, updated_at))
        existing = self.load_profile_or_default(updated_at=updated_at)
        merged = _merge_profile(existing, _profile_from_interview(payload, updated_at))
        merged["source_completion"]["interview"] = True
        merged["updated_at"] = updated_at
        self._write_profile(merged)
        return {
            "schema_version": 1,
            "status": "ok",
            "path": str(DISCLOSURE_PROFILE_PATH),
            "source": "self_interview",
            "profile": merged,
        }

    def load_profile(self) -> dict[str, Any]:
        return self._storage.read_json(DISCLOSURE_PROFILE_PATH, expected_schema_version=USER_DISCLOSURE_PROFILE_SCHEMA_VERSION)

    def load_profile_or_none(self) -> dict[str, Any] | None:
        try:
            return self.load_profile()
        except FileNotFoundError:
            return None

    def load_profile_or_default(self, *, updated_at: str) -> dict[str, Any]:
        profile = self.load_profile_or_none()
        if profile is not None:
            return profile
        return default_disclosure_profile(updated_at=updated_at)

    def readiness(self, *, mode: str) -> dict[str, Any]:
        profile = self.load_profile_or_none()
        if profile is None:
            return _readiness_payload(
                mode=mode,
                ready=False,
                reason="missing_user_disclosure_profile",
                missing=["dating_profile", "self_interview", "shareable_material"],
                profile=None,
            )

        missing: list[str] = []
        completion = dict(profile.get("source_completion") or {})
        if mode == "autonomous":
            if not completion.get("dating_profile"):
                missing.append("dating_profile")
            if not completion.get("interview"):
                missing.append("self_interview")

        shareable = _usable_shareable_material(profile)
        low_risk = _low_risk_material(profile)
        repair = _materials_for_move(profile, "low_investment_repair")
        date_preferences = _date_preference_material(profile)
        if mode == "autonomous":
            if len(low_risk) < MIN_AUTONOMOUS_LOW_RISK_MATERIALS:
                missing.append("low_risk_shareable_material")
            if len(repair) < MIN_AUTONOMOUS_LOW_INVESTMENT_REPAIR_MATERIALS:
                missing.append("low_investment_repair_material")
            if len(date_preferences) < MIN_AUTONOMOUS_DATE_PREFERENCE_MATERIALS:
                missing.append("date_preference_material")

        if not profile.get("simulation_policy"):
            missing.append("simulation_policy")

        ready = not missing
        return _readiness_payload(
            mode=mode,
            ready=ready,
            reason="ready" if ready else "needs_user_profile",
            missing=missing,
            profile=profile,
        )

    def _write_profile(self, profile: dict[str, Any]) -> None:
        errors = validate_disclosure_profile(profile)
        if errors:
            raise ValueError("; ".join(errors))
        self._storage.write_json(DISCLOSURE_PROFILE_PATH, profile)


def default_disclosure_profile(*, updated_at: str) -> dict[str, Any]:
    return {
        "schema_version": USER_DISCLOSURE_PROFILE_SCHEMA_VERSION,
        "user_id": "user_local",
        "hard_facts": [],
        "persona_style": {
            "baseline": "",
            "allowed_modulations": ["warmer", "more outgoing", "more playful"],
        },
        "shareable_material": [],
        "voice_samples": [],
        "boundaries": [],
        "simulation_policy": "free_simulation_soft",
        "source_completion": {
            "dating_profile": False,
            "interview": False,
        },
        "updated_at": updated_at,
    }


def validate_disclosure_profile(profile: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(profile, dict):
        return ["user disclosure profile must be an object"]
    if profile.get("schema_version") != USER_DISCLOSURE_PROFILE_SCHEMA_VERSION:
        errors.append("user disclosure profile schema_version must equal 1")
    if not isinstance(profile.get("user_id"), str) or not profile.get("user_id", "").strip():
        errors.append("user_id is required")
    for field in ("hard_facts", "shareable_material", "voice_samples", "boundaries"):
        if not isinstance(profile.get(field), list):
            errors.append(f"{field} must be a list")
    for index, material in enumerate(_objects(profile.get("shareable_material")), start=1):
        path = f"shareable_material[{index}]"
        if not isinstance(material.get("material_id"), str) or not material.get("material_id", "").strip():
            errors.append(f"{path}.material_id is required")
        if "text" in material and not isinstance(material.get("text"), str):
            errors.append(f"{path}.text must be a string")
        if "tags" in material and not isinstance(material.get("tags"), list):
            errors.append(f"{path}.tags must be a list")
        if material.get("sensitivity", "low") not in MATERIAL_SENSITIVITIES:
            errors.append(f"{path}.sensitivity must be one of {sorted(MATERIAL_SENSITIVITIES)}")
        if material.get("risk_level", material.get("sensitivity", "low")) not in MATERIAL_RISK_LEVELS:
            errors.append(f"{path}.risk_level must be one of {sorted(MATERIAL_RISK_LEVELS)}")
        if "usable_moves" in material and not isinstance(material.get("usable_moves"), list):
            errors.append(f"{path}.usable_moves must be a list")
        if "hard_fact_dependencies" in material and not isinstance(material.get("hard_fact_dependencies"), list):
            errors.append(f"{path}.hard_fact_dependencies must be a list")
        if "example_phrasings" in material and not isinstance(material.get("example_phrasings"), list):
            errors.append(f"{path}.example_phrasings must be a list")
    if not isinstance(profile.get("persona_style"), dict):
        errors.append("persona_style must be an object")
    if profile.get("simulation_policy") not in SIMULATION_POLICIES:
        errors.append(f"simulation_policy must be one of {sorted(SIMULATION_POLICIES)}")
    if not isinstance(profile.get("source_completion"), dict):
        errors.append("source_completion must be an object")
    return errors


def _profile_from_dating_profile(payload: dict[str, Any], updated_at: str) -> dict[str, Any]:
    if _looks_like_disclosure_profile(payload):
        profile = dict(payload)
        profile.setdefault("source_completion", {"dating_profile": True, "interview": False})
        profile["source_completion"]["dating_profile"] = True
        profile.setdefault("updated_at", updated_at)
        profile.setdefault("simulation_policy", "free_simulation_soft")
        return profile

    profile: dict[str, Any] = {
        "schema_version": USER_DISCLOSURE_PROFILE_SCHEMA_VERSION,
        "user_id": str(payload.get("user_id") or "user_local"),
        "hard_facts": _objects(payload.get("hard_facts") or payload.get("facts")),
        "boundaries": _objects(payload.get("boundaries")),
        "voice_samples": _strings(payload.get("voice_samples") or payload.get("style_examples")),
    }
    persona_style = payload.get("persona_style")
    if isinstance(persona_style, dict):
        profile["persona_style"] = dict(persona_style)
    if "simulation_policy" in payload:
        profile["simulation_policy"] = str(payload["simulation_policy"])
    return profile


def _profile_from_interview(payload: dict[str, Any], updated_at: str) -> dict[str, Any]:
    profile: dict[str, Any] = {
        "schema_version": USER_DISCLOSURE_PROFILE_SCHEMA_VERSION,
        "user_id": str(payload.get("user_id") or "user_local"),
        "hard_facts": _objects(payload.get("hard_facts")),
        "shareable_material": _normalize_material(payload.get("shareable_material")),
        "voice_samples": _strings(payload.get("voice_samples")),
        "boundaries": _objects(payload.get("boundaries")),
    }
    persona_style = payload.get("persona_style")
    if isinstance(persona_style, dict):
        profile["persona_style"] = dict(persona_style)
    if "simulation_policy" in payload:
        profile["simulation_policy"] = str(payload["simulation_policy"])
    return profile


def _merge_profile(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    merged["schema_version"] = USER_DISCLOSURE_PROFILE_SCHEMA_VERSION
    merged["user_id"] = str(overlay.get("user_id") or base.get("user_id") or "user_local")
    merged["hard_facts"] = _merge_objects(base.get("hard_facts"), overlay.get("hard_facts"), "fact_id")
    merged["shareable_material"] = _merge_objects(
        base.get("shareable_material"),
        overlay.get("shareable_material"),
        "material_id",
    )
    merged["voice_samples"] = _unique_strings([*_strings(base.get("voice_samples")), *_strings(overlay.get("voice_samples"))])
    merged["boundaries"] = _merge_objects(base.get("boundaries"), overlay.get("boundaries"), "boundary_id")
    if isinstance(overlay.get("persona_style"), dict):
        merged["persona_style"] = dict(overlay["persona_style"])
    else:
        merged.setdefault("persona_style", default_disclosure_profile(updated_at=merged.get("updated_at", ""))["persona_style"])
    merged["simulation_policy"] = str(overlay.get("simulation_policy") or base.get("simulation_policy") or "free_simulation_soft")
    completion = dict(base.get("source_completion") or {})
    for key, value in dict(overlay.get("source_completion") or {}).items():
        if value:
            completion[key] = value
    completion.setdefault("dating_profile", False)
    completion.setdefault("interview", False)
    merged["source_completion"] = completion
    return merged


def _normalize_material(value: Any) -> list[dict[str, Any]]:
    items = _objects(value)
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        material = dict(item)
        material.setdefault("material_id", f"mat_{index}")
        material.setdefault("type", "life_detail")
        material.setdefault("tags", [])
        material.setdefault("risk_level", str(material.get("sensitivity") or "low"))
        material.setdefault("usable_moves", _moves_from_material(material))
        material.setdefault("hard_fact_dependencies", [])
        material.setdefault("example_phrasings", [])
        material.setdefault("sensitivity", "low")
        material.setdefault("source", "user_interview")
        normalized.append(material)
    return normalized


def _usable_shareable_material(profile: dict[str, Any]) -> list[dict[str, Any]]:
    usable: list[dict[str, Any]] = []
    for material in _objects(profile.get("shareable_material")):
        text = material.get("text")
        sensitivity = str(material.get("sensitivity") or "low")
        if isinstance(text, str) and text.strip() and sensitivity in AUTONOMOUS_MATERIAL_SENSITIVITIES:
            usable.append(material)
    return usable


def _low_risk_material(profile: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        material
        for material in _usable_shareable_material(profile)
        if _material_risk_level(material) == "low"
    ]


def _materials_for_move(profile: dict[str, Any], move: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for material in _low_risk_material(profile):
        moves = [str(item) for item in material.get("usable_moves", [])] if isinstance(material.get("usable_moves"), list) else []
        tags = [str(item) for item in material.get("tags", [])] if isinstance(material.get("tags"), list) else []
        if move in moves or move in tags:
            result.append(material)
    return result


def _date_preference_material(profile: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for material in _low_risk_material(profile):
        material_type = str(material.get("type") or "")
        tags = [str(item) for item in material.get("tags", [])] if isinstance(material.get("tags"), list) else []
        moves = [str(item) for item in material.get("usable_moves", [])] if isinstance(material.get("usable_moves"), list) else []
        if material_type == "date_preference" or "date_preference" in tags or "soft_invite_probe" in moves:
            result.append(material)
    return result


def _material_risk_level(material: dict[str, Any]) -> str:
    return str(material.get("risk_level") or material.get("sensitivity") or "low")


def _moves_from_material(material: dict[str, Any]) -> list[str]:
    tags = [str(item) for item in material.get("tags", [])] if isinstance(material.get("tags"), list) else []
    moves: list[str] = []
    if "low_investment_repair" in tags:
        moves.append("low_investment_repair")
    if "soft_invite" in tags or "date_activity" in tags or "date_preference" in tags:
        moves.append("soft_invite_probe")
    if not moves:
        moves.append("light_self_disclosure")
    return moves


def _objects(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _merge_objects(base: Any, overlay: Any, key: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    by_key: dict[str, dict[str, Any]] = {}
    for item in [*_objects(base), *_objects(overlay)]:
        item_key = str(item.get(key) or item.get("id") or len(result))
        if item_key in by_key:
            by_key[item_key].update(item)
        else:
            by_key[item_key] = dict(item)
            result.append(by_key[item_key])
    return result


def _unique_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _looks_like_disclosure_profile(payload: dict[str, Any]) -> bool:
    return "shareable_material" in payload and "simulation_policy" in payload


def _source_document(payload: dict[str, Any], updated_at: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source_payload": dict(payload),
        "updated_at": updated_at,
    }


def _readiness_payload(
    *,
    mode: str,
    ready: bool,
    reason: str,
    missing: list[str],
    profile: dict[str, Any] | None,
) -> dict[str, Any]:
    material_count = len(_objects(profile.get("shareable_material"))) if profile else 0
    usable_material_count = len(_usable_shareable_material(profile)) if profile else 0
    low_risk_count = len(_low_risk_material(profile)) if profile else 0
    low_investment_repair_count = len(_materials_for_move(profile, "low_investment_repair")) if profile else 0
    date_preference_count = len(_date_preference_material(profile)) if profile else 0
    return {
        "schema_version": USER_READINESS_SCHEMA_VERSION,
        "status": "ok" if ready else "needs_user_profile",
        "mode": mode,
        "ready": ready,
        "reason": reason,
        "missing": missing,
        "shareable_material_count": material_count,
        "usable_shareable_material_count": usable_material_count,
        "low_risk_material_count": low_risk_count,
        "low_investment_repair_material_count": low_investment_repair_count,
        "date_preference_material_count": date_preference_count,
        "simulation_policy": profile.get("simulation_policy") if profile else None,
        "profile_path": str(DISCLOSURE_PROFILE_PATH) if profile else None,
    }

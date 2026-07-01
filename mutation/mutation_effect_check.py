"""Non-blocking quality checks for concrete mutation plans."""

from __future__ import annotations

import json
from typing import Any


_OBSERVATION_FRIENDLY: dict[str, set[str]] = {
    "query_sql": {"query_string", "return_value", "public_property"},
    "repr_string_format": {"format_string", "return_value", "public_property"},
    "serialization": {"return_value", "public_property", "type_property", "state_change"},
    "parser_render": {"render_output", "return_value", "public_property"},
    "io_path": {"return_value", "public_property", "format_string", "type_property"},
    "warning": {"warning", "return_value", "public_property"},
}

_STRONGER_TRIGGER_RULES = {
    "CALL_CHAIN_EXTEND",
    "LIFECYCLE_TRIGGER",
    "ARG_BOUNDARY_EXPAND",
    "STATE_MUTATION",
}


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        mapped = value.to_dict()
        return mapped if isinstance(mapped, dict) else {}
    return {}


def check_mutation_effect(
    plan: Any,
    behavior: Any,
    execution_feedback: str = "",
    verifier_feedback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assess plan concreteness while allowing the pipeline to continue."""
    data = _mapping(plan)
    rules = [item for item in data.get("selected_rules", []) if isinstance(item, dict)]
    target_api = [str(item) for item in data.get("target_api", []) if str(item).strip()]
    has_action = bool(
        rules
        and all(
            str(item.get("after_pattern") or item.get("mutation") or "").strip()
            for item in rules
        )
    )
    has_delta = bool(
        rules
        and all(
            str(item.get("before_pattern") or "").strip()
            and str(item.get("after_pattern") or item.get("mutation") or "").strip()
            and str(item.get("before_pattern") or "").strip()
            != str(item.get("after_pattern") or item.get("mutation") or "").strip()
            for item in rules
        )
    )
    has_trigger_effect = bool(
        rules and all(str(item.get("expected_trigger_effect") or "").strip() for item in rules)
    )
    has_observable = bool(
        rules and all(str(item.get("observable_difference") or "").strip() for item in rules)
    )
    oracle_only = bool(rules) and all(
        item.get("rule") == "ORACLE_REBIND"
        or item.get("implementation_mode") == "observation_only"
        or item.get("mutation_scope") == "oracle"
        for item in rules
    )
    feedback_text = (
        execution_feedback
        + "\n"
        + json.dumps(verifier_feedback or {}, ensure_ascii=False, default=str)
    ).upper()
    buggy_pass = "BUGGY_PASS" in feedback_text or "TARGET_NOT_HIT" in feedback_text
    strengthened = any(item.get("rule") in _STRONGER_TRIGGER_RULES for item in rules)
    issue_pattern = str(data.get("issue_pattern") or "")
    raw_oracle_strategy = data.get("oracle_strategy")
    if isinstance(raw_oracle_strategy, dict):
        oracle_strategy = str(
            raw_oracle_strategy.get("preferred_assertion_style") or ""
        )
    else:
        oracle_strategy = str(raw_oracle_strategy or "")
    friendly = (
        issue_pattern not in _OBSERVATION_FRIENDLY
        or oracle_strategy in _OBSERVATION_FRIENDLY[issue_pattern]
    )

    warnings: list[str] = []
    if not target_api:
        warnings.append("target_api is empty")
    if not has_action:
        warnings.append("selected_rules lack a concrete mutation action")
    if not has_delta:
        warnings.append("selected_rules require distinct before_pattern and after_pattern")
    if not has_trigger_effect:
        warnings.append("selected_rules lack expected_trigger_effect")
    if not has_observable:
        warnings.append("selected_rules lack observable_difference")
    if oracle_only:
        warnings.append("oracle-only plan is illegal during trigger planning")
    if buggy_pass and not strengthened:
        warnings.append("previous Buggy PASS was not followed by a stronger trigger operator")
    if not friendly:
        warnings.append(
            f"oracle_strategy={oracle_strategy or '<empty>'} is weak for issue_pattern={issue_pattern}"
        )

    missing_core = sum(
        not flag
        for flag in (bool(target_api), has_action, has_delta, has_trigger_effect, has_observable)
    )
    noop_risk = "high" if missing_core >= 2 or oracle_only else "medium" if missing_core else "low"
    oracle_risk = "high" if oracle_only else "medium" if not friendly else "low"
    return {
        "is_effective_mutation_plan": not warnings,
        "target_api_covered_by_plan": bool(target_api),
        "has_concrete_mutation_action": has_action,
        "has_before_after_delta": has_delta,
        "has_expected_trigger_effect": has_trigger_effect,
        "has_observable_difference": has_observable,
        "risk_of_noop_mutation": noop_risk,
        "risk_of_oracle_overfit": oracle_risk,
        "required_next_action": "generate_candidate",
        "warnings": warnings,
    }

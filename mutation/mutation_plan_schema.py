"""Validation and normalization for BRT mutation plans."""

from __future__ import annotations

from typing import Any

from core.schema import BehaviorTarget, MutationPlan
from mutation.brt_mutation_rules import (
    ISSUE_PATTERNS,
    RULE_NAMES,
    TRIGGER_RULE_NAMES,
    infer_issue_pattern,
)


ORACLE_STRATEGIES = {
    "exception",
    "warning",
    "return_value",
    "state_change",
    "query_string",
    "render_output",
    "public_property",
    "format_string",
    "type_property",
}


def _strings(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def validate_plan_payload(data: dict[str, Any], behavior: BehaviorTarget) -> tuple[dict[str, Any], list[str]]:
    """Normalize model output and return warnings instead of throwing."""
    warnings: list[str] = []
    issue_text = " ".join(
        [
            str(behavior.issue_summary or ""),
            str(behavior.trigger_condition.get("text") or ""),
            str(behavior.error_symptom.get("text") or ""),
            str(behavior.expected_behavior.get("text") or ""),
        ]
    )
    issue_pattern = str(data.get("issue_pattern") or infer_issue_pattern(issue_text))
    if issue_pattern not in ISSUE_PATTERNS:
        warnings.append(f"invalid issue_pattern={issue_pattern}; using unknown")
        issue_pattern = "unknown"
    raw_rules = data.get("selected_rules")
    selected_rules: list[dict[str, str]] = []
    if isinstance(raw_rules, list):
        for raw in raw_rules:
            if not isinstance(raw, dict):
                continue
            rule = str(raw.get("rule") or "")
            if rule not in RULE_NAMES:
                warnings.append(f"invalid mutation rule ignored: {rule}")
                continue
            if rule not in TRIGGER_RULE_NAMES:
                warnings.append(
                    f"oracle-only mutation rule ignored during trigger planning: {rule}"
                )
                continue
            why = str(raw.get("why_issue_aligned") or "")
            if not why:
                warnings.append(f"rule {rule} missing why_issue_aligned")
                why = "Rule is selected to align seed behavior with the issue trigger."
            selected_rules.append(
                {
                    "rule": rule,
                    "target_code": str(raw.get("target_code") or ""),
                    "seed_element": str(raw.get("seed_element") or ""),
                    "mutation": str(raw.get("mutation") or ""),
                    "why_issue_aligned": why,
                    "expected_buggy_observation": str(raw.get("expected_buggy_observation") or ""),
                    "expected_fixed_behavior": str(raw.get("expected_fixed_behavior") or ""),
                    "risk": str(raw.get("risk") or "medium"),
                }
            )
    if not selected_rules:
        old_ops = [
            item
            for item in _strings(data.get("mutation_ops"))
            if item in TRIGGER_RULE_NAMES
        ]
        fallback = old_ops[0] if old_ops else "CALL_CHAIN_EXTEND"
        selected_rules = [
            {
                "rule": fallback,
                "target_code": "",
                "seed_element": "",
                "mutation": "",
                "why_issue_aligned": "Fallback rule chosen after invalid or missing mutation plan rules.",
                "expected_buggy_observation": "",
                "expected_fixed_behavior": str(behavior.expected_behavior.get("text") or ""),
                "risk": "medium",
            }
        ]
    selected_rules = selected_rules[:3]
    oracle = str(data.get("oracle_strategy") or "public_property")
    if oracle not in ORACLE_STRATEGIES:
        warnings.append(f"invalid oracle_strategy={oracle}; using public_property")
        oracle = "public_property"
    normalized = {
        "mutation_goal": str(data.get("mutation_goal") or ""),
        "issue_pattern": issue_pattern,
        "selected_rules": selected_rules,
        "preserve_from_seed": _strings(data.get("preserve_from_seed")),
        "do_not_change": _strings(data.get("do_not_change")),
        "target_api": _strings(data.get("target_api")),
        "target_path": _strings(data.get("target_path")),
        "mutation_ops": list(dict.fromkeys(item["rule"] for item in selected_rules)),
        "expected_behavior": str(behavior.expected_behavior.get("text") or ""),
        "oracle_strategy": oracle,
        "why_this_should_trigger": str(data.get("why_this_should_trigger") or ""),
        "risk": str(data.get("risk") or selected_rules[0].get("risk") or "medium"),
        "fallback_if_buggy_pass": str(data.get("fallback_if_buggy_pass") or ""),
        "fallback_if_fixed_fail": str(data.get("fallback_if_fixed_fail") or ""),
    }
    return normalized, warnings


def mutation_plan_from_payload(
    instance_id: str,
    round_id: int,
    data: dict[str, Any],
    behavior: BehaviorTarget,
) -> tuple[MutationPlan, list[str]]:
    normalized, warnings = validate_plan_payload(data, behavior)
    return (
        MutationPlan(
            instance_id=instance_id,
            round_id=round_id,
            **normalized,
        ),
        warnings,
    )

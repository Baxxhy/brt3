"""Validation and normalization for BRT mutation plans."""

from __future__ import annotations

from typing import Any

from core.schema import BehaviorTarget, MutationPlan
from mutation.brt_mutation_rules import (
    ISSUE_PATTERNS,
    RULE_NAMES,
    RULES,
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

IMPLEMENTATION_MODES = {
    "deterministic_ast",
    "llm_edit",
    "hybrid",
    "observation_only",
}

AST_FEASIBILITY_VALUES = {"none", "partial", "high"}
RISK_VALUES = {"low", "medium", "high"}
FAULT_PROXY_FIELDS = (
    "trigger_precondition",
    "buggy_behavior",
    "expected_fixed_behavior",
    "observable_symptom",
    "target_api",
    "oracle_type",
    "why_issue_aligned",
)


def _strings(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value if str(item).strip()]


def _confidence(value: Any, warnings: list[str], rule: str) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        warnings.append(f"rule {rule} has invalid confidence; using 0.0")
        return 0.0
    if confidence < 0.0 or confidence > 1.0:
        warnings.append(f"rule {rule} confidence={confidence} clamped to [0, 1]")
    return max(0.0, min(1.0, confidence))


def _behavior_target_apis(behavior: BehaviorTarget) -> list[str]:
    values: list[str] = []
    for item in behavior.target_apis:
        if isinstance(item, str):
            values.append(item)
            continue
        if not isinstance(item, dict):
            continue
        for key in ("qualified_name", "name", "api", "symbol", "target"):
            value = str(item.get(key) or "").strip()
            if value:
                values.append(value)
                break
    return list(dict.fromkeys(values))


def _candidate_subtypes(
    candidate_operators: list[dict[str, Any]] | None,
) -> dict[str, list[str]]:
    if candidate_operators is None:
        return {}
    candidates: dict[str, list[str]] = {}
    for item in candidate_operators:
        if not isinstance(item, dict):
            continue
        rule = str(item.get("rule") or "")
        if rule not in TRIGGER_RULE_NAMES:
            continue
        candidates[rule] = _strings(item.get("recommended_subtypes"))
    return candidates


def _normalize_fault_proxy(
    value: Any,
    behavior: BehaviorTarget,
    target_api: list[str],
) -> dict[str, str]:
    raw = value if isinstance(value, dict) else {}
    fallback = {
        "trigger_precondition": str(behavior.trigger_condition.get("text") or ""),
        "buggy_behavior": str(behavior.error_symptom.get("text") or ""),
        "expected_fixed_behavior": str(behavior.expected_behavior.get("text") or ""),
        "observable_symptom": str(behavior.error_symptom.get("text") or ""),
        "target_api": target_api[0] if target_api else "",
        "oracle_type": "",
        "why_issue_aligned": str(behavior.issue_summary or ""),
    }
    return {
        field: str(raw.get(field) or fallback[field])
        for field in FAULT_PROXY_FIELDS
    }


def validate_plan_payload(
    data: dict[str, Any],
    behavior: BehaviorTarget,
    candidate_operators: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], list[str]]:
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

    candidates = _candidate_subtypes(candidate_operators)
    raw_rules = data.get("selected_rules")
    selected_rules: list[dict[str, Any]] = []
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
            if candidate_operators is not None and rule not in candidates:
                warnings.append(f"rule not offered by candidate operator router ignored: {rule}")
                continue

            subtype = str(raw.get("operator_subtype") or "")
            legal_subtypes = list(RULES[rule].subtypes)
            recommended_subtypes = candidates.get(rule) or legal_subtypes
            if subtype not in legal_subtypes:
                warnings.append(
                    f"rule {rule} has invalid operator_subtype={subtype!r}; "
                    f"using {recommended_subtypes[0]}"
                )
                subtype = recommended_subtypes[0]
            elif candidate_operators is not None and subtype not in recommended_subtypes:
                warnings.append(
                    f"rule {rule} subtype={subtype} was not recommended by router; "
                    f"using {recommended_subtypes[0]}"
                )
                subtype = recommended_subtypes[0]

            mutation_scope = str(raw.get("mutation_scope") or "trigger")
            if mutation_scope != "trigger":
                warnings.append(f"rule {rule} mutation_scope={mutation_scope!r}; using trigger")
                mutation_scope = "trigger"
            implementation_mode = str(raw.get("implementation_mode") or "llm_edit")
            if implementation_mode not in IMPLEMENTATION_MODES:
                warnings.append(
                    f"rule {rule} invalid implementation_mode={implementation_mode!r}; using llm_edit"
                )
                implementation_mode = "llm_edit"
            if implementation_mode == "observation_only":
                warnings.append(
                    f"rule {rule} observation_only mode is not legal for trigger mutation; using llm_edit"
                )
                implementation_mode = "llm_edit"
            ast_feasibility = str(raw.get("ast_feasibility") or "none")
            if ast_feasibility not in AST_FEASIBILITY_VALUES:
                warnings.append(
                    f"rule {rule} invalid ast_feasibility={ast_feasibility!r}; using none"
                )
                ast_feasibility = "none"

            before_pattern = str(raw.get("before_pattern") or "")
            after_pattern = str(raw.get("after_pattern") or raw.get("mutation") or "")
            expected_trigger_effect = str(raw.get("expected_trigger_effect") or "")
            if not before_pattern:
                warnings.append(f"rule {rule} missing before_pattern")
            if not after_pattern:
                warnings.append(f"rule {rule} missing after_pattern")
            if not expected_trigger_effect:
                warnings.append(f"rule {rule} missing expected_trigger_effect")
            why = str(raw.get("why_issue_aligned") or "")
            if not why:
                warnings.append(f"rule {rule} missing why_issue_aligned")
                why = "Rule is selected to align seed behavior with the issue trigger."
            risk = str(raw.get("risk") or "medium")
            if risk not in RISK_VALUES:
                warnings.append(f"rule {rule} invalid risk={risk!r}; using medium")
                risk = "medium"
            selected_rules.append(
                {
                    "rule": rule,
                    "operator_subtype": subtype,
                    "mutation_scope": mutation_scope,
                    "confidence": _confidence(raw.get("confidence", 0.0), warnings, rule),
                    "confidence_reason": str(raw.get("confidence_reason") or ""),
                    "pre_requisite": _strings(raw.get("pre_requisite")),
                    "depends_on": _strings(raw.get("depends_on")),
                    "implementation_mode": implementation_mode,
                    "ast_feasibility": ast_feasibility,
                    "target_code": str(raw.get("target_code") or ""),
                    "seed_element": str(raw.get("seed_element") or ""),
                    "before_pattern": before_pattern,
                    "after_pattern": after_pattern,
                    "expected_trigger_effect": expected_trigger_effect,
                    "observable_difference": str(raw.get("observable_difference") or ""),
                    "why_issue_aligned": why,
                    "expected_buggy_observation": str(raw.get("expected_buggy_observation") or ""),
                    "expected_fixed_behavior": str(raw.get("expected_fixed_behavior") or ""),
                    "risk": risk,
                }
            )

    if not selected_rules:
        old_ops = [
            item
            for item in _strings(data.get("mutation_ops"))
            if item in TRIGGER_RULE_NAMES
            and (candidate_operators is None or item in candidates)
        ]
        if old_ops:
            fallback = old_ops[0]
        elif candidates:
            fallback = next(iter(candidates))
        else:
            fallback = "CALL_CHAIN_EXTEND"
        fallback_subtype = (
            (candidates.get(fallback) or list(RULES[fallback].subtypes))[0]
        )
        warnings.append(f"no valid selected_rules; using fallback {fallback}/{fallback_subtype}")
        selected_rules = [
            {
                "rule": fallback,
                "operator_subtype": fallback_subtype,
                "mutation_scope": "trigger",
                "confidence": 0.0,
                "confidence_reason": "Schema fallback after missing or invalid model selection.",
                "pre_requisite": [],
                "depends_on": [],
                "implementation_mode": "llm_edit",
                "ast_feasibility": "none",
                "target_code": "",
                "seed_element": "",
                "before_pattern": "",
                "after_pattern": "",
                "expected_trigger_effect": "",
                "observable_difference": "",
                "why_issue_aligned": "Fallback rule chosen after invalid or missing mutation plan rules.",
                "expected_buggy_observation": "",
                "expected_fixed_behavior": str(behavior.expected_behavior.get("text") or ""),
                "risk": "medium",
            }
        ]
    selected_rules = selected_rules[:2]

    raw_oracle = data.get("oracle_strategy")
    if isinstance(raw_oracle, dict):
        preferred = str(
            raw_oracle.get("preferred_assertion_style") or "public_property"
        )
        if preferred not in ORACLE_STRATEGIES:
            warnings.append(
                f"invalid preferred_assertion_style={preferred}; "
                "using public_property"
            )
            preferred = "public_property"
        observation_points = raw_oracle.get("observation_points")
        if not isinstance(observation_points, list):
            observation_points = (
                [str(observation_points)] if observation_points else []
            )
        oracle: str | dict[str, Any] = {
            "observation_points": [
                str(item) for item in observation_points if str(item).strip()
            ],
            "assertion_goal": str(raw_oracle.get("assertion_goal") or ""),
            "preferred_assertion_style": preferred,
            "avoid": str(raw_oracle.get("avoid") or ""),
        }
    else:
        oracle = str(raw_oracle or "public_property")
        if oracle not in ORACLE_STRATEGIES:
            warnings.append(
                f"invalid oracle_strategy={oracle}; using public_property"
            )
            oracle = "public_property"
    target_api = _strings(data.get("target_api")) or _behavior_target_apis(behavior)
    normalized = {
        "mutation_goal": str(data.get("mutation_goal") or ""),
        "issue_pattern": issue_pattern,
        "fault_proxy": _normalize_fault_proxy(data.get("fault_proxy"), behavior, target_api),
        "selected_rules": selected_rules,
        "preserve_from_seed": _strings(data.get("preserve_from_seed")),
        "do_not_change": _strings(data.get("do_not_change")),
        "target_api": target_api,
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
    candidate_operators: list[dict[str, Any]] | None = None,
) -> tuple[MutationPlan, list[str]]:
    normalized, warnings = validate_plan_payload(data, behavior, candidate_operators)
    return (
        MutationPlan(
            instance_id=instance_id,
            round_id=round_id,
            **normalized,
        ),
        warnings,
    )

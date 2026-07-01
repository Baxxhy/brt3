"""Deterministic routing from issue evidence to candidate trigger operators."""

from __future__ import annotations

import json
from typing import Any

from mutation.brt_mutation_rules import RULES, TRIGGER_RULE_NAMES, infer_issue_pattern


_BASE_ROUTES: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "query_sql": (
        ("CALL_CHAIN_EXTEND", ("query_materialization",)),
        ("OPERATOR_FLIP", ("query_negation", "include_exclude_flip")),
        ("ARG_BOUNDARY_EXPAND", ("empty_queryset", "empty_q_object")),
    ),
    "repr_string_format": (
        ("ARG_VALUE_REPLACE", ("format_specifier_replace",)),
        ("CALL_CHAIN_EXTEND", ("append_materialization_call",)),
    ),
    "serialization": (
        ("CALL_CHAIN_EXTEND", ("serialization_roundtrip",)),
        ("FIXTURE_DATA_MUTATION", ("file_fixture_content_change",)),
        ("LIFECYCLE_TRIGGER", ("save_load_lifecycle",)),
    ),
    "parser_render": (
        ("CALL_CHAIN_EXTEND", ("parser_render_roundtrip",)),
        ("LIFECYCLE_TRIGGER", ("matplotlib_draw_lifecycle",)),
        ("CONFIG_MUTATION", ("render_backend_change",)),
    ),
    "null_empty": (
        ("ARG_BOUNDARY_EXPAND", ("none_input", "empty_container")),
        ("FIXTURE_DATA_MUTATION", ("fixture_field_override",)),
    ),
    "dtype_shape": (
        ("ARG_VALUE_REPLACE", ("dtype_shape_replace",)),
        ("ARG_BOUNDARY_EXPAND", ("nan_inf", "empty_container")),
        ("FIXTURE_DATA_MUTATION", ("factory_edge_record",)),
    ),
    "configuration": (
        ("CONFIG_MUTATION", ("settings_flag_change", "backend_mode_change")),
        ("LIFECYCLE_TRIGGER", ("django_model_lifecycle",)),
    ),
    "warning": (
        ("CONFIG_MUTATION", ("warning_filter_change",)),
        ("CALL_CHAIN_EXTEND", ("append_materialization_call",)),
    ),
    "cache_state": (
        ("STATE_MUTATION", ("cache_invalidate", "lazy_eval_force", "repeated_call")),
        ("LIFECYCLE_TRIGGER", ("save_load_lifecycle",)),
    ),
    "io_path": (
        ("ARG_VALUE_REPLACE", ("path_value_replace",)),
        ("CALL_CHAIN_EXTEND", ("io_write_readback",)),
        ("FIXTURE_DATA_MUTATION", ("file_fixture_content_change",)),
    ),
    "exception": (
        ("ARG_BOUNDARY_EXPAND", ("none_input", "empty_container", "zero_negative_large")),
        ("CALL_CHAIN_EXTEND", ("append_materialization_call", "insert_lifecycle_call")),
        ("LIFECYCLE_TRIGGER", ("save_load_lifecycle",)),
    ),
    "boundary": (
        ("ARG_BOUNDARY_EXPAND", ("zero_negative_large", "singleton_container", "duplicate_values")),
        ("ARG_VALUE_REPLACE", ("literal_replace", "keyword_arg_replace")),
    ),
    "lifecycle": (
        ("LIFECYCLE_TRIGGER", ("django_model_lifecycle", "save_load_lifecycle")),
        ("CALL_CHAIN_EXTEND", ("insert_lifecycle_call",)),
        ("STATE_MUTATION", ("init_order_change", "repeated_call")),
    ),
    "api_call_chain": (
        ("CALL_CHAIN_EXTEND", ("append_materialization_call", "insert_lifecycle_call")),
        ("ARG_VALUE_REPLACE", ("keyword_arg_replace", "literal_replace")),
        ("STATE_MUTATION", ("repeated_call", "lazy_eval_force")),
    ),
}

_FALLBACK_ROUTES = (
    ("CALL_CHAIN_EXTEND", ("append_materialization_call",)),
    ("ARG_VALUE_REPLACE", ("literal_replace", "keyword_arg_replace")),
    ("ARG_BOUNDARY_EXPAND", ("none_input", "empty_container")),
)


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        mapped = value.to_dict()
        return mapped if isinstance(mapped, dict) else {}
    return {}


def _json_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


def _feedback_text(execution_feedback: Any, verifier_feedback: Any) -> str:
    return (_json_text(execution_feedback) + "\n" + _json_text(verifier_feedback)).upper()


def _preferred_prior_rules(prior: Any) -> set[str]:
    if isinstance(prior, str):
        try:
            prior = json.loads(prior)
        except (TypeError, ValueError):
            return set()
    if not isinstance(prior, dict):
        return set()
    values = prior.get("preferred_rules")
    return {str(item) for item in values} if isinstance(values, list) else set()


def _hinted_routes(
    behavior_data: dict[str, Any],
) -> list[tuple[str, tuple[str, ...]]]:
    routes: list[tuple[str, tuple[str, ...]]] = []
    hints = behavior_data.get("mutation_hints")
    if not isinstance(hints, list):
        return routes
    for hint in hints:
        if not isinstance(hint, dict):
            continue
        rule = str(
            hint.get("suggested_operator")
            or hint.get("operator")
            or ""
        )
        if rule not in TRIGGER_RULE_NAMES:
            continue
        subtype = str(
            hint.get("operator_subtype")
            or hint.get("suggested_subtype")
            or hint.get("subtype")
            or ""
        )
        subtypes = (
            (subtype,)
            if subtype in RULES[rule].subtypes
            else tuple(RULES[rule].subtypes[:2])
        )
        if rule not in {item[0] for item in routes}:
            routes.append((rule, subtypes))
    return routes


def route_candidate_operators(
    behavior: Any,
    host: Any,
    protocol: Any = None,
    execution_feedback: str = "",
    verifier_feedback: dict[str, Any] | None = None,
    protocol_context_audit: dict[str, Any] | None = None,
    prior: Any = None,
) -> list[dict[str, Any]]:
    """Return ranked trigger-only operator families and concrete subtypes."""
    behavior_data = _mapping(behavior)
    host_data = _mapping(host)
    issue_text = " ".join(
        [
            _json_text(behavior_data.get("issue_summary")),
            _json_text(behavior_data.get("trigger_condition")),
            _json_text(behavior_data.get("error_symptom")),
            _json_text(behavior_data.get("expected_behavior")),
        ]
    )
    issue_pattern = infer_issue_pattern(issue_text)
    seed_text = " ".join(
        [
            str(host_data.get("seed_test_name") or ""),
            str(host_data.get("seed_test_code") or ""),
            _json_text(protocol_context_audit or {}),
        ]
    ).lower()
    feedback = _feedback_text(execution_feedback, verifier_feedback or {})
    preferred = _preferred_prior_rules(prior)
    hinted_routes = _hinted_routes(behavior_data)
    base_routes = _BASE_ROUTES.get(issue_pattern, _FALLBACK_ROUTES)
    routes = tuple(hinted_routes) + tuple(
        item
        for item in base_routes
        if item[0] not in {hint[0] for hint in hinted_routes}
    )
    hinted_rules = {item[0] for item in hinted_routes}
    candidates: list[dict[str, Any]] = []
    for index, (rule, subtypes) in enumerate(routes):
        if rule not in TRIGGER_RULE_NAMES:
            continue
        confidence = 0.84 - (0.07 * index)
        evidence = [f"issue_pattern={issue_pattern}"]
        requires: list[str] = []
        if rule in hinted_rules:
            confidence += 0.12
            evidence.append(
                "BehaviorTarget mutation_hints explicitly suggests rule"
            )
        if rule in preferred:
            confidence += 0.05
            evidence.append("aggregate prior prefers rule")
        keyword_evidence = {
            "query_materialization": ("annotate", "queryset", ".query", "filter("),
            "parser_render_roundtrip": ("parse", "render", "template"),
            "serialization_roundtrip": ("serialize", "pickle", "json", "load"),
            "io_write_readback": ("write", "read", "path", "file"),
            "matplotlib_draw_lifecycle": ("matplotlib", "figure", "axes", "draw"),
            "django_model_lifecycle": ("django", "model", "queryset"),
        }
        for subtype in subtypes:
            markers = keyword_evidence.get(subtype, ())
            matched = next((marker for marker in markers if marker in seed_text), "")
            if matched:
                confidence += 0.03
                evidence.append(f"seed contains {matched}")
                break
        if "BUGGY_PASS" in feedback or "TARGET_NOT_HIT" in feedback:
            if rule in {"CALL_CHAIN_EXTEND", "LIFECYCLE_TRIGGER", "ARG_BOUNDARY_EXPAND", "STATE_MUTATION"}:
                confidence += 0.10
                evidence.append("previous Buggy PASS requires stronger trigger")
        if any(status in feedback for status in ("SETUP_ERROR", "COLLECT_ERROR", "SYNTAX_ERROR")):
            if rule in {"CONFIG_MUTATION", "LIFECYCLE_TRIGGER"}:
                confidence -= 0.25
                evidence.append("previous mechanical failure lowers setup-sensitive operator")
            requires.append("preserve recovered seed protocol; repair setup before expanding trigger")
        if "UNRELATED_FAIL" in feedback:
            confidence -= 0.08
            evidence.append("previous unrelated failure requires tighter target_api and seed_element")
            requires.append("bind target_api and seed_element to issue evidence")
        if "ISSUE_ALIGNED_FAIL" in feedback:
            evidence.append("trigger is likely established; keep mutation minimal")
        candidates.append(
            {
                "rule": rule,
                "recommended_subtypes": [
                    subtype for subtype in subtypes if subtype in RULES[rule].subtypes
                ],
                "router_confidence": round(max(0.05, min(0.99, confidence)), 3),
                "router_evidence": list(dict.fromkeys(evidence)),
                "allowed_scope": "trigger",
                "requires": list(dict.fromkeys(requires)),
            }
        )
    return sorted(
        candidates,
        key=lambda item: (-float(item["router_confidence"]), str(item["rule"])),
    )

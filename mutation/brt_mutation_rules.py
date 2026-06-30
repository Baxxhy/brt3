"""Issue-aligned test mutation operator taxonomy."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


RULE_NAMES = {
    "ARG_VALUE_REPLACE",
    "ARG_BOUNDARY_EXPAND",
    "OPERATOR_FLIP",
    "CALL_CHAIN_EXTEND",
    "STATE_MUTATION",
    "CONFIG_MUTATION",
    "LIFECYCLE_TRIGGER",
    "FIXTURE_DATA_MUTATION",
    "ORACLE_REBIND",
}

TRIGGER_RULE_NAMES = {
    "ARG_VALUE_REPLACE",
    "ARG_BOUNDARY_EXPAND",
    "OPERATOR_FLIP",
    "CALL_CHAIN_EXTEND",
    "STATE_MUTATION",
    "CONFIG_MUTATION",
    "LIFECYCLE_TRIGGER",
    "FIXTURE_DATA_MUTATION",
}

ISSUE_PATTERNS = {
    "boundary",
    "null_empty",
    "exception",
    "warning",
    "configuration",
    "lifecycle",
    "cache_state",
    "serialization",
    "query_sql",
    "repr_string_format",
    "dtype_shape",
    "parser_render",
    "io_path",
    "api_call_chain",
    "unknown",
}


@dataclass(frozen=True)
class MutationRule:
    name: str
    description: str
    allowed_targets: tuple[str, ...]
    risk: str
    typical_issue_patterns: tuple[str, ...]
    forbidden_when: tuple[str, ...]
    subtypes: tuple[str, ...]
    transformation_template: str
    expected_effect: str
    oracle_hints: tuple[str, ...]
    implementation_modes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


RULES: dict[str, MutationRule] = {
    "ARG_VALUE_REPLACE": MutationRule(
        name="ARG_VALUE_REPLACE",
        description="Replace one issue-relevant argument or literal while preserving the seed protocol.",
        allowed_targets=("argument", "input", "literal", "keyword"),
        risk="low",
        typical_issue_patterns=("boundary", "dtype_shape", "io_path", "configuration", "repr_string_format"),
        forbidden_when=("requires setup rewrite",),
        subtypes=(
            "literal_replace",
            "keyword_arg_replace",
            "enum_value_replace",
            "dtype_shape_replace",
            "path_value_replace",
            "timezone_locale_replace",
            "format_specifier_replace",
        ),
        transformation_template="Replace <before argument/literal> with <issue-derived value> at <target API call>.",
        expected_effect="Drive the existing seed call through the issue-specific value branch.",
        oracle_hints=("return_value", "public_property", "format_string", "type_property"),
        implementation_modes=("deterministic_ast", "llm_edit", "hybrid"),
    ),
    "ARG_BOUNDARY_EXPAND": MutationRule(
        name="ARG_BOUNDARY_EXPAND",
        description="Move one seed input to an issue-supported boundary or degenerate case.",
        allowed_targets=("argument", "input", "fixture_data"),
        risk="medium",
        typical_issue_patterns=("boundary", "null_empty", "dtype_shape", "query_sql", "exception"),
        forbidden_when=("expected behavior is exact value without boundary evidence",),
        subtypes=(
            "none_input",
            "empty_container",
            "singleton_container",
            "duplicate_values",
            "zero_negative_large",
            "nan_inf",
            "newline_special_char",
            "empty_queryset",
            "empty_q_object",
        ),
        transformation_template="Change <seed value> to <concrete boundary value> without replacing unrelated setup.",
        expected_effect="Expose a boundary branch that the ordinary seed value does not execute.",
        oracle_hints=("exception", "return_value", "public_property", "type_property"),
        implementation_modes=("deterministic_ast", "llm_edit", "hybrid"),
    ),
    "OPERATOR_FLIP": MutationRule(
        name="OPERATOR_FLIP",
        description="Flip one issue-relevant boolean, comparison, query, ordering, or membership operator.",
        allowed_targets=("operator", "predicate", "query"),
        risk="medium",
        typical_issue_patterns=("query_sql", "boundary", "api_call_chain"),
        forbidden_when=("issue has no boolean/comparison/negation evidence",),
        subtypes=(
            "boolean_negation",
            "comparison_flip",
            "query_negation",
            "include_exclude_flip",
            "ordering_flip",
            "membership_flip",
        ),
        transformation_template="Replace <before operator/predicate> with <issue-aligned flipped operator/predicate>.",
        expected_effect="Select the complementary branch or query semantics named by the issue.",
        oracle_hints=("return_value", "query_string", "public_property"),
        implementation_modes=("deterministic_ast", "llm_edit", "hybrid"),
    ),
    "CALL_CHAIN_EXTEND": MutationRule(
        name="CALL_CHAIN_EXTEND",
        description="Append or insert the minimum call needed to reach the latent bug path.",
        allowed_targets=("call_chain", "api", "lifecycle"),
        risk="medium",
        typical_issue_patterns=("api_call_chain", "query_sql", "parser_render", "serialization", "lifecycle", "io_path"),
        forbidden_when=("seed setup is not executable",),
        subtypes=(
            "append_materialization_call",
            "insert_lifecycle_call",
            "serialization_roundtrip",
            "parser_render_roundtrip",
            "io_write_readback",
            "query_materialization",
            "fit_predict_chain",
        ),
        transformation_template="Extend <seed call chain> with <concrete issue-relevant call> and retain its public result.",
        expected_effect="Force lazy, round-trip, materialization, or downstream execution of the target path.",
        oracle_hints=("return_value", "query_string", "render_output", "format_string", "public_property"),
        implementation_modes=("deterministic_ast", "llm_edit", "hybrid"),
    ),
    "STATE_MUTATION": MutationRule(
        name="STATE_MUTATION",
        description="Change observable object state, cache state, call order, aliasing, or repeated-use behavior.",
        allowed_targets=("object_state", "cache", "lifecycle"),
        risk="medium",
        typical_issue_patterns=("cache_state", "lifecycle", "serialization"),
        forbidden_when=("state is private-only and not public behavior",),
        subtypes=(
            "cache_invalidate",
            "lazy_eval_force",
            "repeated_call",
            "init_order_change",
            "copy_alias_change",
            "shared_reference_change",
            "public_state_change",
        ),
        transformation_template="Apply <concrete state transition> before/after <target API> while preserving setup.",
        expected_effect="Expose stale-cache, ordering, reuse, or alias-sensitive behavior.",
        oracle_hints=("state_change", "public_property", "return_value"),
        implementation_modes=("deterministic_ast", "llm_edit", "hybrid"),
    ),
    "CONFIG_MUTATION": MutationRule(
        name="CONFIG_MUTATION",
        description="Change one local configuration value required by the issue.",
        allowed_targets=("config", "settings", "environment"),
        risk="high",
        typical_issue_patterns=("configuration", "warning", "parser_render"),
        forbidden_when=("setup already unstable",),
        subtypes=(
            "settings_flag_change",
            "backend_mode_change",
            "format_option_change",
            "warning_filter_change",
            "database_config_change",
            "render_backend_change",
        ),
        transformation_template="Override <single config key> from <before value> to <issue-derived value> in test scope.",
        expected_effect="Activate the configuration-dependent target branch without mutating global state permanently.",
        oracle_hints=("warning", "render_output", "return_value", "public_property"),
        implementation_modes=("llm_edit", "hybrid"),
    ),
    "LIFECYCLE_TRIGGER": MutationRule(
        name="LIFECYCLE_TRIGGER",
        description="Invoke the framework lifecycle phase required to surface the issue.",
        allowed_targets=("lifecycle", "runner", "framework"),
        risk="medium",
        typical_issue_patterns=("lifecycle", "parser_render", "serialization", "api_call_chain", "configuration"),
        forbidden_when=("runner cannot collect seed",),
        subtypes=(
            "django_model_lifecycle",
            "django_queryset_evaluation",
            "pytest_collection_lifecycle",
            "matplotlib_draw_lifecycle",
            "sklearn_fit_predict_lifecycle",
            "save_load_lifecycle",
        ),
        transformation_template="Add <specific lifecycle transition> around <seed target call> using the recovered protocol.",
        expected_effect="Move execution from object construction into the framework phase where the bug is observable.",
        oracle_hints=("return_value", "render_output", "public_property", "state_change"),
        implementation_modes=("llm_edit", "hybrid"),
    ),
    "FIXTURE_DATA_MUTATION": MutationRule(
        name="FIXTURE_DATA_MUTATION",
        description="Make a small issue-aligned change to existing fixture, factory, mock, database, or file data.",
        allowed_targets=("fixture", "data", "setup_data"),
        risk="medium",
        typical_issue_patterns=("boundary", "null_empty", "dtype_shape", "io_path", "serialization"),
        forbidden_when=("requires unrelated fixture replacement",),
        subtypes=(
            "fixture_field_override",
            "factory_edge_record",
            "mock_return_value_change",
            "mock_side_effect_change",
            "patch_target_change",
            "minimal_database_record_change",
            "file_fixture_content_change",
        ),
        transformation_template="Change <one existing fixture/mock/data element> from <before> to <issue-derived after>.",
        expected_effect="Supply the minimum data shape or value needed for the target API to enter the defect path.",
        oracle_hints=("return_value", "public_property", "type_property", "format_string"),
        implementation_modes=("llm_edit", "hybrid"),
    ),
    "ORACLE_REBIND": MutationRule(
        name="ORACLE_REBIND",
        description="Rebind an unstable assertion to issue-grounded public behavior without changing the trigger.",
        allowed_targets=("oracle", "assertion"),
        risk="low",
        typical_issue_patterns=("warning", "query_sql", "repr_string_format", "parser_render", "cache_state"),
        forbidden_when=("buggy pass or target not hit",),
        subtypes=(
            "exception_to_return_value",
            "warning_capture",
            "query_string_check",
            "format_string_check",
            "render_output_check",
            "public_state_delta",
            "type_property_check",
        ),
        transformation_template="Replace <fragile oracle> with <issue-grounded public observation>; keep trigger unchanged.",
        expected_effect="Observe the same triggered defect through a stable public contract.",
        oracle_hints=("warning", "query_string", "format_string", "render_output", "state_change", "type_property"),
        implementation_modes=("llm_edit", "observation_only"),
    ),
}


def rule_catalog() -> list[dict[str, Any]]:
    return [RULES[name].to_dict() for name in sorted(RULES)]


def trigger_rule_catalog() -> list[dict[str, Any]]:
    """Return only operators legal during trigger planning."""
    return [RULES[name].to_dict() for name in sorted(TRIGGER_RULE_NAMES)]


def infer_issue_pattern(text: str) -> str:
    low = text.lower()
    buckets = [
        ("query_sql", ("sql", "query", "q(", "group by", "where", "annotate")),
        ("null_empty", ("empty", "none", "null", "[]", "blank")),
        ("warning", ("warning", "warns", "deprecation")),
        ("configuration", ("setting", "config", "option", "backend", "flag")),
        ("serialization", ("serialize", "deserialize", "pickle", "json", "yaml")),
        ("repr_string_format", ("repr", "str(", "format", "latex", "pretty", "string")),
        ("parser_render", ("parse", "render", "html", "sphinx", "template")),
        ("dtype_shape", ("dtype", "shape", "array", "dataframe", "dimension")),
        ("cache_state", ("cache", "state", "lazy", "copy", "deepcopy")),
        ("lifecycle", ("fit", "transform", "draw", "save", "load", "migrate", "setup")),
        ("io_path", ("file", "path", "directory", "read", "write")),
        ("exception", ("exception", "error", "crash", "traceback", "raises")),
        ("boundary", ("boundary", "zero", "negative", "large", "min", "max")),
        ("api_call_chain", ("api", "method", "function", "call")),
    ]
    for pattern, keywords in buckets:
        if any(keyword in low for keyword in keywords):
            return pattern
    return "unknown"

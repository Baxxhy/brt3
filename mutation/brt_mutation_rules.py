"""Issue-aligned BRT mutation rule taxonomy."""

from __future__ import annotations

from dataclasses import dataclass, asdict
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


RULES: dict[str, MutationRule] = {
    "ARG_VALUE_REPLACE": MutationRule(
        "ARG_VALUE_REPLACE",
        "改参数、字符串、数字、枚举、None、空容器、dtype、shape、path、timezone、locale。",
        ("argument", "input", "literal", "keyword"),
        "low",
        ("boundary", "null_empty", "dtype_shape", "io_path", "configuration"),
        ("requires setup rewrite",),
    ),
    "ARG_BOUNDARY_EXPAND": MutationRule(
        "ARG_BOUNDARY_EXPAND",
        "加强边界值，如 empty/singleton/duplicate/zero/negative/special char/newline/nan/inf/empty QuerySet/empty Q object。",
        ("argument", "input", "fixture_data"),
        "medium",
        ("boundary", "null_empty", "dtype_shape", "query_sql"),
        ("expected behavior is exact value without boundary evidence",),
    ),
    "OPERATOR_FLIP": MutationRule(
        "OPERATOR_FLIP",
        "只在 issue 涉及 negation/comparison/boolean/order 时使用，如 ==↔!=、Q↔~Q、include/exclude。",
        ("operator", "predicate", "query"),
        "medium",
        ("query_sql", "boundary", "api_call_chain"),
        ("issue has no boolean/comparison/negation evidence",),
    ),
    "CALL_CHAIN_EXTEND": MutationRule(
        "CALL_CHAIN_EXTEND",
        "扩展调用链以触发真实 bug path，如 annotate().values().query、fit().transform()、parse().render()。",
        ("call_chain", "api", "lifecycle"),
        "medium",
        ("api_call_chain", "query_sql", "parser_render", "serialization", "lifecycle"),
        ("seed setup is not executable",),
    ),
    "STATE_MUTATION": MutationRule(
        "STATE_MUTATION",
        "改对象状态、缓存、初始化顺序、重复调用、lazy evaluation、copy/deepcopy、shared reference。",
        ("object_state", "cache", "lifecycle"),
        "medium",
        ("cache_state", "lifecycle", "serialization"),
        ("state is private-only and not public behavior",),
    ),
    "CONFIG_MUTATION": MutationRule(
        "CONFIG_MUTATION",
        "改 settings/backend/flag/mode/format/warning filter/database config/matplotlib backend/pytest config/Django settings。",
        ("config", "settings", "environment"),
        "high",
        ("configuration", "warning", "parser_render"),
        ("setup already unstable",),
    ),
    "LIFECYCLE_TRIGGER": MutationRule(
        "LIFECYCLE_TRIGGER",
        "触发框架生命周期，如 Django model/app/testcase、pytest collection、matplotlib draw、sklearn fit/predict。",
        ("lifecycle", "runner", "framework"),
        "medium",
        ("lifecycle", "parser_render", "serialization", "api_call_chain"),
        ("runner cannot collect seed",),
    ),
    "FIXTURE_DATA_MUTATION": MutationRule(
        "FIXTURE_DATA_MUTATION",
        "基于 seed fixture 做最小数据改动，不重造大环境。",
        ("fixture", "data", "setup_data"),
        "medium",
        ("boundary", "null_empty", "dtype_shape", "io_path"),
        ("requires unrelated fixture replacement",),
    ),
    "ORACLE_REBIND": MutationRule(
        "ORACLE_REBIND",
        "只改断言，不改 trigger/setup；把内部实现断言转成公开行为断言。",
        ("oracle", "assertion"),
        "low",
        ("warning", "query_sql", "repr_string_format", "parser_render", "state_change"),
        ("buggy pass or target not hit",),
    ),
}


def rule_catalog() -> list[dict[str, Any]]:
    return [RULES[name].to_dict() for name in sorted(RULES)]


def trigger_rule_catalog() -> list[dict[str, Any]]:
    """Rules allowed while planning seed mutations and trigger repairs.

    Oracle-only rules are intentionally excluded here. They are handled by the
    observation oracle after the verifier explicitly diagnoses an oracle error.
    """
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

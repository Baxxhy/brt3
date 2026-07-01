"""Normalize and sanitize mutation plans anchored to a HostScaffold."""

from __future__ import annotations

import ast
import re
import textwrap
from typing import Any

from core.schema import BehaviorTarget, HostScaffold, MutationPlan
from mutation.brt_mutation_rules import TRIGGER_RULE_NAMES


ANCHOR_SCOPES = {
    "seed_function_body",
    "setup",
    "fixture",
    "call_chain",
    "assertion",
}
DEFAULT_PRESERVE_CONSTRAINTS = [
    "不要修改 imports",
    "不要删除 fixtures",
    "不要修改 class wrapper",
    "不要改变 runner/nodeid",
    "只在 seed function body 或指定 anchor 内变异",
]
_CONFIG_MARKERS = {
    "override_settings",
    "modify_settings",
    "settings.",
    "monkeypatch.",
    "os.environ",
}
_SETUP_NAMES = {
    "setUp",
    "tearDown",
    "setUpClass",
    "tearDownClass",
    "setup_method",
    "teardown_method",
    "setup_class",
    "teardown_class",
}


def attach_anchored_fields(
    plan: MutationPlan,
    data: dict[str, Any],
    behavior: BehaviorTarget,
    scaffold: HostScaffold,
) -> MutationPlan:
    raw_operators = data.get("selected_operators")
    operators = _strings(raw_operators)
    if not operators:
        operators = list(plan.mutation_ops)
    else:
        routed_operators = set(plan.mutation_ops)
        operators = [
            item for item in operators if item in routed_operators
        ]
    operators = list(dict.fromkeys(operators))[:2]

    raw_targets = data.get("mutation_targets")
    targets: list[dict[str, Any]] = []
    if isinstance(raw_targets, list):
        for raw in raw_targets[:2]:
            if not isinstance(raw, dict):
                continue
            targets.append(_normalize_target(raw, operators, behavior))
    if not targets:
        for raw in plan.selected_rules[:2]:
            targets.append(
                _normalize_target(
                    {
                        "operator": raw.get("rule"),
                        "anchor_scope": raw.get("anchor_scope")
                        or raw.get("mutation_scope")
                        or "seed_function_body",
                        "before_pattern": raw.get("before_pattern"),
                        "after_pattern": raw.get("after_pattern"),
                        "target_api": raw.get("target_api")
                        or raw.get("target_code")
                        or "",
                        "expected_buggy_symptom": raw.get(
                            "expected_buggy_symptom"
                        )
                        or raw.get("expected_buggy_observation")
                        or raw.get("expected_trigger_effect")
                        or "",
                    },
                    operators,
                    behavior,
                )
            )

    raw_oracle = data.get("oracle_strategy")
    if isinstance(raw_oracle, dict):
        oracle = {
            "observation_points": _list_or_scalar(
                raw_oracle.get("observation_points")
            ),
            "assertion_goal": str(raw_oracle.get("assertion_goal") or ""),
            "preferred_assertion_style": str(
                raw_oracle.get("preferred_assertion_style") or ""
            ),
            "avoid": str(raw_oracle.get("avoid") or ""),
        }
    else:
        oracle = {
            "observation_points": [
                str(
                    item.get("name")
                    or item.get("expression")
                    or item.get("text")
                    or ""
                )
                for item in behavior.observation_points
                if isinstance(item, dict)
            ],
            "assertion_goal": str(
                behavior.expected_behavior.get("text") or ""
            ),
            "preferred_assertion_style": str(
                raw_oracle or plan.oracle_strategy or "public_property"
            ),
            "avoid": (
                "assert True, unconditional skip, broad exception swallowing, "
                "pytest.raises(Exception), unrelated sleep"
            ),
        }

    preserve_constraints = _strings(data.get("preserve_constraints"))
    plan.selected_operators = operators
    plan.mutation_targets = targets[:2]
    plan.preserve_constraints = list(
        dict.fromkeys(preserve_constraints + DEFAULT_PRESERVE_CONSTRAINTS)
    )
    plan.oracle_strategy = oracle
    plan.scaffold_hash = scaffold.scaffold_hash
    plan.selected_rules = _align_selected_rules(
        plan.selected_rules,
        plan.mutation_targets,
    )
    plan.mutation_ops = list(plan.selected_operators)
    return plan


def sanitize_anchored_plan(
    plan: MutationPlan,
    scaffold: HostScaffold,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    target_checks: list[dict[str, Any]] = []
    if scaffold.host_scaffold_mode != "ast_scaffold":
        errors.append(
            "HostScaffold is not AST-backed; anchored mutation is unavailable"
        )
    if not plan.selected_operators:
        errors.append("selected_operators is empty")
    if len(plan.selected_operators) > 2:
        errors.append("selected_operators exceeds the maximum of 2")
    invalid_operators = [
        item
        for item in plan.selected_operators
        if item not in TRIGGER_RULE_NAMES
    ]
    if invalid_operators:
        errors.append(
            "invalid selected_operators: " + ", ".join(invalid_operators)
        )
    if not plan.mutation_targets:
        errors.append("mutation_targets is empty")
    if len(plan.mutation_targets) > 2:
        errors.append("mutation_targets exceeds the maximum of 2")

    for index, target in enumerate(plan.mutation_targets[:2]):
        operator = str(target.get("operator") or "")
        scope = str(target.get("anchor_scope") or "")
        before = str(target.get("before_pattern") or "")
        after = str(target.get("after_pattern") or "")
        check: dict[str, Any] = {
            "index": index,
            "operator": operator,
            "anchor_scope": scope,
            "before_pattern": before,
            "before_count": 0,
            "before_pattern_found": False,
            "before_pattern_unique": False,
            "after_pattern_valid_python": False,
        }
        if operator not in TRIGGER_RULE_NAMES:
            errors.append(f"target {index}: invalid operator={operator!r}")
        if operator not in plan.selected_operators:
            errors.append(
                f"target {index}: operator is not in selected_operators"
            )
        if scope not in ANCHOR_SCOPES:
            errors.append(f"target {index}: invalid anchor_scope={scope!r}")
        if not before.strip():
            errors.append(f"target {index}: before_pattern is empty")
        if not after.strip():
            errors.append(f"target {index}: after_pattern is empty")

        anchor_text = _anchor_text(scaffold, scope)
        before_count = anchor_text.count(before) if before else 0
        check["before_count"] = before_count
        check["before_pattern_found"] = before_count > 0
        check["before_pattern_unique"] = before_count == 1
        if before_count == 0:
            errors.append(
                f"target {index}: before_pattern is absent from {scope}"
            )
        elif before_count > 1:
            errors.append(
                f"target {index}: before_pattern is ambiguous in {scope} "
                f"({before_count} matches)"
            )

        after_valid, after_error, after_tree = _parse_snippet(after)
        check["after_pattern_valid_python"] = after_valid
        if not after_valid:
            errors.append(
                f"target {index}: after_pattern is invalid Python: "
                f"{after_error}"
            )
        if after_tree is not None:
            errors.extend(
                f"target {index}: {item}"
                for item in _forbidden_after_patterns(
                    after,
                    after_tree,
                    operator,
                )
            )
        if any(
            re.search(rf"\b{re.escape(name)}\b", after)
            for name in _SETUP_NAMES
        ):
            errors.append(
                f"target {index}: after_pattern attempts to define or alter "
                "setup/teardown protocol"
            )
        if scope == "setup" and operator not in {
            "CONFIG_MUTATION",
            "FIXTURE_DATA_MUTATION",
        }:
            errors.append(
                f"target {index}: setup anchors require CONFIG_MUTATION or "
                "FIXTURE_DATA_MUTATION"
            )
        if scope == "fixture" and operator not in {
            "FIXTURE_DATA_MUTATION",
            "ARG_VALUE_REPLACE",
            "ARG_BOUNDARY_EXPAND",
        }:
            errors.append(
                f"target {index}: fixture anchor uses incompatible operator"
            )
        if operator == "CONFIG_MUTATION" and scope == "setup":
            if not any(marker in after for marker in _CONFIG_MARKERS):
                errors.append(
                    f"target {index}: setup CONFIG_MUTATION is outside the "
                    "local configuration whitelist"
                )
        target_checks.append(check)

    shape_changes = [
        change
        for change in (
            _assignment_shape_change(
                str(target.get("before_pattern") or ""),
                str(target.get("after_pattern") or ""),
            )
            for target in plan.mutation_targets[:2]
        )
        if change
    ]
    if shape_changes and not any(
        str(target.get("anchor_scope") or "") == "assertion"
        for target in plan.mutation_targets[:2]
    ):
        errors.append(
            "input mutation changes value shape "
            + ", ".join(shape_changes)
            + " but no assertion anchor preserves the expected fixed shape"
        )

    found = bool(target_checks) and all(
        item["before_pattern_found"] for item in target_checks
    )
    unique = bool(target_checks) and all(
        item["before_pattern_unique"] for item in target_checks
    )
    plan.before_pattern_found = found
    plan.before_pattern_unique = unique
    plan.sanitizer_status = "PASS" if not errors else "FAIL"
    plan.sanitizer_warnings = [*errors, *warnings]
    return {
        "status": plan.sanitizer_status,
        "errors": errors,
        "warnings": warnings,
        "before_pattern_found": found,
        "before_pattern_unique": unique,
        "targets": target_checks,
    }


def _normalize_target(
    raw: dict[str, Any],
    operators: list[str],
    behavior: BehaviorTarget,
) -> dict[str, Any]:
    operator = str(
        raw.get("operator")
        or raw.get("rule")
        or (operators[0] if operators else "")
    )
    target_api = raw.get("target_api")
    if not target_api:
        target_api = _first_target_api(behavior)
    scope = str(
        raw.get("anchor_scope")
        or raw.get("mutation_scope")
        or "seed_function_body"
    )
    if scope == "trigger":
        scope = "seed_function_body"
    return {
        "operator": operator,
        "anchor_scope": scope,
        "before_pattern": str(raw.get("before_pattern") or ""),
        "after_pattern": str(raw.get("after_pattern") or ""),
        "target_api": str(target_api or ""),
        "expected_buggy_symptom": str(
            raw.get("expected_buggy_symptom")
            or raw.get("expected_buggy_observation")
            or raw.get("expected_trigger_effect")
            or ""
        ),
    }


def _align_selected_rules(
    selected_rules: list[dict[str, Any]],
    targets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_operator: dict[str, dict[str, Any]] = {}
    for item in selected_rules:
        operator = str(item.get("rule") or "")
        if operator and operator not in by_operator:
            by_operator[operator] = dict(item)
    aligned: list[dict[str, Any]] = []
    for target in targets[:2]:
        operator = str(target.get("operator") or "")
        rule = by_operator.get(operator, {"rule": operator})
        rule.update(
            {
                "mutation_scope": "trigger",
                "anchor_scope": target.get("anchor_scope"),
                "before_pattern": target.get("before_pattern"),
                "after_pattern": target.get("after_pattern"),
                "target_api": target.get("target_api"),
                "expected_buggy_observation": target.get(
                    "expected_buggy_symptom"
                ),
            }
        )
        aligned.append(rule)
    return aligned


def _anchor_text(scaffold: HostScaffold, scope: str) -> str:
    if scope in {
        "seed_function_body",
        "call_chain",
        "assertion",
    }:
        return scaffold.seed_function_code
    if scope == "setup":
        return "\n\n".join(
            [*scaffold.setup_methods, *scaffold.teardown_methods]
        )
    if scope == "fixture":
        fixture_helpers = [
            str(item.get("code") or "")
            for item in scaffold.local_helpers
            if str(item.get("name") or "") in scaffold.fixture_args
            or "fixture" in str(item.get("code") or "")
        ]
        return "\n\n".join(
            [scaffold.seed_function_code, *fixture_helpers]
        )
    return scaffold.scaffold_code


def _parse_snippet(
    snippet: str,
) -> tuple[bool, str, ast.Module | None]:
    try:
        return True, "", ast.parse(snippet)
    except SyntaxError as direct_error:
        wrappers = [
            "def _brt_anchor():\n" + textwrap.indent(snippet, "    "),
            f"_brt_anchor = {{{snippet}}}",
            f"_brt_anchor({snippet})",
            f"_brt_anchor = [{snippet}]",
        ]
        last_error = direct_error
        for wrapped in wrappers:
            try:
                return True, "", ast.parse(wrapped)
            except SyntaxError as exc:
                last_error = exc
        return (
            False,
            f"{direct_error.msg}; wrapped: {last_error.msg}",
            None,
        )


def _assignment_shape_change(before: str, after: str) -> str:
    def assigned_value(source: str) -> ast.AST | None:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return None
        if len(tree.body) != 1:
            return None
        node = tree.body[0]
        if isinstance(node, ast.Assign):
            return node.value
        if isinstance(node, ast.AnnAssign):
            return node.value
        return None

    before_value = assigned_value(before)
    after_value = assigned_value(after)
    if before_value is None or after_value is None:
        return ""
    container_types = (ast.Dict, ast.List, ast.Tuple, ast.Set)
    if isinstance(before_value, container_types) and isinstance(
        after_value,
        container_types,
    ):
        before_kind = type(before_value).__name__
        after_kind = type(after_value).__name__
        if before_kind != after_kind:
            return f"{before_kind}->{after_kind}"
    return ""


def _forbidden_after_patterns(
    source: str,
    tree: ast.Module,
    operator: str,
) -> list[str]:
    errors: list[str] = []
    if re.search(r"\b(?:async\s+)?def\s+[A-Za-z_]", source):
        errors.append(
            "after_pattern may not replace a function definition or fixture signature"
        )
    if re.search(r"\b(?:git\s+apply|patch\s+-p|apply_patch)\b", source):
        errors.append("after_pattern may not modify repository source files")
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            errors.append("after_pattern may not modify imports")
        elif isinstance(node, ast.ClassDef):
            errors.append("after_pattern may not define or modify a class wrapper")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name != "_brt_anchor":
                errors.append(
                    "after_pattern may not replace a function definition or fixture signature"
                )
        elif isinstance(node, ast.Assert) and isinstance(
            node.test, ast.Constant
        ) and node.test.value is True:
            errors.append("assert True is forbidden")
        elif isinstance(node, ast.Call):
            dotted = _dotted_name(node.func)
            if dotted in {
                "pytest.skip",
                "pytest.xfail",
                "pytest.importorskip",
                "pytest.mark.skip",
                "unittest.skip",
                "unittest.skipIf",
                "unittest.skipUnless",
                "time.sleep",
                "sleep",
            }:
                errors.append(f"forbidden call in after_pattern: {dotted}")
            if dotted.endswith(".sleep"):
                errors.append(f"forbidden sleep in after_pattern: {dotted}")
            if dotted == "pytest.raises" and node.args:
                if _dotted_name(node.args[0]) in {
                    "Exception",
                    "BaseException",
                }:
                    errors.append("pytest.raises(Exception) is forbidden")
            if dotted.endswith("assertTrue") and node.args:
                if isinstance(node.args[0], ast.Constant) and node.args[0].value is True:
                    errors.append("unconditional assertTrue(True) is forbidden")
        elif isinstance(node, ast.ExceptHandler):
            broad = node.type is None or _dotted_name(node.type) in {
                "Exception",
                "BaseException",
            }
            reraises = any(
                isinstance(item, ast.Raise) for item in ast.walk(node)
            )
            if broad and not reraises:
                errors.append("broad exception swallowing is forbidden")
    if re.search(r"\bassert\s+True\b", source):
        errors.append("assert True is forbidden")
    if operator != "CONFIG_MUTATION" and any(
        marker in source for marker in ("sys.path", "os.environ")
    ):
        errors.append(
            "global import/environment configuration requires CONFIG_MUTATION"
        )
    return list(dict.fromkeys(errors))


def _dotted_name(node: ast.AST | None) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _first_target_api(behavior: BehaviorTarget) -> str:
    for item in behavior.target_apis:
        if isinstance(item, str) and item:
            return item
        if isinstance(item, dict):
            for key in ("qualified_name", "name", "api", "symbol", "target"):
                value = str(item.get(key) or "")
                if value:
                    return value
    return ""


def _strings(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value if str(item).strip()]


def _list_or_scalar(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)] if str(value or "").strip() else []

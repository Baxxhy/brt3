"""AST-aware seed test reranking for BRT generation."""

from __future__ import annotations

import ast
import json
import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.io_utils import read_repo_file
from core.schema import BehaviorTarget, RetrievedTest
from core.utils import truncate_text


AST_SEED_SELECTION_STRATEGY = "ast_aware_rerank_with_icore_fallback"
AST_RERANK_MIN_SCORE = 20.0
ALLOW_SAME_FILE_EXPANSION = False

_TESTCASE_BASE_NAMES = {
    "TestCase",
    "SimpleTestCase",
    "TransactionTestCase",
    "LiveServerTestCase",
    "StaticLiveServerTestCase",
}
_SETUP_METHODS = {
    "setUp",
    "tearDown",
    "setUpClass",
    "tearDownClass",
    "setup_method",
    "teardown_method",
    "setup_class",
    "teardown_class",
}
_CONFIG_SYMBOLS = {
    "settings",
    "override_settings",
    "modify_settings",
    "monkeypatch",
    "pytestconfig",
    "testdir",
    "tmp_path",
    "tmpdir",
}


@dataclass
class SeedCandidate:
    retrieved_rank: int
    test_file: str
    test_entry: str
    nodeid: str
    test_name: str
    enclosing_class: str = ""
    test_code: str = ""
    source_kind: str = "snippet"
    matched_apis: list[dict[str, str]] = field(default_factory=list)
    reusable_parts: list[str] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    fixture_args: list[str] = field(default_factory=list)
    has_self: bool = False
    inherits_testcase: bool = False
    seed_score: float = 0.0
    seed_score_breakdown: dict[str, float] = field(default_factory=dict)
    seed_execution_status: str = ""
    selection_reason: str = ""

    def to_retrieved_test(self, instance_id: str, raw: dict[str, Any]) -> RetrievedTest:
        return RetrievedTest(
            instance_id=instance_id,
            name=self.test_entry or self.test_name,
            file=self.test_file,
            code_content=self.test_code,
            raw=raw,
        )

    def to_record(self, max_code_chars: int = 12000) -> dict[str, Any]:
        return {
            "test_file": self.test_file,
            "test_entry": self.test_entry,
            "nodeid": self.nodeid,
            "test_name": self.test_name,
            "enclosing_class": self.enclosing_class,
            "test_code": truncate_text(self.test_code, max_code_chars),
            "source_kind": self.source_kind,
            "retrieved_rank": self.retrieved_rank,
            "matched_apis": self.matched_apis,
            "reusable_parts": self.reusable_parts,
            "symbols": self.symbols,
            "decorators": self.decorators,
            "fixture_args": self.fixture_args,
            "has_self": self.has_self,
            "inherits_testcase": self.inherits_testcase,
            "seed_score": self.seed_score,
            "seed_score_breakdown": self.seed_score_breakdown,
            "seed_execution_status": self.seed_execution_status,
            "selection_reason": self.selection_reason,
        }


def rank_seed_candidates(
    related_tests: list[RetrievedTest],
    behavior: BehaviorTarget,
    buggy_repo: str,
    max_retrieved: int = 5,
    max_file_tests: int = 200,
    allow_same_file_expansion: bool = ALLOW_SAME_FILE_EXPANSION,
) -> tuple[list[SeedCandidate], dict[str, Any]]:
    diagnostics: dict[str, Any] = {
        "strategy": AST_SEED_SELECTION_STRATEGY,
        "fallback_reason": "",
        "files_considered": [],
        "allow_same_file_expansion": allow_same_file_expansion,
    }
    if not allow_same_file_expansion:
        diagnostics["fallback_reason"] = (
            "same-file AST seed expansion is disabled; use iCoRe anchored seed pack"
        )
        diagnostics["expanded_ast_candidates_disabled"] = True
        diagnostics["candidate_count"] = 0
        diagnostics["top_candidates"] = []
        return [], diagnostics
    candidates: dict[tuple[str, str], SeedCandidate] = {}
    for rank, retrieved in enumerate(related_tests[:max_retrieved]):
        file_candidates, file_diag = _candidates_for_retrieved(
            retrieved,
            behavior,
            buggy_repo,
            rank,
            max_file_tests=max_file_tests,
        )
        diagnostics["files_considered"].append(file_diag)
        for candidate in file_candidates:
            key = (candidate.test_file, candidate.test_entry or candidate.test_name)
            previous = candidates.get(key)
            if previous is None or candidate.seed_score > previous.seed_score:
                candidates[key] = candidate
    ranked = sorted(
        candidates.values(),
        key=lambda item: (item.seed_score, -item.retrieved_rank, item.test_file, item.test_entry),
        reverse=True,
    )
    if not ranked:
        diagnostics["fallback_reason"] = "AST reranking produced no candidates"
    elif ranked[0].seed_score < AST_RERANK_MIN_SCORE:
        diagnostics["fallback_reason"] = (
            f"best AST seed score {ranked[0].seed_score:.1f} is below "
            f"{AST_RERANK_MIN_SCORE:.1f}"
        )
    diagnostics["candidate_count"] = len(ranked)
    diagnostics["top_candidates"] = [item.to_record(max_code_chars=1200) for item in ranked[:10]]
    return ranked, diagnostics


def apply_preflight_score(candidate: SeedCandidate, status: str) -> SeedCandidate:
    previous = candidate.seed_score_breakdown.pop("preflight_status", 0.0)
    candidate.seed_score -= previous
    delta = preflight_status_score(status)
    candidate.seed_execution_status = status
    candidate.seed_score_breakdown["preflight_status"] = delta
    candidate.seed_score += delta
    candidate.selection_reason = _selection_reason(candidate)
    return candidate


def preflight_status_score(status: str) -> float:
    normalized = (status or "").upper()
    if normalized == "PASS":
        return 50.0
    if normalized == "ISSUE_ALIGNED_FAIL":
        return 10.0
    if normalized == "UNRELATED_FAIL":
        return -10.0
    if normalized in {"ASSERTION_FAIL", "RUNTIME_FAIL"}:
        return -20.0
    if normalized in {
        "SETUP_ERROR",
        "IMPORT_ERROR",
        "COLLECT_ERROR",
        "SYNTAX_ERROR",
        "ERROR",
    }:
        return -90.0
    if normalized == "TIMEOUT":
        return -200.0
    return 0.0


def _candidates_for_retrieved(
    retrieved: RetrievedTest,
    behavior: BehaviorTarget,
    buggy_repo: str,
    rank: int,
    max_file_tests: int,
) -> tuple[list[SeedCandidate], dict[str, Any]]:
    rel_file = retrieved.file
    full_source = read_repo_file(buggy_repo, rel_file) if rel_file else ""
    diag: dict[str, Any] = {
        "rank": rank,
        "file": rel_file,
        "name": retrieved.name,
        "full_file_found": bool(full_source),
        "used_snippet_fallback": False,
        "parse_error": "",
    }
    candidates: list[SeedCandidate] = []
    if full_source:
        try:
            candidates = _extract_test_slices(
                full_source,
                rel_file,
                rank,
                retrieved,
                behavior,
                source_kind="full_file",
                max_file_tests=max_file_tests,
            )
        except SyntaxError as exc:
            diag["parse_error"] = str(exc)
    if not candidates:
        diag["used_snippet_fallback"] = True
        try:
            candidates = _extract_test_slices(
                textwrap.dedent(retrieved.code_content or ""),
                rel_file,
                rank,
                retrieved,
                behavior,
                source_kind="snippet",
                max_file_tests=max_file_tests,
            )
        except SyntaxError as exc:
            diag["parse_error"] = str(exc)
            candidates = [
                _snippet_candidate_without_ast(retrieved, behavior, rank)
            ]
    diag["candidate_count"] = len(candidates)
    return candidates, diag


def _extract_test_slices(
    source: str,
    rel_file: str,
    rank: int,
    retrieved: RetrievedTest,
    behavior: BehaviorTarget,
    source_kind: str,
    max_file_tests: int,
) -> list[SeedCandidate]:
    if not source.strip():
        return []
    tree = ast.parse(source)
    slices: list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, ast.ClassDef | None]] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if (
                    isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and _is_test_function(child.name, retrieved.name)
                ):
                    slices.append((child, node))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_test_function(
            node.name,
            retrieved.name,
        ):
            slices.append((node, None))
        if len(slices) >= max_file_tests:
            break
    candidates: list[SeedCandidate] = []
    for func, cls in slices:
        candidate = _candidate_from_ast_node(
            source,
            rel_file,
            rank,
            retrieved,
            behavior,
            func,
            cls,
            source_kind,
        )
        candidates.append(candidate)
    if not candidates and retrieved.code_content:
        candidates.append(_snippet_candidate_without_ast(retrieved, behavior, rank))
    return candidates


def _candidate_from_ast_node(
    source: str,
    rel_file: str,
    rank: int,
    retrieved: RetrievedTest,
    behavior: BehaviorTarget,
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    cls: ast.ClassDef | None,
    source_kind: str,
) -> SeedCandidate:
    test_name = func.name
    enclosing_class = cls.name if cls else ""
    test_entry = f"{enclosing_class}.{test_name}" if enclosing_class else test_name
    nodeid = (
        f"{rel_file}::{enclosing_class}::{test_name}"
        if enclosing_class
        else f"{rel_file}::{test_name}"
    )
    test_code = _node_source(source, func)
    symbols = _symbols_from_ast(func)
    decorators = [_node_source(source, item).strip() for item in func.decorator_list]
    fixture_args = _fixture_args(func)
    has_self = bool(func.args.args and func.args.args[0].arg == "self")
    inherits_testcase = _inherits_testcase(source, cls)
    matched_apis = _matched_apis(symbols, behavior)
    reusable_parts = _reusable_parts(
        source,
        func,
        cls,
        decorators,
        fixture_args,
        has_self,
        inherits_testcase,
        symbols,
        matched_apis,
    )
    breakdown = _score_breakdown(
        candidate_file=rel_file,
        test_name=test_name,
        test_entry=test_entry,
        retrieved=retrieved,
        retrieved_rank=rank,
        behavior=behavior,
        matched_apis=matched_apis,
        reusable_parts=reusable_parts,
        symbols=symbols,
        func=func,
    )
    score = sum(breakdown.values())
    candidate = SeedCandidate(
        retrieved_rank=rank,
        test_file=rel_file,
        test_entry=test_entry,
        nodeid=nodeid,
        test_name=test_name,
        enclosing_class=enclosing_class,
        test_code=test_code,
        source_kind=source_kind,
        matched_apis=matched_apis,
        reusable_parts=reusable_parts,
        symbols=sorted(symbols),
        decorators=[item for item in decorators if item],
        fixture_args=fixture_args,
        has_self=has_self,
        inherits_testcase=inherits_testcase,
        seed_score=score,
        seed_score_breakdown=breakdown,
    )
    candidate.selection_reason = _selection_reason(candidate)
    return candidate


def _snippet_candidate_without_ast(
    retrieved: RetrievedTest,
    behavior: BehaviorTarget,
    rank: int,
) -> SeedCandidate:
    code = textwrap.dedent(retrieved.code_content or "")
    test_name = _guess_test_name(code) or _last_name_segment(retrieved.name)
    test_entry = _normalized_test_entry(retrieved.name) or test_name
    symbols = set(_identifier_tokens(code))
    matched_apis = _matched_apis(symbols, behavior)
    reusable_parts = []
    if "assert" in code:
        reusable_parts.append("assert style")
    if any(name in symbols for name in _CONFIG_SYMBOLS):
        reusable_parts.append("config/state fixture")
    breakdown = _score_breakdown(
        candidate_file=retrieved.file,
        test_name=test_name,
        test_entry=test_entry,
        retrieved=retrieved,
        retrieved_rank=rank,
        behavior=behavior,
        matched_apis=matched_apis,
        reusable_parts=reusable_parts,
        symbols=symbols,
        func=None,
    )
    score = sum(breakdown.values())
    candidate = SeedCandidate(
        retrieved_rank=rank,
        test_file=retrieved.file,
        test_entry=test_entry,
        nodeid=f"{retrieved.file}::{test_entry}" if test_entry else retrieved.file,
        test_name=test_name,
        test_code=code,
        source_kind="snippet",
        matched_apis=matched_apis,
        reusable_parts=reusable_parts,
        symbols=sorted(symbols),
        seed_score=score,
        seed_score_breakdown=breakdown,
    )
    candidate.selection_reason = _selection_reason(candidate)
    return candidate


def _score_breakdown(
    candidate_file: str,
    test_name: str,
    test_entry: str,
    retrieved: RetrievedTest,
    retrieved_rank: int,
    behavior: BehaviorTarget,
    matched_apis: list[dict[str, str]],
    reusable_parts: list[str],
    symbols: set[str],
    func: ast.AST | None,
) -> dict[str, float]:
    breakdown: dict[str, float] = {
        "icore_rank": max(5.0, 50.0 - 5.0 * retrieved_rank),
    }
    if _same_file(candidate_file, retrieved.file):
        breakdown["retrieved_file"] = 8.0
    if _entry_matches(test_entry, test_name, retrieved.name):
        breakdown["retrieved_entry"] = 25.0
    elif _last_name_segment(retrieved.name) == test_name and test_name:
        breakdown["retrieved_name_last_segment"] = 10.0

    related_file_bonus, related_name_bonus = _related_seed_bonus(
        candidate_file,
        test_entry,
        test_name,
        behavior,
    )
    if related_file_bonus:
        breakdown["behavior_related_file"] = related_file_bonus
    if related_name_bonus:
        breakdown["behavior_related_name"] = related_name_bonus

    exact_api_count = sum(1 for item in matched_apis if item["match_type"] == "exact_or_dotted")
    last_api_count = sum(1 for item in matched_apis if item["match_type"] == "last_segment")
    if exact_api_count:
        breakdown["target_api_exact_or_dotted"] = min(90.0, 35.0 * exact_api_count)
    if last_api_count:
        breakdown["target_api_last_segment"] = min(45.0, 15.0 * last_api_count)

    feature_bonus = _feature_bonus(symbols, reusable_parts, func, behavior)
    breakdown.update(feature_bonus)
    return breakdown


def _feature_bonus(
    symbols: set[str],
    reusable_parts: list[str],
    func: ast.AST | None,
    behavior: BehaviorTarget,
) -> dict[str, float]:
    bonus: dict[str, float] = {}
    if func is not None:
        if any(isinstance(node, (ast.Dict, ast.List, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)) for node in ast.walk(func)):
            bonus["mutable_or_structured_input"] = 12.0
        if any(isinstance(node, ast.Compare) for node in ast.walk(func)):
            bonus["boundary_or_expected_value"] = 8.0
        if any(isinstance(node, ast.Call) and node.args for node in ast.walk(func)):
            bonus["call_with_arguments"] = 8.0
    if "config/state fixture" in reusable_parts:
        bonus["config_or_state_context"] = 10.0
    if "call chain" in reusable_parts:
        bonus["call_chain"] = 8.0
    if any(part in reusable_parts for part in {"fixture args", "class setup", "TestCase class"}):
        bonus["reusable_setup"] = 12.0
    if any(part in reusable_parts for part in {"assert style", "pytest.raises", "warnings assertion"}):
        bonus["assertion_style"] = 8.0
    hint_slots = {
        str(item.get("slot") or "").lower()
        for item in behavior.mutation_hints
        if isinstance(item, dict)
    }
    if hint_slots and symbols:
        hint_text = json.dumps(behavior.mutation_hints, ensure_ascii=False).lower()
        if any(symbol.lower() in hint_text for symbol in list(symbols)[:200]):
            bonus["mutation_hint_symbol_overlap"] = 8.0
        if "config" in hint_slots and "config/state fixture" in reusable_parts:
            bonus["mutation_hint_config_context"] = 8.0
        if hint_slots.intersection({"input", "object_state", "state"}) and (
            "mutable_or_structured_input" in bonus or "call_with_arguments" in bonus
        ):
            bonus["mutation_hint_mutable_context"] = 8.0
    return bonus


def _related_seed_bonus(
    candidate_file: str,
    test_entry: str,
    test_name: str,
    behavior: BehaviorTarget,
) -> tuple[float, float]:
    file_bonus = 0.0
    name_bonus = 0.0
    for index, item in enumerate(behavior.related_test_seeds):
        if not isinstance(item, dict):
            continue
        weight = max(0.0, 1.0 - min(index, 10) * 0.05)
        test_file = str(item.get("test_file") or item.get("file") or "")
        seed_name = str(item.get("test_name") or item.get("name") or "")
        if test_file and _same_file(candidate_file, test_file):
            file_bonus = max(file_bonus, 35.0 * weight)
        if seed_name and _entry_matches(test_entry, test_name, seed_name):
            name_bonus = max(name_bonus, 45.0 * weight)
        elif seed_name and _last_name_segment(seed_name) == test_name:
            name_bonus = max(name_bonus, 25.0 * weight)
    return file_bonus, name_bonus


def _matched_apis(symbols: set[str], behavior: BehaviorTarget) -> list[dict[str, str]]:
    matches: list[dict[str, str]] = []
    normalized_symbols = {_normalize_identifier(symbol) for symbol in symbols if symbol}
    normalized_symbols.discard("")
    for api in _target_api_names(behavior):
        normalized_api = _normalize_identifier(api)
        if not normalized_api:
            continue
        api_last = normalized_api.rsplit(".", 1)[-1]
        exact_match = _find_exact_or_dotted_match(normalized_api, normalized_symbols)
        if exact_match:
            matches.append(
                {
                    "api": api,
                    "match_type": "exact_or_dotted",
                    "matched_symbol": exact_match,
                }
            )
            continue
        last_match = next(
            (
                symbol
                for symbol in sorted(normalized_symbols)
                if symbol.rsplit(".", 1)[-1] == api_last
            ),
            "",
        )
        if last_match:
            matches.append(
                {
                    "api": api,
                    "match_type": "last_segment",
                    "matched_symbol": last_match,
                }
            )
    return matches


def _find_exact_or_dotted_match(api: str, symbols: set[str]) -> str:
    api_parts = api.split(".")
    for symbol in sorted(symbols):
        if symbol == api or symbol.endswith(f".{api}"):
            return symbol
        symbol_parts = symbol.split(".")
        if len(api_parts) >= 2 and len(symbol_parts) >= 2:
            if api_parts[-2:] == symbol_parts[-2:]:
                return symbol
    return ""


def _target_api_names(behavior: BehaviorTarget) -> list[str]:
    names: list[str] = []
    for item in behavior.target_apis:
        if isinstance(item, dict) and item.get("name"):
            names.append(str(item["name"]))
    return list(dict.fromkeys(names))


def _reusable_parts(
    source: str,
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    cls: ast.ClassDef | None,
    decorators: list[str],
    fixture_args: list[str],
    has_self: bool,
    inherits_testcase: bool,
    symbols: set[str],
    matched_apis: list[dict[str, str]],
) -> list[str]:
    parts: list[str] = []
    if cls is not None:
        parts.append("class wrapper")
        if _class_has_setup(cls):
            parts.append("class setup")
    if fixture_args:
        parts.append("fixture args")
    if has_self:
        parts.append("self-bound test method")
    if inherits_testcase:
        parts.append("TestCase class")
    if decorators:
        parts.append("decorators")
    if _has_assertion(func):
        parts.append("assert style")
    if _has_pytest_raises(symbols):
        parts.append("pytest.raises")
    if _has_warning_assertion(symbols):
        parts.append("warnings assertion")
    if any(symbol in _CONFIG_SYMBOLS for symbol in symbols):
        parts.append("config/state fixture")
    if any("." in symbol for symbol in symbols):
        parts.append("call chain")
    if matched_apis:
        parts.append("target api reference")
    return list(dict.fromkeys(parts))


def _symbols_from_ast(node: ast.AST) -> set[str]:
    symbols: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            symbols.add(child.id)
        elif isinstance(child, ast.Attribute):
            dotted = _dotted_name(child)
            if dotted:
                symbols.add(dotted)
            symbols.add(child.attr)
        elif isinstance(child, ast.Call):
            dotted = _dotted_name(child.func)
            if dotted:
                symbols.add(dotted)
                symbols.add(dotted.rsplit(".", 1)[-1])
    return {symbol for symbol in symbols if symbol}


def _dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    if isinstance(node, ast.Call):
        return _dotted_name(node.func)
    if isinstance(node, ast.Subscript):
        return _dotted_name(node.value)
    return ""


def _fixture_args(func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    args = [arg.arg for arg in func.args.args]
    if args and args[0] in {"self", "cls"}:
        args = args[1:]
    return args


def _inherits_testcase(source: str, cls: ast.ClassDef | None) -> bool:
    if cls is None:
        return False
    for base in cls.bases:
        name = _dotted_name(base) or _node_source(source, base)
        last = name.rsplit(".", 1)[-1]
        if last in _TESTCASE_BASE_NAMES or last.endswith("TestCase"):
            return True
    return False


def _class_has_setup(cls: ast.ClassDef) -> bool:
    return any(
        isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
        and child.name in _SETUP_METHODS
        for child in cls.body
    )


def _has_assertion(func: ast.AST) -> bool:
    for node in ast.walk(func):
        if isinstance(node, ast.Assert):
            return True
        if isinstance(node, ast.Call):
            name = _dotted_name(node.func)
            if name.rsplit(".", 1)[-1].startswith("assert"):
                return True
    return False


def _has_pytest_raises(symbols: set[str]) -> bool:
    return "pytest.raises" in symbols or "raises" in symbols


def _has_warning_assertion(symbols: set[str]) -> bool:
    return bool({"pytest.warns", "warns", "warnings", "catch_warnings"} & symbols)


def _node_source(source: str, node: ast.AST) -> str:
    try:
        return ast.get_source_segment(source, node) or ""
    except Exception:  # noqa: BLE001
        return ""


def _is_test_function(name: str, retrieved_name: str) -> bool:
    if name.startswith("test"):
        return True
    return bool(retrieved_name and _last_name_segment(retrieved_name) == name)


def _entry_matches(test_entry: str, test_name: str, wanted: str) -> bool:
    normalized = _normalized_test_entry(wanted)
    return bool(normalized and normalized in {test_entry, test_name})


def _normalized_test_entry(name: str) -> str:
    raw = str(name or "").strip()
    if not raw:
        return ""
    raw = raw.replace("::", ".")
    parts = [part for part in raw.split(".") if part]
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return parts[-1] if parts else ""


def _last_name_segment(name: str) -> str:
    return _normalized_test_entry(name).rsplit(".", 1)[-1]


def _same_file(left: str, right: str) -> bool:
    return _normalize_path(left) == _normalize_path(right)


def _normalize_path(path: str) -> str:
    return str(Path(str(path or "")).as_posix()).strip("/")


def _normalize_identifier(value: str) -> str:
    text = str(value or "").strip()
    text = text.replace("::", ".")
    text = re.sub(r"\(\)$", "", text)
    pieces = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text)
    if not pieces:
        return ""
    if "." in text:
        dotted = ".".join(pieces)
        return dotted
    return pieces[-1]


def _identifier_tokens(code: str) -> list[str]:
    return re.findall(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*", code)


def _guess_test_name(code: str) -> str:
    match = re.search(r"def\s+(test_[A-Za-z0-9_]+)\s*\(", code or "")
    return match.group(1) if match else ""


def _selection_reason(candidate: SeedCandidate) -> str:
    positives = [
        key
        for key, value in sorted(
            candidate.seed_score_breakdown.items(),
            key=lambda item: item[1],
            reverse=True,
        )
        if value > 0
    ]
    negatives = [
        key
        for key, value in sorted(
            candidate.seed_score_breakdown.items(),
            key=lambda item: item[1],
        )
        if value < 0
    ]
    reason = "AST rerank selected by " + ", ".join(positives[:5])
    if negatives:
        reason += "; penalties: " + ", ".join(negatives[:3])
    return reason

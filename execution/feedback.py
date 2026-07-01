"""Main feedback loop for BRT3."""

from __future__ import annotations

import copy
import hashlib
import json
import fcntl
import shlex
import shutil
import subprocess
import traceback
import re
from dataclasses import fields
from pathlib import Path
from typing import Any

from execution.executor import run_command_in_conda
from generation.generator import (
    format_effective_source_context,
    generate_candidate,
    repair_candidate,
)
from context.host_context import build_host_context
from context.host_scaffold import (
    apply_scaffold_to_protocol,
    extract_host_scaffold,
    fallback_host_scaffold,
)
from context.protocol_recovery import (
    audit_protocol_context,
    audit_recovered_protocol,
    recover_test_protocol,
)
from context.seed_reranker import (
    AST_RERANK_MIN_SCORE,
    AST_SEED_SELECTION_STRATEGY,
    apply_preflight_score,
    rank_seed_candidates,
)
from mutation.seed_mutator import build_mutation_plan
from mutation.brt_mutation_rules import TRIGGER_RULE_NAMES, infer_issue_pattern
from mutation.mutation_effectiveness import load_mutation_prior, prioritize_rules
from oracle.observation_oracle import rebind_observation_oracle
from validation.strict_semantic_verifier import verify_strict_semantics
from execution.icore_runtime import (
    disable_editable_install_command,
    dump_spec,
    ensure_icore_environment,
    env_name_for,
    env_lock_path,
    harden_editable_install_command,
    icore_setup_command,
    icore_test_command,
    first_test_selector,
    make_instance_spec,
)
from context.issue_rewriter import rewrite_issue
from oracle.oracle import run_observation_probe, synthesize_oracle
from patching.patch_utils import run_surrogate_patch_loop
from core.schema import (
    CandidateCheckpoint,
    DualVersionResult,
    ExecutionResult,
    FinalResult,
    HostContext,
    HostScaffold,
    InstanceContext,
    MutationPlan,
    ProtocolRecovery,
    RetrievedTest,
    VerifierDecision,
)
from core.utils import ensure_dir, safe_json_dump, write_text
from validation.verifier import verify_buggy_only


MECHANICAL_SEED_FAILURE_STATUSES = frozenset(
    {"SETUP_ERROR", "IMPORT_ERROR", "SYNTAX_ERROR", "COLLECT_ERROR", "TIMEOUT", "ERROR"}
)
SEED_SELECTION_STRATEGY = (
    "icore_original_order_first_mechanically_executable_top5"
)
SEED_PREFLIGHT_LIMIT = 5


def _seed_is_mechanically_executable(status: str) -> bool:
    return status not in MECHANICAL_SEED_FAILURE_STATUSES


def _run_local(command: str, cwd: str, timeout: int = 300) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            command,
            shell=True,
            executable="/bin/bash",
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
        return {
            "command": command,
            "cwd": cwd,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "timeout": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "cwd": cwd,
            "returncode": 124,
            "stdout": exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b"").decode("utf-8", errors="replace"),
            "stderr": exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode("utf-8", errors="replace"),
            "timeout": True,
        }


def _refresh_candidate_command(context: InstanceContext, candidate: Any) -> None:
    candidate.command = icore_test_command(
        context.repo,
        str(context.metadata.get("version") or ""),
        candidate.candidate_repo_path,
        first_test_selector(candidate.code),
    )


def _checkpoint_score(
    execution: ExecutionResult,
    decision: VerifierDecision,
    dual: DualVersionResult | None,
) -> tuple[int, str]:
    if (
        dual
        and dual.status in {"F2P_SUCCESS", "SURROGATE_F2P_SUCCESS"}
        and decision.decision == "accept"
    ):
        return 300, "buggy fail and independently generated surrogate patch pass"
    if decision.decision == "accept" and execution.returncode != 0:
        return 200, "buggy fail accepted by semantic verifier"
    if execution.returncode != 0 and execution.status not in {
        "SETUP_ERROR",
        "SYNTAX_ERROR",
        "COLLECT_ERROR",
        "TIMEOUT",
    }:
        return 100, "executable buggy failure not accepted as issue-aligned"
    if execution.returncode == 0:
        return 10, "test passes on buggy source"
    return 0, f"non-executable candidate: {execution.status}"


def _llm_stats(llm_client: Any) -> dict[str, Any]:
    stats_fn = getattr(llm_client, "stats", None)
    if callable(stats_fn):
        try:
            data = stats_fn()
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _host_signature(host: Any) -> str:
    try:
        payload = json.dumps(host.to_dict(), ensure_ascii=False, sort_keys=True)
    except Exception:
        payload = repr(host)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _latest_plan_fields(mutation_plans: list[Any]) -> dict[str, Any]:
    if not mutation_plans:
        return {
            "mutation_plan": {},
            "mutation_rules_used": [],
            "mutation_risk": "medium",
            "issue_pattern": "unknown",
            "oracle_strategy": "",
            "mutation_plan_mode": "",
            "selected_operators": [],
            "before_pattern_found": False,
            "before_pattern_unique": False,
            "sanitizer_status": "",
        }
    latest = mutation_plans[-1]
    rules = list(dict.fromkeys(op for plan in mutation_plans for op in getattr(plan, "mutation_ops", [])))
    raw_oracle = getattr(latest, "oracle_strategy", "") or ""
    oracle_strategy = (
        str(raw_oracle.get("preferred_assertion_style") or "")
        if isinstance(raw_oracle, dict)
        else str(raw_oracle)
    )
    return {
        "mutation_plan": latest.to_dict(),
        "mutation_rules_used": rules,
        "mutation_risk": getattr(latest, "risk", "medium") or "medium",
        "issue_pattern": getattr(latest, "issue_pattern", "unknown") or "unknown",
        "oracle_strategy": oracle_strategy,
        "mutation_plan_mode": getattr(latest, "mutation_plan_mode", "") or "",
        "selected_operators": list(
            getattr(latest, "selected_operators", []) or []
        ),
        "before_pattern_found": bool(
            getattr(latest, "before_pattern_found", False)
        ),
        "before_pattern_unique": bool(
            getattr(latest, "before_pattern_unique", False)
        ),
        "sanitizer_status": getattr(latest, "sanitizer_status", "") or "",
    }


def _stable_result_fields(
    llm_client: Any,
    mutation_plans: list[Any] | None = None,
    mode: str = "deep",
    deterministic: bool = True,
    selected_seed_signature: str = "",
    seed_reused: bool = False,
    seed_change_reason: str = "",
    analysis_prior_used: bool = False,
    regression_guard_triggered: bool = False,
    regression_guard_reason: str = "",
    surrogate_patch_used: bool = False,
    observation_oracle_used: bool = False,
    strict_verifier_level: str = "",
    final_selection_reason: str = "",
    seed_selection_mode: str = "",
    seed_candidates_count: int = 0,
    selected_seed_score: float = 0.0,
    matched_apis: list[dict[str, Any]] | None = None,
    seed_score_breakdown: dict[str, Any] | None = None,
    seed_selection_fallback_reason: str = "",
    primary_seed_test: dict[str, Any] | None = None,
    host_scaffold: HostScaffold | None = None,
    candidate: Any | None = None,
    final_code: str = "",
) -> dict[str, Any]:
    fields = _llm_stats(llm_client)
    mutation_plans = mutation_plans or []
    latest_plan = mutation_plans[-1] if mutation_plans else None
    fallback_reasons = [
        str(getattr(host_scaffold, "fallback_reason", "") or ""),
        str(getattr(latest_plan, "fallback_reason", "") or ""),
        str(getattr(candidate, "fallback_reason", "") or ""),
    ]
    fields.update(
        {
            "deterministic": deterministic,
            "mode": mode,
            "selected_seed_signature": selected_seed_signature,
            "seed_reused": seed_reused,
            "seed_change_reason": seed_change_reason,
            "surrogate_patch_used": surrogate_patch_used,
            "surrogate_patch_decision_used_for_ranking_only": True,
            "observation_oracle_used": observation_oracle_used,
            "strict_verifier_level": strict_verifier_level,
            "analysis_prior_used": analysis_prior_used,
            "regression_guard_triggered": regression_guard_triggered,
            "regression_guard_reason": regression_guard_reason,
            "final_selection_reason": final_selection_reason,
            "seed_selection_mode": seed_selection_mode,
            "seed_candidates_count": seed_candidates_count,
            "selected_seed_score": selected_seed_score,
            "matched_apis": matched_apis or [],
            "seed_score_breakdown": seed_score_breakdown or {},
            "seed_selection_fallback_reason": seed_selection_fallback_reason,
            "primary_seed_test": primary_seed_test or {},
            "host_scaffold_mode": (
                host_scaffold.host_scaffold_mode if host_scaffold else ""
            ),
            "scaffold_hash": (
                host_scaffold.scaffold_hash if host_scaffold else ""
            ),
            "seed_function_hash": (
                host_scaffold.seed_function_hash if host_scaffold else ""
            ),
            "generator_mode": str(
                getattr(candidate, "generator_mode", "") or ""
            ),
            "fallback_reason": "; ".join(
                dict.fromkeys(item for item in fallback_reasons if item)
            ),
            "final_test_hash": (
                hashlib.sha256(final_code.encode("utf-8")).hexdigest()
                if final_code
                else str(getattr(candidate, "final_test_hash", "") or "")
            ),
        }
    )
    fields.update(_latest_plan_fields(mutation_plans))
    return fields


def _analysis_prior_hint(
    analysis_prior_dir: str,
    context: InstanceContext,
    behavior: Any,
) -> str:
    if not analysis_prior_dir:
        return ""
    prior = load_mutation_prior(analysis_prior_dir)
    if not prior:
        return ""
    issue_text = " ".join(
        [
            str(getattr(behavior, "issue_summary", "") or ""),
            str(getattr(behavior, "trigger_condition", {}).get("text") if hasattr(behavior, "trigger_condition") else ""),
            str(getattr(behavior, "error_symptom", {}).get("text") if hasattr(behavior, "error_symptom") else ""),
            str(getattr(behavior, "expected_behavior", {}).get("text") if hasattr(behavior, "expected_behavior") else ""),
        ]
    )
    pattern = infer_issue_pattern(issue_text)
    ordered = prioritize_rules(prior, context.repo, pattern, list(TRIGGER_RULE_NAMES))
    hint = {
        "repo": context.repo,
        "issue_pattern": pattern,
        "preferred_rules": ordered[:5],
        "avoid_large_setup_changes": True,
    }
    return json.dumps(hint, ensure_ascii=False)


def _dataclass_from_mapping(cls: Any, data: dict[str, Any]) -> Any:
    allowed = {item.name for item in fields(cls)}
    return cls(**{key: value for key, value in (data or {}).items() if key in allowed})


def _save_checkpoint(
    output_dir: str,
    attempt_id: int,
    candidate: Any,
    execution: ExecutionResult,
    decision: VerifierDecision,
    dual: DualVersionResult | None,
) -> CandidateCheckpoint:
    checkpoint_dir = ensure_dir(Path(output_dir) / "checkpoints")
    code_path = str(Path(checkpoint_dir) / f"candidate_attempt_{attempt_id}.py")
    write_text(code_path, candidate.code)
    score, reason = _checkpoint_score(execution, decision, dual)
    checkpoint = CandidateCheckpoint(
        instance_id=candidate.instance_id,
        round_id=attempt_id,
        code_path=code_path,
        score=score,
        reason=reason,
        execution=execution.to_dict(),
        verifier=decision.to_dict(),
        surrogate=dual.to_dict() if dual else {},
    )
    checkpoint.save_json(
        str(Path(checkpoint_dir) / f"candidate_attempt_{attempt_id}.json")
    )
    return checkpoint


def _missing_dependency_hint(log: str) -> str:
    patterns = [
        r"No module named ['\"]([^'\"]+)['\"]",
        r"requires the ([A-Za-z0-9_.-]+) python package",
    ]
    for pattern in patterns:
        match = re.search(pattern, log, flags=re.IGNORECASE)
        if match:
            return match.group(1).split(".", 1)[0]
    return ""


def _find_declared_requirement(repo_path: str, module_hint: str) -> str:
    if not module_hint:
        return ""
    token = re.sub(r"\d+$", "", module_hint.lower().replace("_", "-"))
    root = Path(repo_path)
    candidates = sorted(root.glob("requirements*.txt"))
    candidates += sorted(root.glob("requirements/*.txt"))
    candidates += sorted(root.glob("*/requirements*.txt"))
    candidates += sorted(root.glob("*/*/requirements*.txt"))
    for path in candidates:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith(("#", "-", "git+", "http://", "https://")):
                continue
            normalized = line.lower().replace("_", "-")
            if token and token in normalized:
                return line
    return ""


def _recover_declared_dependency(
    context: InstanceContext,
    execution: ExecutionResult,
    conda_env: str,
    timeout: int,
    no_conda: bool,
    output_dir: str,
    round_id: int,
) -> bool:
    log = execution.stdout + "\n" + execution.stderr
    hint = _missing_dependency_hint(log)
    requirement = _find_declared_requirement(context.buggy_repo_path, hint)
    if not requirement:
        return False
    dependency_lock = env_lock_path(conda_env or "__direct_host__", "project_setup")
    dependency_lock.parent.mkdir(parents=True, exist_ok=True)
    with open(dependency_lock, "w", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        install_result = run_command_in_conda(
            f"python -m pip install {shlex.quote(requirement)}",
            context.buggy_repo_path,
            conda_env,
            timeout,
            no_conda,
            None,
            context.instance_id,
        )
    safe_json_dump(
        {
            "module_hint": hint,
            "requirement": requirement,
            "execution": install_result.to_dict(),
        },
        str(Path(output_dir) / f"dependency_recovery_round_{round_id}.json"),
    )
    return install_result.returncode == 0


def prepare_instance_worktree(
    context: InstanceContext,
    output_dir: str,
    conda_env: str,
    timeout: int,
    no_conda: bool,
) -> tuple[str, dict[str, Any]]:
    source_repo = context.buggy_repo_path
    base_commit = context.base_commit
    if not source_repo or not base_commit:
        return source_repo, {"status": "SKIPPED", "reason": "missing source repo or base_commit", "repo_path": source_repo}
    worktree = Path(output_dir) / "worktree"
    prepare_cache = Path(output_dir) / "repo_prepare.json"
    if prepare_cache.is_file() and worktree.is_dir():
        try:
            cached_prepare = json.loads(prepare_cache.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            cached_prepare = {}
        if cached_prepare.get("status") == "PASS":
            cached_prepare = dict(cached_prepare)
            cached_prepare["status"] = "PASS"
            cached_prepare["reused_prepared_worktree"] = True
            cached_prepare["repo_path"] = str(worktree)
            return str(worktree), cached_prepare
    if worktree.exists():
        _run_local(
            f"git worktree remove --force {shlex.quote(str(worktree))}",
            source_repo,
            timeout=300,
        )
        if worktree.exists():
            shutil.rmtree(worktree)
    ensure_dir(worktree.parent)
    add_cmd = f"git worktree add --force --detach {shlex.quote(str(worktree))} {shlex.quote(base_commit)}"
    add_result = _run_local(add_cmd, source_repo, timeout=300)
    if add_result["returncode"] != 0:
        clone_cmd = f"git clone --shared {shlex.quote(source_repo)} {shlex.quote(str(worktree))}"
        clone_result = _run_local(clone_cmd, str(Path(output_dir)), timeout=600)
        checkout_result = _run_local(f"git checkout --force {shlex.quote(base_commit)}", str(worktree), timeout=300) if clone_result["returncode"] == 0 else {}
        add_result = {"worktree_add": add_result, "clone": clone_result, "checkout": checkout_result}
        if clone_result["returncode"] != 0 or checkout_result.get("returncode") != 0:
            return str(worktree), {"status": "WORKTREE_ERROR", "details": add_result, "repo_path": str(worktree)}
    submodule_result = _run_local(
        "git submodule update --init --recursive",
        str(worktree),
        timeout=600,
    )
    cached_astropy_helpers = Path(source_repo) / "astropy_helpers"
    worktree_astropy_helpers = worktree / "astropy_helpers"
    if (
        context.repo == "astropy/astropy"
        and cached_astropy_helpers.is_dir()
        and not worktree_astropy_helpers.exists()
    ):
        shutil.copytree(
            cached_astropy_helpers,
            worktree_astropy_helpers,
            symlinks=True,
        )
    version = str(context.metadata.get("version") or "")
    environment_setup_commit = str(
        context.metadata.get("environment_setup_commit") or base_commit
    )
    spec = make_instance_spec(
        context.instance_id,
        context.repo,
        version,
        base_commit,
        environment_setup_commit,
    )
    dump_spec(spec, str(Path(output_dir) / "icore_exec_spec.json"))
    resolved_env = conda_env or env_name_for(context.repo, version)
    env_result = ensure_icore_environment(
        spec, resolved_env, str(worktree), timeout
    )
    if env_result.get("returncode") != 0:
        return str(worktree), {
            "status": "ENV_CREATE_ERROR",
            "source_repo": source_repo,
            "repo_path": str(worktree),
            "base_commit": base_commit,
            "env_name": resolved_env,
            "environment": env_result,
            "worktree": add_result,
        }
    setup = icore_setup_command(spec, str(worktree))
    setup_lock = env_lock_path(resolved_env, "project_setup")
    setup_lock.parent.mkdir(parents=True, exist_ok=True)
    with open(setup_lock, "w", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        setup_result = run_command_in_conda(
            setup,
            str(worktree),
            resolved_env,
            timeout,
            no_conda,
            None,
            context.instance_id,
        )
        setup_log = setup_result.stdout + "\n" + setup_result.stderr
        if (
            setup_result.returncode != 0
            and "missing the 'build_editable' hook" in setup_log
            and " -e ." in setup
        ):
            fallback_setup = disable_editable_install_command(setup)
            fallback_result = run_command_in_conda(
                fallback_setup,
                str(worktree),
                resolved_env,
                timeout,
                no_conda,
                None,
                context.instance_id,
            )
            if fallback_result.returncode == 0:
                setup = fallback_setup
                setup_result = fallback_result
        setup_log = setup_result.stdout + "\n" + setup_result.stderr
        if (
            setup_result.returncode != 0
            and (
                "uninstall-no-record-file" in setup_log
                or "AssertionError: Egg-link" in setup_log
                or "Egg-link" in setup_log
            )
            and "python -m pip install" in setup
            and " -e ." in setup
        ):
            fallback_setup = harden_editable_install_command(setup)
            if fallback_setup == setup:
                fallback_setup = disable_editable_install_command(setup)
            fallback_result = run_command_in_conda(
                fallback_setup,
                str(worktree),
                resolved_env,
                timeout,
                no_conda,
                None,
                context.instance_id,
            )
            if fallback_result.returncode == 0:
                setup = fallback_setup
                setup_result = fallback_result
        setup_log = setup_result.stdout + "\n" + setup_result.stderr
        if (
            setup_result.returncode != 0
            and (
                "AssertionError: Egg-link" in setup_log
                or "Egg-link" in setup_log
                or "missing the 'build_editable' hook" in setup_log
            )
            and " -e ." in setup
        ):
            fallback_setup = disable_editable_install_command(setup)
            fallback_result = run_command_in_conda(
                fallback_setup,
                str(worktree),
                resolved_env,
                timeout,
                no_conda,
                None,
                context.instance_id,
            )
            if fallback_result.returncode == 0:
                setup = fallback_setup
                setup_result = fallback_result
    status = "PASS" if setup_result.returncode == 0 else "SETUP_ERROR"
    return str(worktree), {
        "status": status,
        "source_repo": source_repo,
        "repo_path": str(worktree),
        "base_commit": base_commit,
        "environment_setup_commit": environment_setup_commit,
        "env_name": resolved_env,
        "environment": env_result,
        "worktree": add_result,
        "submodule": submodule_result,
        "setup_command": setup,
        "setup_execution": setup_result.to_dict(),
    }


def run_instance_pipeline(
    context: InstanceContext,
    llm_client: Any,
    output_dir: str,
    conda_env: str = "",
    timeout: int = 120,
    no_conda: bool = False,
    max_feedback_rounds: int = 3,
    max_env_rounds: int | None = None,
    max_brt_rounds: int | None = None,
    max_patch_rounds: int = 3,
    validation_mode: str = "buggy_only",
    patched_repo_base: str = "",
    patch_file: str = "",
    generate_only: bool = False,
    enable_protocol_recovery: bool = True,
    enable_seed_mutation: bool = True,
    enable_observation_oracle: bool = True,
    enable_strict_semantic_verifier: bool = True,
    mode: str = "deep",
    deterministic: bool = True,
    analysis_prior_dir: str = "",
    use_mutation_prior: bool = True,
    issue_rewrite_dir: str = "",
    precomputed_behavior_target: dict[str, Any] | None = None,
    issue_rewrite_source: str = "",
) -> FinalResult:
    ensure_dir(output_dir)
    ensure_dir(Path(output_dir) / "prompts")
    ensure_dir(Path(output_dir) / "responses")
    ensure_dir(Path(output_dir) / "logs")
    mode = mode if mode in {"fast", "deep"} else "deep"
    analysis_prior_used = bool(analysis_prior_dir and use_mutation_prior)
    if mode == "fast":
        max_env_rounds = 2 if max_env_rounds is None else min(max_env_rounds, 2)
        max_brt_rounds = 2 if max_brt_rounds is None else min(max_brt_rounds, 2)
        max_patch_rounds = min(max_patch_rounds, 1)
    else:
        max_env_rounds = 3 if max_env_rounds is None else max_env_rounds
        max_brt_rounds = 3 if max_brt_rounds is None else max_brt_rounds
        max_patch_rounds = max(1, max_patch_rounds)
    try:
        if not generate_only:
            prepared_repo, prepare_meta = prepare_instance_worktree(context, output_dir, conda_env, timeout, no_conda)
            context.buggy_repo_path = prepared_repo
            safe_json_dump(prepare_meta, str(Path(output_dir) / "repo_prepare.json"))
            if prepare_meta.get("status") in {
                "WORKTREE_ERROR",
                "ENV_CREATE_ERROR",
                "SETUP_ERROR",
            }:
                result = FinalResult(
                    instance_id=context.instance_id,
                    status="SETUP_ERROR",
                    final_test_path="",
                    rounds_used=0,
                    buggy_execution=prepare_meta.get("setup_execution", {}),
                    dual_version_result={"mode": validation_mode, "status": "SKIPPED"},
                    behavior_target={},
                    host_context={},
                    observation_report={},
                    notes="repository worktree/setup failed before BRT generation",
                    protocol_recovery_enabled=enable_protocol_recovery,
                    seed_mutation_enabled=enable_seed_mutation,
                    observation_oracle_enabled=enable_observation_oracle,
                    strict_verifier_enabled=enable_strict_semantic_verifier,
                    final_reason="repository worktree/setup failed before BRT generation",
                    **_stable_result_fields(
                        llm_client,
                        mode=mode,
                        deterministic=deterministic,
                        analysis_prior_used=analysis_prior_used,
                    ),
                )
                result.save_json(str(Path(output_dir) / "summary.json"))
                return result
        else:
            safe_json_dump({"status": "SKIPPED", "reason": "generate_only"}, str(Path(output_dir) / "repo_prepare.json"))
        local_behavior_path = Path(output_dir) / "behavior_target.json"
        if precomputed_behavior_target is not None:
            from context.issue_rewriter import behavior_from_dict

            behavior = behavior_from_dict(
                context.instance_id,
                precomputed_behavior_target,
            )
            safe_json_dump(
                {
                    "mode": "precomputed_aggregate",
                    "source_path": str(Path(issue_rewrite_source).resolve()),
                    "instance_id": context.instance_id,
                },
                str(Path(output_dir) / "issue_rewrite_source.json"),
            )
        elif issue_rewrite_dir:
            from context.issue_rewriter import load_behavior_target

            cached_behavior_path = (
                Path(issue_rewrite_dir) / context.instance_id / "behavior_target.json"
            )
            behavior = load_behavior_target(
                cached_behavior_path,
                expected_instance_id=context.instance_id,
            )
            safe_json_dump(
                {
                    "mode": "precomputed",
                    "source_path": str(cached_behavior_path.resolve()),
                    "instance_id": context.instance_id,
                },
                str(Path(output_dir) / "issue_rewrite_source.json"),
            )
        elif local_behavior_path.exists():
            from context.issue_rewriter import load_behavior_target

            behavior = load_behavior_target(
                local_behavior_path,
                expected_instance_id=context.instance_id,
            )
        else:
            behavior = rewrite_issue(context, llm_client, output_dir)
        behavior.save_json(str(local_behavior_path))
        protocol = None
        seed_fallback_used = False
        seed_attempts: list[dict[str, Any]] = []
        # Prefer AST-aware function-level reranking, while keeping the original
        # iCoRe-order selector below as the final fallback.
        seeds_to_try = list(context.retrieved_tests)[:SEED_PREFLIGHT_LIMIT]
        related_test = seeds_to_try[0] if seeds_to_try else None
        host = None
        selected_seed_path = Path(output_dir) / "selected_seed.json"
        seed_fallback_path = Path(output_dir) / "seed_fallback.json"
        seed_rerank_path = Path(output_dir) / "seed_rerank.json"
        host_cache_path = Path(output_dir) / "host_context.json"
        protocol_cache_path = Path(output_dir) / "protocol_recovery.json"
        seed_reused = False
        seed_change_reason = ""
        seed_selection_mode = "fallback_old"
        seed_candidates_count = 0
        selected_seed_score = 0.0
        matched_apis: list[dict[str, Any]] = []
        seed_score_breakdown: dict[str, Any] = {}
        seed_selection_fallback_reason = ""
        primary_seed_test: dict[str, Any] = {}
        seed_rerank_diagnostics: dict[str, Any] = {}

        def _seed_rank(seed: Any) -> int:
            for index, item in enumerate(context.retrieved_tests):
                if item.file == seed.file and item.name == seed.name:
                    return index
            return -1

        saved_seed: dict[str, Any] = {}
        if deterministic and selected_seed_path.is_file():
            try:
                saved_seed = json.loads(
                    selected_seed_path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError, TypeError):
                saved_seed = {}
        saved_file = str(saved_seed.get("selected_seed_file") or "")
        saved_name = str(saved_seed.get("selected_seed_name") or "")
        saved_primary_seed = (
            saved_seed.get("primary_seed_test")
            if isinstance(saved_seed.get("primary_seed_test"), dict)
            else {}
        )
        matched_seed = next(
            (
                item
                for item in seeds_to_try
                if item.file == saved_file and item.name == saved_name
            ),
            None,
        )
        if matched_seed is None and saved_file and saved_name:
            matched_seed = RetrievedTest(
                instance_id=context.instance_id,
                name=saved_name,
                file=saved_file,
                code_content=str(saved_primary_seed.get("test_code") or ""),
                raw={"source": "selected_seed_cache"},
            )
        cache_matches_strategy = (
            saved_seed.get("selection_strategy") == AST_SEED_SELECTION_STRATEGY
            and matched_seed is not None
        )

        if (
            deterministic
            and host_cache_path.is_file()
            and cache_matches_strategy
        ):
            try:
                host = _dataclass_from_mapping(
                    HostContext,
                    json.loads(host_cache_path.read_text(encoding="utf-8")),
                )
                related_test = matched_seed
                selected_seed_signature = _host_signature(host)
                seed_reused = True
                seed_fallback_used = bool(saved_seed.get("fallback_used"))
                seed_change_reason = str(
                    saved_seed.get("fallback_reason")
                    or saved_seed.get("seed_change_reason")
                    or ""
                )
                seed_selection_mode = str(
                    saved_seed.get("seed_selection_mode") or seed_selection_mode
                )
                seed_candidates_count = int(saved_seed.get("seed_candidates_count") or 0)
                try:
                    selected_seed_score = float(saved_seed.get("selected_seed_score") or 0.0)
                except (TypeError, ValueError):
                    selected_seed_score = 0.0
                cached_matched_apis = saved_seed.get("matched_apis")
                matched_apis = cached_matched_apis if isinstance(cached_matched_apis, list) else []
                cached_breakdown = saved_seed.get("seed_score_breakdown")
                seed_score_breakdown = cached_breakdown if isinstance(cached_breakdown, dict) else {}
                seed_selection_fallback_reason = str(
                    saved_seed.get("seed_selection_fallback_reason") or ""
                )
                primary_seed_test = saved_primary_seed
                if enable_protocol_recovery and protocol_cache_path.is_file():
                    protocol = _dataclass_from_mapping(
                        ProtocolRecovery,
                        json.loads(protocol_cache_path.read_text(encoding="utf-8")),
                    )
                if seed_fallback_path.is_file():
                    cached_fallback = json.loads(
                        seed_fallback_path.read_text(encoding="utf-8")
                    )
                    cached_attempts = cached_fallback.get("attempts")
                    if isinstance(cached_attempts, list):
                        seed_attempts = [
                            dict(item)
                            for item in cached_attempts
                            if isinstance(item, dict)
                        ]
                if not seed_attempts:
                    seed_attempts.append(
                        {
                            "rank": _seed_rank(related_test),
                            "file": related_test.file,
                            "name": related_test.name,
                            "execution_status": host.seed_execution_status,
                            "selected": True,
                            "protocol_risks": (
                                protocol.protocol_risks if protocol else []
                            ),
                            "reused_from_cache": True,
                        }
                    )
                else:
                    for attempt in seed_attempts:
                        attempt["selected"] = (
                            attempt.get("file") == related_test.file
                            and attempt.get("name") == related_test.name
                        )
            except Exception as exc:  # noqa: BLE001
                host = None
                protocol = None
                seed_reused = False
                seed_change_reason = f"cached HostContext/ProtocolRecovery could not be loaded: {exc}"
        elif deterministic and host_cache_path.is_file():
            seed_change_reason = (
                "cached seed selection used a previous strategy or is no "
                "longer available in the top-5 iCoRe results"
            )

        if host is None:
            ast_ranked = []
            try:
                ast_ranked, seed_rerank_diagnostics = rank_seed_candidates(
                    seeds_to_try,
                    behavior,
                    context.buggy_repo_path,
                    max_retrieved=SEED_PREFLIGHT_LIMIT,
                )
                seed_candidates_count = len(ast_ranked)
            except Exception as exc:  # noqa: BLE001
                seed_selection_fallback_reason = f"AST seed reranking failed: {exc}"
                seed_rerank_diagnostics = {
                    "strategy": AST_SEED_SELECTION_STRATEGY,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
            if ast_ranked:
                best_ast_score = ast_ranked[0].seed_score
                if best_ast_score < AST_RERANK_MIN_SCORE:
                    seed_selection_fallback_reason = (
                        f"best AST seed score {best_ast_score:.1f} is below "
                        f"{AST_RERANK_MIN_SCORE:.1f}"
                    )
                else:
                    evaluated_ast: list[
                        tuple[Any, RetrievedTest, HostContext, ProtocolRecovery | None]
                    ] = []
                    for candidate in ast_ranked[:SEED_PREFLIGHT_LIMIT]:
                        seed = candidate.to_retrieved_test(
                            context.instance_id,
                            {
                                "source": "ast_rerank",
                                "retrieved_rank": candidate.retrieved_rank,
                                "source_kind": candidate.source_kind,
                            },
                        )
                        candidate_host = build_host_context(
                            context.instance_id, seed, context.buggy_repo_path, behavior,
                            context.retrieved_code, conda_env, timeout, no_conda,
                            skip_execution=generate_only, repo=context.repo,
                            version=str(context.metadata.get("version") or ""),
                        )
                        apply_preflight_score(
                            candidate,
                            candidate_host.seed_execution_status,
                        )
                        candidate_protocol = recover_test_protocol(
                            context.instance_id, seed, context.buggy_repo_path, behavior,
                            context.retrieved_code, context.repo,
                            str(context.metadata.get("version") or ""),
                        ) if enable_protocol_recovery else None
                        attempt = candidate.to_record(max_code_chars=1200)
                        attempt.update({
                            "rank": candidate.retrieved_rank,
                            "file": seed.file,
                            "name": seed.name,
                            "execution_status": candidate_host.seed_execution_status,
                            "selected": False,
                            "selection_mode": "ast_rerank",
                            "protocol_risks": (
                                candidate_protocol.protocol_risks
                                if candidate_protocol
                                else []
                            ),
                        })
                        seed_attempts.append(attempt)
                        evaluated_ast.append((candidate, seed, candidate_host, candidate_protocol))
                    viable_ast = [
                        item
                        for item in evaluated_ast
                        if generate_only
                        or _seed_is_mechanically_executable(item[2].seed_execution_status)
                    ]
                    if viable_ast:
                        selected_candidate, related_test, host, protocol = max(
                            viable_ast,
                            key=lambda item: (
                                item[0].seed_score,
                                -item[0].retrieved_rank,
                                item[0].test_file,
                                item[0].test_entry,
                            ),
                        )
                        seed_selection_mode = "ast_rerank"
                        selected_seed_score = selected_candidate.seed_score
                        matched_apis = selected_candidate.matched_apis
                        seed_score_breakdown = selected_candidate.seed_score_breakdown
                        primary_seed_test = selected_candidate.to_record()
                        for attempt in seed_attempts:
                            attempt["selected"] = (
                                attempt.get("selection_mode") == "ast_rerank"
                                and attempt.get("file") == related_test.file
                                and attempt.get("name") == related_test.name
                            )
                    else:
                        seed_selection_fallback_reason = (
                            "AST seed rerank preflight found no mechanically "
                            "executable candidate"
                        )
            else:
                seed_selection_fallback_reason = (
                    seed_selection_fallback_reason
                    or "AST seed reranking produced no candidates"
                )

        if host is None:
            if not seed_selection_fallback_reason:
                seed_selection_fallback_reason = (
                    "AST seed reranking unavailable; using legacy iCoRe order"
                )
            first_candidate_seed = None
            first_candidate_host = None
            first_candidate_protocol = None
            for seed_index, seed in enumerate(seeds_to_try):
                rank = _seed_rank(seed)
                candidate_host = build_host_context(
                    context.instance_id, seed, context.buggy_repo_path, behavior,
                    context.retrieved_code, conda_env, timeout, no_conda,
                    skip_execution=generate_only, repo=context.repo,
                    version=str(context.metadata.get("version") or ""),
                )
                candidate_protocol = recover_test_protocol(
                    context.instance_id, seed, context.buggy_repo_path, behavior,
                    context.retrieved_code, context.repo,
                    str(context.metadata.get("version") or ""),
                ) if enable_protocol_recovery else None
                if seed_index == 0:
                    first_candidate_seed = seed
                    first_candidate_host = candidate_host
                    first_candidate_protocol = candidate_protocol
                seed_attempts.append({
                    "rank": rank if rank >= 0 else seed_index,
                    "file": seed.file,
                    "name": seed.name,
                    "execution_status": candidate_host.seed_execution_status,
                    "selected": False,
                    "selection_mode": "fallback_old",
                    "protocol_risks": candidate_protocol.protocol_risks if candidate_protocol else [],
                })
                if generate_only or _seed_is_mechanically_executable(
                    candidate_host.seed_execution_status
                ):
                    related_test, host, protocol = (
                        seed,
                        candidate_host,
                        candidate_protocol,
                    )
                    seed_attempts[-1]["selected"] = True
                    seed_fallback_used = seed_index > 0
                    if seed_fallback_used:
                        seed_change_reason = (
                            "previous seed failed mechanical execution "
                            "qualification; tried next iCoRe-ranked seed"
                        )
                    for attempt in seed_attempts:
                        attempt["selected"] = (
                            attempt.get("selection_mode") == "fallback_old"
                            and attempt.get("file") == related_test.file
                            and attempt.get("name") == related_test.name
                        )
                    break
                if seed_index < len(seeds_to_try) - 1:
                    seed_fallback_used = True
                    seed_change_reason = (
                        "previous seed failed mechanical execution "
                        "qualification; tried next iCoRe-ranked seed"
                    )
            else:
                if first_candidate_seed is not None and first_candidate_host is not None:
                    related_test, host, protocol = (
                        first_candidate_seed,
                        first_candidate_host,
                        first_candidate_protocol,
                    )
                    for attempt in seed_attempts:
                        attempt["selected"] = (
                            attempt.get("selection_mode") == "fallback_old"
                            and attempt.get("file") == related_test.file
                            and attempt.get("name") == related_test.name
                        )
                    seed_fallback_used = True
                    seed_change_reason = (
                        "all top-5 iCoRe-ranked seeds failed mechanical "
                        "execution qualification; falling back to the first "
                        "iCoRe-ranked seed"
                    )
                else:
                    related_test = None
                    host = None
                    protocol = None
        if host is None:
            host = build_host_context(
                context.instance_id, None, context.buggy_repo_path, behavior,
                context.retrieved_code, conda_env, timeout, no_conda,
                skip_execution=generate_only, repo=context.repo,
                version=str(context.metadata.get("version") or ""),
            )
        try:
            host_scaffold = extract_host_scaffold(
                context.instance_id,
                primary_seed_test,
                related_test,
                host,
                context.buggy_repo_path,
            )
        except Exception as exc:  # noqa: BLE001
            host_scaffold = fallback_host_scaffold(
                context.instance_id,
                host,
                related_test.file if related_test else host.host_file,
                related_test.name if related_test else host.seed_test_name,
                f"HostScaffold extraction failed: {exc}",
            )
        host_scaffold.save_json(
            str(Path(output_dir) / "host_scaffold.json")
        )
        if protocol is not None:
            try:
                protocol = apply_scaffold_to_protocol(
                    protocol,
                    host_scaffold,
                )
            except Exception as exc:  # noqa: BLE001
                protocol.protocol_risks.append(
                    f"HostScaffold protocol merge failed; retained old "
                    f"ProtocolRecovery: {exc}"
                )
        selected_seed_signature = _host_signature(host)
        safe_json_dump(
            {
                "selection_strategy": AST_SEED_SELECTION_STRATEGY,
                "legacy_selection_strategy": SEED_SELECTION_STRATEGY,
                "seed_selection_mode": seed_selection_mode,
                "seed_candidates_count": seed_candidates_count,
                "selected_seed_score": selected_seed_score,
                "matched_apis": matched_apis,
                "seed_score_breakdown": seed_score_breakdown,
                "seed_selection_fallback_reason": seed_selection_fallback_reason,
                "primary_seed_test": primary_seed_test,
                "diagnostics": seed_rerank_diagnostics,
                "attempts": seed_attempts,
            },
            str(seed_rerank_path),
        )
        safe_json_dump(
            {
                "selection_strategy": AST_SEED_SELECTION_STRATEGY,
                "legacy_selection_strategy": SEED_SELECTION_STRATEGY,
                "seed_selection_mode": seed_selection_mode,
                "fallback_used": seed_fallback_used,
                "fallback_reason": (
                    seed_change_reason if seed_fallback_used else ""
                ),
                "seed_selection_fallback_reason": seed_selection_fallback_reason,
                "seed_candidates_count": seed_candidates_count,
                "selected_seed_score": selected_seed_score,
                "matched_apis": matched_apis,
                "seed_score_breakdown": seed_score_breakdown,
                "primary_seed_test": primary_seed_test,
                "attempts": seed_attempts,
            },
            str(seed_fallback_path),
        )
        safe_json_dump(
            {
                "selection_strategy": AST_SEED_SELECTION_STRATEGY,
                "legacy_selection_strategy": SEED_SELECTION_STRATEGY,
                "seed_selection_mode": seed_selection_mode,
                "selected_seed_file": related_test.file if related_test else "",
                "selected_seed_name": related_test.name if related_test else "",
                "seed_rank": _seed_rank(related_test) if related_test else -1,
                "fallback_used": seed_fallback_used,
                "fallback_reason": seed_change_reason if seed_fallback_used else "",
                "seed_selection_fallback_reason": seed_selection_fallback_reason,
                "seed_candidates_count": seed_candidates_count,
                "selected_seed_score": selected_seed_score,
                "matched_apis": matched_apis,
                "seed_score_breakdown": seed_score_breakdown,
                "primary_seed_test": primary_seed_test,
                "seed_execution_status": host.seed_execution_status,
                "host_context_signature": selected_seed_signature,
                "seed_reused": seed_reused,
                "seed_change_reason": seed_change_reason,
                "created_at": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
            },
            str(selected_seed_path),
        )
        protocol_context_audit: dict[str, Any] = {}
        if protocol is not None:
            try:
                protocol = audit_recovered_protocol(
                    protocol, behavior, related_test, llm_client, output_dir
                )
            except Exception as exc:  # noqa: BLE001
                protocol.protocol_risks.append(f"协议模型审计失败，保留 AST 恢复结果：{exc}")
            protocol.save_json(str(Path(output_dir) / "protocol_recovery.json"))
            if related_test is not None:
                try:
                    protocol_context_audit = audit_protocol_context(
                        protocol,
                        behavior,
                        related_test,
                        list(context.retrieved_tests)[:5],
                        context.retrieved_code,
                        llm_client,
                        output_dir,
                    )
                except Exception as exc:  # noqa: BLE001
                    protocol_context_audit = {
                        "audit_failed": True,
                        "error": str(exc),
                    }
                    safe_json_dump(
                        protocol_context_audit,
                        str(Path(output_dir) / "protocol_context_audit.json"),
                    )
        host.save_json(str(Path(output_dir) / "host_context.json"))
        candidate = None
        execution = None
        decision = None
        observation = None
        dual = None
        final_code = ""
        mutation_plans = []
        strict_result = None
        oracle_type = ""
        oracle_rebound = False
        env_budget = max_env_rounds if max_env_rounds is not None else max_feedback_rounds
        brt_budget = max_brt_rounds if max_brt_rounds is not None else max_feedback_rounds
        analysis_prior_hint = _analysis_prior_hint(analysis_prior_dir, context, behavior) if analysis_prior_used else ""
        if analysis_prior_hint:
            safe_json_dump(
                {"analysis_prior_dir": analysis_prior_dir, "hint": json.loads(analysis_prior_hint)},
                str(Path(output_dir) / "analysis_prior_used.json"),
            )
        initial_plan = None
        initial_plan_path = Path(output_dir) / "mutation_round_0_plan.json"
        if enable_seed_mutation and deterministic and initial_plan_path.is_file():
            try:
                initial_plan = _dataclass_from_mapping(
                    MutationPlan,
                    json.loads(initial_plan_path.read_text(encoding="utf-8")),
                )
                if initial_plan.scaffold_hash != host_scaffold.scaffold_hash:
                    initial_plan = None
            except Exception:  # noqa: BLE001
                initial_plan = None
        if enable_seed_mutation and initial_plan is None:
            initial_plan = build_mutation_plan(
                context.instance_id, 0, behavior, host, host_scaffold,
                protocol, llm_client, output_dir,
                analysis_prior_hint=analysis_prior_hint,
                protocol_context_audit=protocol_context_audit,
            )
        if initial_plan:
            mutation_plans.append(initial_plan)
        candidate = generate_candidate(
            context.instance_id,
            behavior,
            host,
            related_test,
            context.retrieved_code,
            llm_client,
            output_dir,
            context.buggy_repo_path,
            0,
            write_to_repo=not generate_only,
            protocol=protocol,
            mutation_plan=initial_plan,
            host_scaffold=host_scaffold,
        )
        write_text(str(Path(output_dir) / "mutation_round_0_test.py"), candidate.code)
        _refresh_candidate_command(context, candidate)
        if generate_only:
            final_code = candidate.code
            write_text(str(Path(output_dir) / "final_test.py"), final_code)
            execution_stub = {"status": "SKIPPED", "reason": "generate_only"}
            result = FinalResult(
                instance_id=context.instance_id,
                status="GENERATED",
                final_test_path=str(Path(output_dir) / "final_test.py"),
                rounds_used=1,
                buggy_execution=execution_stub,
                dual_version_result={"mode": "buggy_only", "status": "SKIPPED"},
                behavior_target=behavior.to_dict(),
                host_context=host.to_dict(),
                observation_report={},
                notes="generate_only: complete same-directory test file generated without execution",
                protocol_recovery_enabled=enable_protocol_recovery,
                seed_mutation_enabled=enable_seed_mutation,
                observation_oracle_enabled=enable_observation_oracle,
                strict_verifier_enabled=enable_strict_semantic_verifier,
                selected_seed_file=related_test.file if related_test else "",
                selected_seed_name=related_test.name if related_test else "",
                seed_fallback_used=seed_fallback_used,
                mutation_ops=initial_plan.mutation_ops if initial_plan else [],
                final_reason="generate_only: generation completed without execution",
                **_stable_result_fields(
                    llm_client,
                    mutation_plans,
                    mode=mode,
                    deterministic=deterministic,
                    selected_seed_signature=selected_seed_signature,
                    seed_reused=seed_reused,
                    seed_change_reason=seed_change_reason,
                    analysis_prior_used=analysis_prior_used,
                    final_selection_reason="generate_only",
                    seed_selection_mode=seed_selection_mode,
                    seed_candidates_count=seed_candidates_count,
                    selected_seed_score=selected_seed_score,
                    matched_apis=matched_apis,
                    seed_score_breakdown=seed_score_breakdown,
                    seed_selection_fallback_reason=seed_selection_fallback_reason,
                    primary_seed_test=primary_seed_test,
                    host_scaffold=host_scaffold,
                    candidate=candidate,
                    final_code=final_code,
                ),
            )
            result.save_json(str(Path(output_dir) / "summary.json"))
            return result

        env_rounds_used = 0
        for env_round in range(env_budget):
            execution = run_command_in_conda(candidate.command, context.buggy_repo_path, conda_env, timeout, no_conda, behavior, context.instance_id)
            safe_json_dump(execution.to_dict(), str(Path(output_dir) / f"env_execution_round_{env_round}.json"))
            write_text(str(Path(output_dir) / "logs" / f"env_execution_round_{env_round}.log"), execution.stdout + "\n" + execution.stderr)
            env_rounds_used = env_round + 1
            if execution.status not in {"SETUP_ERROR", "SYNTAX_ERROR", "COLLECT_ERROR"}:
                break
            if execution.status == "SETUP_ERROR" and _recover_declared_dependency(
                context,
                execution,
                conda_env,
                timeout,
                no_conda,
                output_dir,
                env_round,
            ):
                continue
            if env_round == env_budget - 1:
                break
            candidate = repair_candidate(
                context.instance_id,
                behavior,
                host,
                candidate,
                execution,
                llm_client,
                output_dir,
                env_round + 1,
                "setup",
                context.retrieved_code,
                buggy_repo=context.buggy_repo_path,
                protocol=protocol,
                host_scaffold=host_scaffold,
            )
            _refresh_candidate_command(context, candidate)
        if execution is not None and execution.status in {"SETUP_ERROR", "SYNTAX_ERROR", "COLLECT_ERROR"}:
            final_code = candidate.code
            write_text(str(Path(output_dir) / "final_test.py"), final_code)
            result = FinalResult(
                instance_id=context.instance_id,
                status="ENV_UNRESOLVED",
                final_test_path=str(Path(output_dir) / "final_test.py"),
                rounds_used=env_rounds_used,
                buggy_execution=execution.to_dict(),
                dual_version_result={
                    "mode": validation_mode,
                    "status": "SKIPPED_ENV_UNRESOLVED",
                },
                behavior_target=behavior.to_dict(),
                host_context=host.to_dict(),
                observation_report={},
                notes=(
                    f"environment probe remained {execution.status} after "
                    f"{env_rounds_used} rounds; BRT and dual-version validation skipped"
                ),
                protocol_recovery_enabled=enable_protocol_recovery,
                seed_mutation_enabled=enable_seed_mutation,
                observation_oracle_enabled=enable_observation_oracle,
                strict_verifier_enabled=enable_strict_semantic_verifier,
                selected_seed_file=related_test.file if related_test else "",
                selected_seed_name=related_test.name if related_test else "",
                seed_fallback_used=seed_fallback_used,
                mutation_ops=[op for plan in mutation_plans for op in plan.mutation_ops],
                final_reason="environment qualification remained unresolved",
                **_stable_result_fields(
                    llm_client,
                    mutation_plans,
                    mode=mode,
                    deterministic=deterministic,
                    selected_seed_signature=selected_seed_signature,
                    seed_reused=seed_reused,
                    seed_change_reason=seed_change_reason,
                    analysis_prior_used=analysis_prior_used,
                    final_selection_reason="environment qualification unresolved",
                    seed_selection_mode=seed_selection_mode,
                    seed_candidates_count=seed_candidates_count,
                    selected_seed_score=selected_seed_score,
                    matched_apis=matched_apis,
                    seed_score_breakdown=seed_score_breakdown,
                    seed_selection_fallback_reason=seed_selection_fallback_reason,
                    primary_seed_test=primary_seed_test,
                    host_scaffold=host_scaffold,
                    candidate=candidate,
                    final_code=final_code,
                ),
            )
            result.save_json(str(Path(output_dir) / "summary.json"))
            return result
        else:
            brt_attempt = 0
            semantic_repairs_used = 0
            late_setup_repairs_used = 0
            # Round 0 is the initial BRT. Environment qualification already
            # has its own budget above and must not expand this checkpoint loop.
            max_brt_attempts = 1 + max(0, brt_budget)
            checkpoints: list[CandidateCheckpoint] = []
            best_score = -1
            best_index = -1
            best_candidate = None
            best_execution = None
            best_decision = None
            best_dual = None
            best_observation = None
            best_strict_result = None
            while brt_attempt < max_brt_attempts:
                if brt_attempt > 0 or execution is None:
                    execution = run_command_in_conda(candidate.command, context.buggy_repo_path, conda_env, timeout, no_conda, behavior, context.instance_id)
                safe_json_dump(execution.to_dict(), str(Path(output_dir) / f"execution_round_{brt_attempt}.json"))
                write_text(str(Path(output_dir) / "logs" / f"execution_round_{brt_attempt}.log"), execution.stdout + "\n" + execution.stderr)
                effective_source = format_effective_source_context(
                    behavior, context.retrieved_code, context.buggy_repo_path
                )
                if enable_strict_semantic_verifier:
                    decision, strict_result = verify_strict_semantics(
                        context.issue_text, behavior, protocol, candidate,
                        execution, effective_source, llm_client, output_dir,
                        brt_attempt,
                    )
                else:
                    decision = verify_buggy_only(
                        context.issue_text, behavior, candidate, execution,
                        llm_client, host.to_dict(), effective_source,
                    )
                safe_json_dump(decision.to_dict(), str(Path(output_dir) / f"verifier_round_{brt_attempt}.json"))
                candidate_dual = None
                if decision.decision == "accept":
                    if validation_mode == "surrogate_patch":
                        validation_dir = str(
                            Path(output_dir)
                            / "candidate_validations"
                            / f"attempt_{brt_attempt}"
                        )
                        ensure_dir(validation_dir)
                        candidate_dual = run_surrogate_patch_loop(
                            context.instance_id,
                            behavior,
                            candidate,
                            context.retrieved_code,
                            context.buggy_repo_path,
                            execution,
                            llm_client,
                            validation_dir,
                            conda_env,
                            timeout,
                            no_conda,
                            max_patch_rounds,
                        )
                    else:
                        candidate_dual = DualVersionResult(
                            context.instance_id,
                            "buggy_only",
                            execution.to_dict(),
                            {},
                            "SKIPPED",
                            "Only buggy source was executed.",
                        )
                checkpoint = _save_checkpoint(
                    output_dir,
                    brt_attempt,
                    candidate,
                    execution,
                    decision,
                    candidate_dual,
                )
                checkpoints.append(checkpoint)
                if checkpoint.score > best_score:
                    best_score = checkpoint.score
                    best_index = len(checkpoints) - 1
                    best_candidate = copy.deepcopy(candidate)
                    best_execution = copy.deepcopy(execution)
                    best_decision = copy.deepcopy(decision)
                    best_dual = copy.deepcopy(candidate_dual)
                    best_observation = copy.deepcopy(observation)
                    best_strict_result = copy.deepcopy(strict_result)
                if decision.decision == "accept":
                    surrogate_status = candidate_dual.status if candidate_dual else ""
                    safe_json_dump(
                        {
                            "decision": "keep_candidate",
                            "reason": (
                                "candidate is semantically accepted; surrogate patch "
                                "success is used as a ranking signal"
                            ),
                            "surrogate_status": surrogate_status,
                        },
                        str(Path(output_dir) / f"surrogate_feedback_round_{brt_attempt}.json"),
                    )
                    break
                focus = "trigger"
                if decision.decision == "repair_setup":
                    if late_setup_repairs_used >= env_budget:
                        final_code = candidate.code
                        write_text(str(Path(output_dir) / "final_test.py"), final_code)
                        break
                    focus = "setup"
                    late_setup_repairs_used += 1
                elif decision.decision == "repair_oracle":
                    if semantic_repairs_used >= max(0, brt_budget):
                        final_code = candidate.code
                        write_text(str(Path(output_dir) / "final_test.py"), final_code)
                        break
                    next_round = env_rounds_used + brt_attempt + 1
                    if enable_observation_oracle:
                        candidate, observation, oracle_type = rebind_observation_oracle(
                            behavior, protocol, candidate,
                            execution.stdout + "\n" + execution.stderr,
                            llm_client, output_dir, context.buggy_repo_path,
                            conda_env, timeout, no_conda, context.repo,
                            str(context.metadata.get("version") or ""), next_round,
                        )
                        final_code = candidate.code
                        oracle_rebound = True
                    else:
                        observation = run_observation_probe(
                            behavior, candidate, llm_client, output_dir,
                            context.buggy_repo_path, conda_env, timeout, no_conda,
                            context.repo, str(context.metadata.get("version") or ""),
                        )
                        final_code = synthesize_oracle(
                            behavior, candidate, observation,
                            execution.stdout + "\n" + execution.stderr,
                            llm_client, output_dir,
                        )
                        candidate.code = final_code
                    candidate.round_id = next_round
                    write_text(str(Path(output_dir) / f"candidate_round_{next_round}.py"), final_code)
                    _refresh_candidate_command(context, candidate)
                    semantic_repairs_used += 1
                    # Oracle synthesis already performs the oracle repair using
                    # runtime observations. Do not immediately rewrite it a
                    # second time with the stale pre-observation execution log.
                    brt_attempt += 1
                    continue
                else:
                    if semantic_repairs_used >= max(0, brt_budget):
                        final_code = candidate.code
                        write_text(str(Path(output_dir) / "final_test.py"), final_code)
                        break
                    semantic_repairs_used += 1
                mutation_plan = None
                if focus == "trigger" and enable_seed_mutation:
                    mutation_plan = build_mutation_plan(
                        context.instance_id,
                        env_rounds_used + brt_attempt + 1,
                        behavior, host, host_scaffold, protocol, llm_client,
                        output_dir,
                        execution.stdout + "\n" + execution.stderr,
                        decision.to_dict(),
                        analysis_prior_hint,
                        protocol_context_audit=protocol_context_audit,
                    )
                    mutation_plans.append(mutation_plan)
                candidate = repair_candidate(
                    context.instance_id,
                    behavior,
                    host,
                    candidate,
                    execution,
                    llm_client,
                    output_dir,
                    env_rounds_used + brt_attempt + 1,
                    focus,
                    context.retrieved_code,
                    json.dumps(observation.to_dict() if observation else {}, ensure_ascii=False),
                    decision.to_dict(),
                    context.buggy_repo_path,
                    protocol,
                    mutation_plan,
                    host_scaffold,
                )
                if mutation_plan is not None:
                    write_text(str(Path(output_dir) / f"mutation_round_{mutation_plan.round_id}_test.py"), candidate.code)
                _refresh_candidate_command(context, candidate)
                brt_attempt += 1
            if best_candidate is not None:
                candidate = best_candidate
                execution = best_execution
                decision = best_decision
                dual = best_dual
                observation = best_observation
                strict_result = best_strict_result
                final_code = candidate.code
                write_text(candidate.candidate_file_path, candidate.code)
                _refresh_candidate_command(context, candidate)
                checkpoints[best_index].selected = True
                checkpoints[best_index].save_json(
                    str(
                        Path(output_dir)
                        / "checkpoints"
                        / f"candidate_attempt_{checkpoints[best_index].round_id}.json"
                    )
                )
                safe_json_dump(
                    {
                        "selection_policy": (
                            "surrogate_f2p > verifier_accept > executable_buggy_fail "
                            "> buggy_pass > environment_failure; earliest wins ties"
                        ),
                        "selected_attempt": checkpoints[best_index].round_id,
                        "checkpoints": [item.to_dict() for item in checkpoints],
                    },
                    str(Path(output_dir) / "candidate_ranking.json"),
                )
        assert candidate is not None and execution is not None
        if dual is not None:
            pass
        elif validation_mode == "surrogate_patch":
            if execution.returncode == 0:
                dual = DualVersionResult(
                    context.instance_id,
                    validation_mode,
                    execution.to_dict(),
                    {},
                    "BUGGY_PASS",
                    "Surrogate patch validation skipped because the BRT passes on buggy source.",
                )
            elif decision is not None and decision.decision == "accept":
                dual = run_surrogate_patch_loop(
                    context.instance_id,
                    behavior,
                    candidate,
                    context.retrieved_code,
                    context.buggy_repo_path,
                    execution,
                    llm_client,
                    output_dir,
                    conda_env,
                    timeout,
                    no_conda,
                    max_patch_rounds,
                )
            else:
                dual = DualVersionResult(
                    context.instance_id,
                    validation_mode,
                    execution.to_dict(),
                    {},
                    "SKIPPED_UNALIGNED_BUGGY_FAIL",
                    "Surrogate patch validation requires an issue-aligned buggy failure.",
                )
            dual.save_json(str(Path(output_dir) / "dual_version_result.json"))
        else:
            dual = DualVersionResult(
                context.instance_id,
                "buggy_only",
                execution.to_dict(),
                {},
                "SKIPPED",
                "Only the buggy repository was executed; no patched source was loaded.",
            )
            dual.save_json(str(Path(output_dir) / "dual_version_result.json"))
        write_text(str(Path(output_dir) / "final_test.py"), final_code or candidate.code)
        if dual.status in {"F2P_SUCCESS", "SURROGATE_F2P_SUCCESS"}:
            status = dual.status
        elif decision is not None and decision.decision == "accept":
            status = "ISSUE_ALIGNED_FAIL"
        elif execution.status in {"SETUP_ERROR", "SYNTAX_ERROR", "COLLECT_ERROR", "TIMEOUT"}:
            status = execution.status
        elif execution.returncode != 0:
            # Executor keyword matching is only a triage hint. A rejected
            # verifier decision must never become an accepted issue failure.
            status = "UNRELATED_FAIL"
        else:
            status = execution.status
        strict_level = (
            "llm"
            if strict_result is not None and enable_strict_semantic_verifier
            else ("skipped" if not enable_strict_semantic_verifier else "local")
        )
        surrogate_patch_used = bool(
            dual
            and dual.mode == "surrogate_patch"
            and dual.status
            not in {"SKIPPED", "BUGGY_PASS", "SKIPPED_UNALIGNED_BUGGY_FAIL"}
        )
        selection_reason = (
            checkpoints[best_index].reason
            if "checkpoints" in locals() and best_index >= 0
            else (decision.reason if decision else status)
        )
        result = FinalResult(
            instance_id=context.instance_id,
            status=status,
            final_test_path=str(Path(output_dir) / "final_test.py"),
            rounds_used=(candidate.round_id + 1),
            buggy_execution=execution.to_dict(),
            dual_version_result=dual.to_dict(),
            behavior_target=behavior.to_dict(),
            host_context=host.to_dict(),
            observation_report=observation.to_dict() if observation else {},
            notes=decision.reason if decision else "",
            protocol_recovery_enabled=enable_protocol_recovery,
            seed_mutation_enabled=enable_seed_mutation,
            observation_oracle_enabled=enable_observation_oracle,
            strict_verifier_enabled=enable_strict_semantic_verifier,
            selected_seed_file=related_test.file if related_test else "",
            selected_seed_name=related_test.name if related_test else "",
            seed_fallback_used=seed_fallback_used,
            mutation_ops=list(dict.fromkeys(op for plan in mutation_plans for op in plan.mutation_ops)),
            oracle_type=oracle_type,
            strict_verifier_decision=strict_result.decision if strict_result else "",
            strict_failure_class=strict_result.failure_class if strict_result else "",
            oracle_rebound=oracle_rebound,
            final_reason=decision.reason if decision else "",
            **_stable_result_fields(
                llm_client,
                mutation_plans,
                mode=mode,
                deterministic=deterministic,
                selected_seed_signature=selected_seed_signature,
                seed_reused=seed_reused,
                seed_change_reason=seed_change_reason,
                analysis_prior_used=analysis_prior_used,
                regression_guard_triggered=bool(decision and decision.decision == "accept"),
                regression_guard_reason=(
                    "surrogate patch is ranking-only; accepted candidate was not rewritten after surrogate failure"
                    if decision and decision.decision == "accept"
                    else ""
                ),
                surrogate_patch_used=surrogate_patch_used,
                observation_oracle_used=oracle_rebound,
                strict_verifier_level=strict_level,
                final_selection_reason=selection_reason,
                seed_selection_mode=seed_selection_mode,
                seed_candidates_count=seed_candidates_count,
                selected_seed_score=selected_seed_score,
                matched_apis=matched_apis,
                seed_score_breakdown=seed_score_breakdown,
                seed_selection_fallback_reason=seed_selection_fallback_reason,
                primary_seed_test=primary_seed_test,
                host_scaffold=host_scaffold,
                candidate=candidate,
                final_code=final_code or candidate.code,
            ),
        )
        result.save_json(str(Path(output_dir) / "summary.json"))
        return result
    except Exception as exc:  # noqa: BLE001
        safe_json_dump({
            "instance_id": context.instance_id,
            "status": "ERROR",
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "protocol_recovery_enabled": enable_protocol_recovery,
            "seed_mutation_enabled": enable_seed_mutation,
            "observation_oracle_enabled": enable_observation_oracle,
            "strict_verifier_enabled": enable_strict_semantic_verifier,
            "selected_seed_file": "",
            "selected_seed_name": "",
            "seed_fallback_used": False,
            "mutation_ops": [],
            "oracle_type": "",
            "strict_verifier_decision": "",
            "strict_failure_class": "",
            "oracle_rebound": False,
            "final_reason": str(exc),
            **_stable_result_fields(
                llm_client,
                mode=mode,
                deterministic=deterministic,
                analysis_prior_used=analysis_prior_used,
                final_selection_reason="pipeline exception",
            ),
        }, str(Path(output_dir) / "summary.json"))
        return FinalResult(
            instance_id=context.instance_id,
            status="ERROR",
            notes=str(exc),
            **_stable_result_fields(
                llm_client,
                mode=mode,
                deterministic=deterministic,
                analysis_prior_used=analysis_prior_used,
                final_selection_reason="pipeline exception",
            ),
        )

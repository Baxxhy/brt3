#!/usr/bin/env python3
"""Analyze V0->V1 BRT result regressions without modifying preserved results."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT = Path("/root/Baxxhy/BugReproduce/brt3")
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from mutation.brt_mutation_rules import RULE_NAMES, infer_issue_pattern


DEFAULT_V0 = PROJECT / "results/preserved/f2p_40_20260621_224723"
DEFAULT_V1 = PROJECT / "results/preserved/f2p_42_20260623_091037"
DEFAULT_V2 = PROJECT / "results/runs/run_20260624_refactor_deepseek7"


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _find_json(root: Path, name: str) -> Path | None:
    direct = root / "evaluation" / name
    if direct.is_file():
        return direct
    direct = root / name
    if direct.is_file():
        return direct
    matches = sorted(root.rglob(name), key=lambda p: (len(p.parts), str(p)))
    return matches[0] if matches else None


def _load_merged(root: Path) -> dict[str, dict[str, Any]]:
    path = _find_json(root, "merged_results.json")
    if not path:
        return {}
    data = _read_json(path)
    if isinstance(data, dict):
        return {str(k): v for k, v in data.items() if isinstance(v, dict)}
    if isinstance(data, list):
        out = {}
        for item in data:
            if isinstance(item, dict) and item.get("instance_id"):
                out[str(item["instance_id"])] = item
        return out
    return {}


def _index_summaries(root: Path) -> dict[str, dict[str, Any]]:
    summaries: dict[str, dict[str, Any]] = {}
    for path in root.rglob("summary.json"):
        if "worktree" in path.parts:
            continue
        data = _read_json(path)
        if not isinstance(data, dict):
            continue
        iid = str(data.get("instance_id") or path.parent.name)
        if iid and iid not in summaries:
            summaries[iid] = data
    return summaries


def _status(record: dict[str, Any] | None) -> str:
    if not record:
        return "MISSING"
    status = str(record.get("status") or record.get("formal_status") or "UNKNOWN")
    if not status and record.get("success") is True:
        status = "F2P_SUCCESS"
    return status or "UNKNOWN"


def _is_success(status: str) -> bool:
    return status == "F2P_SUCCESS" or status.lower() in {"success", "fail_to_pass_success"}


def _repo_from_iid(iid: str) -> str:
    if "__" in iid:
        owner, rest = iid.split("__", 1)
        project = rest.split("-", 1)[0]
        return f"{owner}/{project}"
    return iid.split("-", 1)[0]


def _summary_status(summary: dict[str, Any] | None) -> str:
    return str((summary or {}).get("status") or "UNKNOWN")


def _seed(summary: dict[str, Any] | None) -> tuple[str, str]:
    data = summary or {}
    return str(data.get("selected_seed_file") or ""), str(data.get("selected_seed_name") or "")


def _mutation_ops(summary: dict[str, Any] | None) -> list[str]:
    data = summary or {}
    raw = data.get("mutation_rules_used") or data.get("mutation_ops") or []
    if isinstance(raw, list):
        return [str(item) for item in raw if str(item)]
    return []


def _issue_pattern(summary: dict[str, Any] | None) -> str:
    data = summary or {}
    pattern = str(data.get("issue_pattern") or "")
    if pattern and pattern != "unknown":
        return pattern
    behavior = data.get("behavior_target") if isinstance(data.get("behavior_target"), dict) else {}
    text = " ".join(
        str(behavior.get(key) or "")
        for key in ["issue_summary", "trigger_condition", "error_symptom", "expected_behavior"]
    )
    return infer_issue_pattern(text)


def _log_excerpt(record: dict[str, Any] | None, side: str) -> str:
    if not record:
        return ""
    source = record.get(f"{side}_run") or record.get(side) or {}
    if isinstance(source, dict):
        text = str(source.get("error_excerpt") or source.get("stdout") or "") + "\n" + str(source.get("stderr") or "")
    else:
        text = str(source)
    lines = [line for line in text.splitlines() if line.strip()]
    return "\n".join(lines[-40:])[-4000:]


def _coarse_failure(status: str) -> str:
    if status in {"BUGGY_SETUP_ERROR", "SETUP_ERROR", "FIXED_SETUP_ERROR", "COLLECT_ERROR", "SYNTAX_ERROR", "TIMEOUT", "MISSING_GENERATED_TEST"}:
        return "SETUP/EVAL"
    if status in {"PATCH_APPLY_ERROR", "FLAKY_EVAL"}:
        return "SETUP/EVAL"
    if status == "BUGGY_PASS":
        return "BUGGY_PASS"
    if status == "FIXED_FAIL":
        return "FIXED_FAIL"
    return status or "UNKNOWN"


def _root_cause(v1_status: str, seed_changed: bool, v1_summary: dict[str, Any] | None) -> tuple[str, str, list[str]]:
    evidence: list[str] = []
    if seed_changed:
        evidence.append("seed changed between V0 and V1")
    strict_failure = str((v1_summary or {}).get("strict_failure_class") or "")
    if v1_status == "BUGGY_PASS":
        return "TRIGGER_REGRESSION", "seed_mutation", evidence + ["V1 passes on buggy, so trigger is weaker or target path is missed"]
    if v1_status == "FIXED_FAIL":
        broken = "observation_oracle"
        if strict_failure in {"side_path", "target_not_hit"}:
            evidence.append(f"strict verifier failure_class={strict_failure}")
            broken = "seed_mutation"
        return "ORACLE_REGRESSION", broken, evidence + ["V1 fails on fixed, so oracle may be too strong or side-path related"]
    if v1_status in {"BUGGY_SETUP_ERROR", "SETUP_ERROR", "COLLECT_ERROR", "SYNTAX_ERROR", "MISSING_GENERATED_TEST"}:
        return "SETUP_REGRESSION", "host_context", evidence + [f"V1 mechanical status={v1_status}"]
    if v1_status in {"PATCH_APPLY_ERROR", "TIMEOUT", "FLAKY_EVAL"}:
        return "EVAL_INFRA_REGRESSION", "formal_eval", evidence + [f"V1 evaluation status={v1_status}"]
    if str((v1_summary or {}).get("surrogate_patch_used")).lower() == "true":
        return "CHECKPOINT_REGRESSION", "surrogate_patch", evidence + ["surrogate/checkpoint path was involved"]
    return "UNKNOWN", "unknown", evidence + [f"unclassified V1 status={v1_status}"]


def analyze(v0: Path, v1: Path, v2: Path, output_dir: Path) -> dict[str, Any]:
    v0_results = _load_merged(v0)
    v1_results = _load_merged(v1)
    v2_results = _load_merged(v2)
    v0_summaries = _index_summaries(v0)
    v1_summaries = _index_summaries(v1)
    all_ids = sorted(set(v0_results) | set(v1_results) | set(v2_results) | set(v0_summaries) | set(v1_summaries))
    v0_success = {iid for iid in all_ids if _is_success(_status(v0_results.get(iid)))}
    v1_success = {iid for iid in all_ids if _is_success(_status(v1_results.get(iid)))}

    regressions: list[dict[str, Any]] = []
    for iid in sorted(v0_success - v1_success):
        v0_status = _status(v0_results.get(iid))
        v1_status = _status(v1_results.get(iid))
        v0_seed_file, v0_seed_name = _seed(v0_summaries.get(iid))
        v1_seed_file, v1_seed_name = _seed(v1_summaries.get(iid))
        seed_changed = (v0_seed_file, v0_seed_name) != (v1_seed_file, v1_seed_name)
        root_cause, broken_module, evidence = _root_cause(v1_status, seed_changed, v1_summaries.get(iid))
        regressions.append(
            {
                "instance_id": iid,
                "v0_formal_status": v0_status,
                "v1_formal_status": v1_status,
                "v0_generation_status": _summary_status(v0_summaries.get(iid)),
                "v1_generation_status": _summary_status(v1_summaries.get(iid)),
                "v0_seed_file": v0_seed_file,
                "v0_seed_name": v0_seed_name,
                "v1_seed_file": v1_seed_file,
                "v1_seed_name": v1_seed_name,
                "seed_changed": seed_changed,
                "v1_mutation_ops": _mutation_ops(v1_summaries.get(iid)),
                "v1_oracle_rebound": bool((v1_summaries.get(iid) or {}).get("oracle_rebound")),
                "v1_strict_failure_class": str((v1_summaries.get(iid) or {}).get("strict_failure_class") or ""),
                "v1_strict_verifier_decision": str((v1_summaries.get(iid) or {}).get("strict_verifier_decision") or ""),
                "v1_buggy_log_excerpt": _log_excerpt(v1_results.get(iid), "buggy"),
                "v1_fixed_log_excerpt": _log_excerpt(v1_results.get(iid), "fixed"),
                "v1_failure_transition": f"{v0_status} -> {v1_status}",
                "root_cause": root_cause,
                "broken_module": broken_module,
                "evidence": evidence,
            }
        )

    fail_fail: list[dict[str, Any]] = []
    transition_counts: Counter[str] = Counter()
    still_ids = sorted(set(all_ids) - v0_success - v1_success)
    for iid in still_ids:
        v0_status = _status(v0_results.get(iid))
        v1_status = _status(v1_results.get(iid))
        transition = f"{_coarse_failure(v0_status)} -> {_coarse_failure(v1_status)}"
        transition_counts[transition] += 1
        fail_fail.append(
            {
                "instance_id": iid,
                "v0_formal_status": v0_status,
                "v1_formal_status": v1_status,
                "transition": transition,
                "v1_generation_status": _summary_status(v1_summaries.get(iid)),
                "v1_strict_failure_class": str((v1_summaries.get(iid) or {}).get("strict_failure_class") or ""),
                "v1_mutation_ops": _mutation_ops(v1_summaries.get(iid)),
            }
        )

    effectiveness: dict[str, Any] = {name: {"count": 0, "f2p_success": 0, "fixed_fail": 0, "buggy_pass": 0, "setup_error": 0} for name in RULE_NAMES}
    by_repo: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
    by_pattern: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
    for iid in sorted(set(v1_results) | set(v1_summaries)):
        status = _status(v1_results.get(iid))
        outcome = "f2p_success" if _is_success(status) else (
            "fixed_fail" if status == "FIXED_FAIL" else (
                "buggy_pass" if status == "BUGGY_PASS" else (
                    "setup_error" if _coarse_failure(status) == "SETUP/EVAL" else "other"
                )
            )
        )
        ops = _mutation_ops(v1_summaries.get(iid)) or ["UNKNOWN"]
        repo = _repo_from_iid(iid)
        pattern = _issue_pattern(v1_summaries.get(iid))
        for op in ops:
            if op in effectiveness:
                effectiveness[op]["count"] += 1
                if outcome in effectiveness[op]:
                    effectiveness[op][outcome] += 1
            by_repo[repo][op][outcome] += 1
            by_pattern[pattern][op][outcome] += 1
    for item in effectiveness.values():
        count = item["count"] or 1
        item["success_rate"] = item["f2p_success"] / count
        item["fixed_fail_risk"] = item["fixed_fail"] / count
        item["buggy_pass_risk"] = item["buggy_pass"] / count
    mutation_summary = {
        "by_rule": effectiveness,
        "by_repo": {repo: {op: dict(counter) for op, counter in ops.items()} for repo, ops in by_repo.items()},
        "by_issue_pattern": {pat: {op: dict(counter) for op, counter in ops.items()} for pat, ops in by_pattern.items()},
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "v0_success_v1_fail.json", regressions)
    _write_json(output_dir / "v0_fail_v1_fail.json", {"transition_counts": dict(transition_counts), "records": fail_fail})
    _write_json(output_dir / "mutation_effectiveness_summary.json", mutation_summary)
    root_counts = Counter(item["root_cause"] for item in regressions)
    module_counts = Counter(item["broken_module"] for item in regressions)
    v1_fail_stats = {
        "failure_class_consistent_count": sum(1 for item in fail_fail if item["transition"].split(" -> ")[0] == item["transition"].split(" -> ")[1]),
        "failure_class_changed_count": sum(1 for item in fail_fail if item["transition"].split(" -> ")[0] != item["transition"].split(" -> ")[1]),
        "v1_unrelated_to_issue_aligned_count": sum(1 for item in fail_fail if item["v1_generation_status"] in {"ISSUE_ALIGNED_FAIL", "SURROGATE_F2P_SUCCESS"}),
        "v1_issue_aligned_but_not_f2p_count": sum(1 for item in fail_fail if item["v1_generation_status"] == "ISSUE_ALIGNED_FAIL"),
        "v1_setup_or_eval_failure_count": sum(1 for item in fail_fail if _coarse_failure(item["v1_formal_status"]) == "SETUP/EVAL"),
        "v1_buggy_pass_count": sum(1 for item in fail_fail if item["v1_formal_status"] == "BUGGY_PASS"),
        "v1_fixed_fail_count": sum(1 for item in fail_fail if item["v1_formal_status"] == "FIXED_FAIL"),
    }
    md = [
        "# V0/V1 Regression Root Cause Summary",
        "",
        f"- V0 successes: {len(v0_success)}",
        f"- V1 successes: {len(v1_success)}",
        f"- V0_SUCCESS -> V1_FAIL: {len(regressions)}",
        "",
        "## Root Cause Counts",
    ]
    md.extend(f"- {key}: {value}" for key, value in sorted(root_counts.items()))
    md.append("")
    md.append("## Broken Module Counts")
    md.extend(f"- {key}: {value}" for key, value in sorted(module_counts.items()))
    md.append("")
    md.append("## V0_FAIL -> V1_FAIL Counts")
    md.extend(f"- {key}: {value}" for key, value in sorted(transition_counts.items()))
    md.append("")
    md.append("## V0_FAIL -> V1_FAIL Extra Stats")
    md.extend(f"- {key}: {value}" for key, value in sorted(v1_fail_stats.items()))
    (output_dir / "regression_root_cause_summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    pattern_lines = ["# Issue Pattern Mutation Summary", ""]
    for pattern, ops in sorted(mutation_summary["by_issue_pattern"].items()):
        pattern_lines.append(f"## {pattern}")
        for op, counter in sorted(ops.items()):
            pattern_lines.append(f"- {op}: {counter}")
        pattern_lines.append("")
    (output_dir / "issue_pattern_summary.md").write_text("\n".join(pattern_lines), encoding="utf-8")
    _write_json(
        output_dir / "analysis_summary.json",
        {
            "v0_success_count": len(v0_success),
            "v1_success_count": len(v1_success),
            "v2_success_count": sum(1 for iid in set(v2_results) if _is_success(_status(v2_results.get(iid)))),
            "v0_success_v1_fail_count": len(regressions),
            "root_cause_counts": dict(root_counts),
            "broken_module_counts": dict(module_counts),
            "v0_fail_v1_fail_transition_counts": dict(transition_counts),
            "v0_fail_v1_fail_stats": v1_fail_stats,
        },
    )
    latest = output_dir.parent / "latest"
    try:
        if latest.exists() or latest.is_symlink():
            latest.unlink()
        os.symlink(output_dir.name, latest)
    except OSError:
        (output_dir.parent / "latest.txt").write_text(str(output_dir), encoding="utf-8")
    return {"root_cause_counts": dict(root_counts), "v0_fail_v1_fail_stats": v1_fail_stats, "output_dir": str(output_dir)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v0", default=str(DEFAULT_V0))
    parser.add_argument("--v1", default=str(DEFAULT_V1))
    parser.add_argument("--v2", default=str(DEFAULT_V2))
    parser.add_argument("--output-dir", default="")
    args = parser.parse_args()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir) if args.output_dir else PROJECT / "results/analysis" / f"v0_v1_regression_{ts}"
    result = analyze(Path(args.v0), Path(args.v1), Path(args.v2), output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

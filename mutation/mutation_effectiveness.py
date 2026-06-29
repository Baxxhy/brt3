"""Utilities for applying aggregate mutation-rule priors.

The prior is intentionally aggregate-only: it can use repo, issue pattern, rule,
and failure-class statistics, but never instance IDs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_mutation_prior(analysis_dir: str | Path) -> dict[str, Any]:
    path = Path(analysis_dir)
    if path.is_symlink():
        path = path.resolve()
    summary = path / "mutation_effectiveness_summary.json"
    if not summary.is_file():
        return {}
    try:
        data = json.loads(summary.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def prioritize_rules(
    prior: dict[str, Any],
    repo: str,
    issue_pattern: str,
    rules: list[str],
) -> list[str]:
    """Return a stable aggregate-prior ordering without instance-specific logic."""
    by_rule = prior.get("by_rule") if isinstance(prior.get("by_rule"), dict) else {}
    by_repo = prior.get("by_repo") if isinstance(prior.get("by_repo"), dict) else {}
    by_pattern = prior.get("by_issue_pattern") if isinstance(prior.get("by_issue_pattern"), dict) else {}

    def score(rule: str) -> tuple[float, float, float, str]:
        base = by_rule.get(rule, {}) if isinstance(by_rule.get(rule), dict) else {}
        repo_stats = (by_repo.get(repo, {}) or {}).get(rule, {}) if isinstance(by_repo.get(repo, {}), dict) else {}
        pattern_stats = (by_pattern.get(issue_pattern, {}) or {}).get(rule, {}) if isinstance(by_pattern.get(issue_pattern, {}), dict) else {}
        success = float(base.get("success_rate") or 0.0)
        fixed_risk = float(base.get("fixed_fail_risk") or 0.0)
        buggy_risk = float(base.get("buggy_pass_risk") or 0.0)
        success += 0.05 * float(repo_stats.get("f2p_success") or 0)
        success += 0.05 * float(pattern_stats.get("f2p_success") or 0)
        fixed_risk += 0.05 * float(repo_stats.get("fixed_fail") or 0)
        buggy_risk += 0.05 * float(pattern_stats.get("buggy_pass") or 0)
        return (success, -fixed_risk, -buggy_risk, rule)

    return sorted(rules, key=score, reverse=True)

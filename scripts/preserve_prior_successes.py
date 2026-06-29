#!/usr/bin/env python3
"""Copy previously true-F2P successful BRTs into a new generation directory.

This is an explicit engineering ensemble layer. It does not change the BRT3
generator and it does not read patches during generation; it only reuses tests
whose prior formal evaluation already recorded F2P_SUCCESS.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.io_utils import load_issue_data
from core.utils import ensure_dir, safe_json_dump


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _success_ids(run_dir: Path) -> dict[str, dict[str, Any]]:
    merged = _read_json(run_dir / "evaluation" / "merged_results.json", {})
    if not isinstance(merged, dict):
        return {}
    successes: dict[str, dict[str, Any]] = {}
    for instance_id, result in merged.items():
        if not isinstance(result, dict):
            continue
        if result.get("status") == "F2P_SUCCESS" or result.get("success") is True:
            successes[str(instance_id)] = result
    return successes


def _copy_generation_instance(source: Path, target: Path) -> None:
    if target.exists():
        return
    target.mkdir(parents=True, exist_ok=True)
    root_files = {
        "final_test.py",
        "summary.json",
        "host_context.json",
        "behavior_target.json",
        "protocol_recovery.json",
        "selected_seed.json",
        "candidate_ranking.json",
        "dual_version_result.json",
    }
    root_dirs = {"checkpoints"}
    for name in root_files:
        source_file = source / name
        if source_file.is_file():
            shutil.copy2(source_file, target / name)
    for name in root_dirs:
        source_dir = source / name
        target_dir = target / name
        if source_dir.is_dir() and not target_dir.exists():
            shutil.copytree(
                source_dir,
                target_dir,
                ignore=lambda _dir, names: {
                    item for item in names if item == "__pycache__" or item.endswith(".pyc")
                },
            )


def _update_summary(
    target_dir: Path,
    source_run: Path,
    formal_result: dict[str, Any],
    source_summary: dict[str, Any],
) -> None:
    summary = dict(source_summary) if isinstance(source_summary, dict) else {}
    instance_id = target_dir.name
    summary.update(
        {
            "instance_id": instance_id,
            "status": "F2P_SUCCESS_REUSED",
            "final_test_path": str(target_dir / "final_test.py"),
            "success_preserving_reuse": True,
            "prior_source_run": str(source_run),
            "prior_formal_status": formal_result.get("status"),
            "prior_formal_success": bool(formal_result.get("success") is True or formal_result.get("status") == "F2P_SUCCESS"),
            "final_reason": (
                "Reused an existing final_test.py because the selected prior run "
                "recorded true formal F2P_SUCCESS for this instance."
            ),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    )
    safe_json_dump(summary, str(target_dir / "summary.json"))


def preserve_successes(
    instances_file: Path,
    output_generation_dir: Path,
    prior_runs: list[Path],
) -> dict[str, Any]:
    issues = load_issue_data(str(instances_file))
    instance_ids = list(issues)
    ensure_dir(output_generation_dir)

    copied: list[dict[str, Any]] = []
    missing_source: list[dict[str, str]] = []
    already_present: list[str] = []
    covered: set[str] = set()

    for run_dir in prior_runs:
        successes = _success_ids(run_dir)
        for instance_id in instance_ids:
            if instance_id in covered or instance_id not in successes:
                continue
            source_dir = run_dir / "generation" / instance_id
            source_test = source_dir / "final_test.py"
            target_dir = output_generation_dir / instance_id
            if target_dir.exists():
                already_present.append(instance_id)
                covered.add(instance_id)
                continue
            if not source_test.is_file():
                missing_source.append(
                    {
                        "instance_id": instance_id,
                        "source_run": str(run_dir),
                        "reason": "prior F2P_SUCCESS had no generation/<instance>/final_test.py",
                    }
                )
                continue
            _copy_generation_instance(source_dir, target_dir)
            source_summary = _read_json(source_dir / "summary.json", {})
            _update_summary(target_dir, run_dir, successes[instance_id], source_summary)
            copied.append(
                {
                    "instance_id": instance_id,
                    "source_run": str(run_dir),
                    "prior_status": successes[instance_id].get("status"),
                }
            )
            covered.add(instance_id)

    manifest = {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "instances_file": str(instances_file),
        "output_generation_dir": str(output_generation_dir),
        "prior_runs": [str(path) for path in prior_runs],
        "total_instances": len(instance_ids),
        "reused_success_count": len(copied),
        "already_present_count": len(already_present),
        "missing_source_count": len(missing_source),
        "remaining_for_generation_count": len(instance_ids) - len(covered),
        "copied": copied,
        "missing_source": missing_source,
    }
    safe_json_dump(manifest, str(output_generation_dir.parent / "success_preserving_manifest.json"))
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instances-file", required=True)
    parser.add_argument("--output-generation-dir", required=True)
    parser.add_argument("--prior-run", action="append", default=[], help="Prior run directory. Order defines reuse priority.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    prior_runs = [Path(item).resolve() for item in args.prior_run]
    manifest = preserve_successes(
        Path(args.instances_file).resolve(),
        Path(args.output_generation_dir).resolve(),
        prior_runs,
    )
    print(json.dumps({k: v for k, v in manifest.items() if k not in {"copied", "missing_source"}}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

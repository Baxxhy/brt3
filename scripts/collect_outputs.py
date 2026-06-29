#!/usr/bin/env python3
"""Collect per-instance final BRT outputs into one JSON file.

This is a thin compatibility summary. It does not replace the richer
`scripts/export_run_outputs.py` exports and refuses to overwrite an existing
output file unless `--force` is passed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return default


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _rel(path: Path | None, base: Path) -> str | None:
    if path is None:
        return None
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except (OSError, ValueError):
        return str(path)


def _load_instance_ids(run_dir: Path) -> list[str]:
    resolved = run_dir / "resolved_instances.json"
    data = _read_json(resolved, [])
    if isinstance(data, list):
        ids = [str(row.get("instance_id")) for row in data if isinstance(row, dict) and row.get("instance_id")]
        if ids:
            return ids
    generation_dir = run_dir / "generation"
    if not generation_dir.is_dir():
        return []
    return sorted(path.name for path in generation_dir.iterdir() if path.is_dir())


def _selected_prompt(instance_dir: Path) -> tuple[str | None, str | None]:
    ranking = _read_json(instance_dir / "candidate_ranking.json", {})
    selected = None
    if isinstance(ranking, dict):
        selected = ranking.get("selected_attempt")
        if not isinstance(selected, int):
            for item in ranking.get("checkpoints") or []:
                if isinstance(item, dict) and item.get("selected") and isinstance(item.get("round_id"), int):
                    selected = item["round_id"]
                    break
    candidates = []
    if isinstance(selected, int):
        candidates.append(instance_dir / "prompts" / f"generation_round_{selected}.txt")
        candidates.append(instance_dir / "prompts" / f"repair_prompt_round_{selected}.txt")
    candidates.extend(sorted((instance_dir / "prompts").glob("generation_round_*.txt")))
    candidates.append(instance_dir / "prompt.txt")
    for path in candidates:
        if path.is_file():
            return _read_text(path), str(path)
    return None, None


def collect(run_dir: Path) -> list[dict[str, Any]]:
    generation_dir = run_dir / "generation"
    evaluation = _read_json(run_dir / "evaluation" / "merged_results.json", {})
    if not isinstance(evaluation, dict):
        evaluation = {}
    records: list[dict[str, Any]] = []
    for instance_id in _load_instance_ids(run_dir):
        instance_dir = generation_dir / instance_id
        summary = _read_json(instance_dir / "summary.json", {})
        if not isinstance(summary, dict):
            summary = {}
        final_test_path = instance_dir / "final_test.py"
        final_prompt, final_prompt_path = _selected_prompt(instance_dir)
        eval_record = evaluation.get(instance_id, {})
        if not isinstance(eval_record, dict):
            eval_record = {}
        execution_log = instance_dir / "logs" / "execution_round_0.log"
        records.append(
            {
                "instance_id": instance_id,
                "generated_test": _read_text(final_test_path),
                "final_prompt": final_prompt,
                "final_status": eval_record.get("status") or summary.get("status"),
                "test_path": _rel(final_test_path, run_dir) if final_test_path.is_file() else None,
                "logs": {
                    "generation_summary": _rel(instance_dir / "summary.json", run_dir)
                    if (instance_dir / "summary.json").is_file()
                    else None,
                    "execution_log": _rel(execution_log, run_dir) if execution_log.is_file() else None,
                    "evaluation_record": "evaluation/merged_results.json"
                    if instance_id in evaluation
                    else None,
                },
                "metadata": {
                    "generation_status": summary.get("status"),
                    "formal_status": eval_record.get("status"),
                    "prompt_path": _rel(Path(final_prompt_path), run_dir) if final_prompt_path else None,
                    "selected_seed_file": summary.get("selected_seed_file"),
                    "selected_seed_name": summary.get("selected_seed_name"),
                    "strict_verifier_decision": summary.get("strict_verifier_decision"),
                },
            }
        )
    return records


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Run directory, e.g. results/runs/run_...")
    parser.add_argument("--output", required=True, help="Output JSON path.")
    parser.add_argument("--force", action="store_true", help="Allow overwriting the output file.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    run_dir = Path(args.input).resolve()
    output = Path(args.output).resolve()
    if output.exists() and not args.force:
        raise SystemExit(f"Refusing to overwrite existing output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    records = collect(run_dir)
    output.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "records": len(records)}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


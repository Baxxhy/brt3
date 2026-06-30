# BRT3 Run Guide

## Entry Points

Run commands from the project directory:

```bash
cd /root/Baxxhy/BugReproduce/brt3
```

Recommended entry points:

```bash
python -m cli.run_issue_rewrite --help
python -m cli.run --help
python -m evaluation.direct_eval --help
```

Compatibility wrappers remain for older habits:

```bash
python run_issue_rewrite.py --help
python run.py --help
python direct_eval.py --help
```

Those root files only forward to the real modules.

## Issue Rewrite

```bash
python -m cli.run_issue_rewrite \
  --instances_path /root/Baxxhy/BugReproduce/brt2/data/issues/swt276_issues.json \
  --code_retrieval_path /root/Baxxhy/BugReproduce/iCoRe/retrieval_results/code/code_retrieval_results_gpt.json \
  --test_retrieval_path /root/Baxxhy/BugReproduce/iCoRe/retrieval_results/test/icore/gpt/related_tests.json \
  --output_dir results/runs/run_issue_rewrite_smoke \
  --model deepseek-v3 \
  --limit 1 \
  --max_workers 1
```

This writes one `behavior_target.json` per instance.

Precompute issue rewrites for all 276 instances with nine workers:

```bash
bash scripts/run_issue_rewrite_276.sh --max-workers 9 --resume
```

Results are written to `results/issue_rewrite/<instance_id>/`. Each directory
contains `behavior_target.json`, the prompt, the raw response, and metadata.
After all 276 instances succeed, they are combined into:

```text
results/issue_rewrite/issue_rewrite.json
```

## BRT Generation

```bash
python -m cli.run \
  --instances_path /root/Baxxhy/BugReproduce/brt2/data/issues/swt276_issues.json \
  --code_retrieval_path /root/Baxxhy/BugReproduce/iCoRe/retrieval_results/code/code_retrieval_results_gpt.json \
  --test_retrieval_path /root/Baxxhy/BugReproduce/iCoRe/retrieval_results/test/icore/gpt/related_tests.json \
  --repo_root_base /root/Baxxhy/BugReproduce/swe_repos \
  --output_dir results/runs/run_generation_smoke/generation \
  --issue_rewrite_path /root/Baxxhy/BugReproduce/brt3/results/issue_rewrite/issue_rewrite.json \
  --model deepseek-v3 \
  --limit 1 \
  --max_workers 1 \
  --num_candidates 1
```

Generation does not read the true patch. It writes each instance under
`generation/<instance_id>/`, including `final_test.py`, prompt/response files,
execution logs, and `summary.json`.

When `--issue_rewrite_path` is provided, generation loads the aggregate JSON
once, requires every selected instance to be present, and does not call the
issue rewrite model. Omit the option to retain the original inline rewrite
behavior. `--issue_rewrite_dir` remains available only for compatibility with
older per-instance caches.

## Smoke Run

Preferred smoke command:

```bash
bash scripts/run_latest_full_pipeline.sh \
  --generation-only \
  --smoke \
  --smoke-n 1 \
  --max-workers 1 \
  --timeout 600
```

This verifies input parsing, issue rewrite, BRT generation, buggy execution, and
JSON output without launching a full 276-instance evaluation.

## Full Run

```bash
bash scripts/run_latest_full_pipeline.sh \
  --instances-file /root/Baxxhy/BugReproduce/brt2/data/issues/swt276_issues.json \
  --issue-rewrite-path /root/Baxxhy/BugReproduce/brt3/results/issue_rewrite/issue_rewrite.json \
  --model deepseek-v3 \
  --max-workers 6 \
  --timeout 1800
```

The wrapper runs generation, formal evaluation, export, and final self-check in
one organized run directory.

## Formal Evaluation

Evaluate an existing generation directory:

```bash
python scripts/run_formal_eval_after_generation.py \
  --outputs_dir results/runs/run_YYYYMMDD_HHMMSS/generation \
  --evaluation_dir results/runs/run_YYYYMMDD_HHMMSS/evaluation \
  --summary_path results/runs/run_YYYYMMDD_HHMMSS/evaluation/formal_eval_summary.json \
  --log_path results/runs/run_YYYYMMDD_HHMMSS/logs/evaluation.log \
  --dataset_file results/runs/run_YYYYMMDD_HHMMSS/resolved_instances.json \
  --repo_root_base /root/Baxxhy/BugReproduce/swe_repos \
  --max_workers 6 \
  --timeout 1800 \
  --resume
```

The direct evaluator is also runnable directly:

```bash
python -m evaluation.direct_eval --help
```

## Key Parameters

| Parameter | Meaning |
|---|---|
| `--instances_path` / `--instances-file` | Issue dataset JSON/JSONL, or a TXT list of instance IDs in the wrapper. |
| `--code_retrieval_path` | Retrieved source context JSON. |
| `--test_retrieval_path` | Retrieved test context JSON. |
| `--repo_root_base` | Root containing checked-out SWE repositories. |
| `--output_dir` | Generation output directory. |
| `--model` | LLM model name, usually `deepseek-v3`. |
| `--max_workers` | Parallel workers. Use 1 for smoke, 6-7 for full runs. |
| `--timeout` | Per setup/test timeout in seconds. |
| `--issue_rewrite_path` / `--issue-rewrite-path` | Aggregate `issue_rewrite.json`; loaded once and skips inline issue rewrite. |
| `--issue_rewrite_dir` / `--issue-rewrite-dir` | Deprecated compatibility mode for per-instance caches. |
| `--resume` | Reuse completed instance summaries or formal worker results. |

## Output Layout

```text
results/runs/run_YYYYMMDD_HHMMSS/
  generation/<instance_id>/
    final_test.py
    summary.json
    prompts/
    responses/
    logs/
  evaluation/
    worker_*/results.json
    merged_results.json
    metrics.json
  exports/
    all_outputs.json
    all_outputs.jsonl
    all_tests_only.json
    final_summary.json
  logs/
  resolved_instances.json
  run_config.json
```

## Latest Result Summary

```bash
cat results/LATEST_EXPERIMENT_SUMMARY.md
```

## Unified Output JSON

Rich export:

```bash
python scripts/export_run_outputs.py --run-dir results/runs/run_YYYYMMDD_HHMMSS
```

Compatibility schema requested for downstream tools:

```bash
python -m scripts.collect_outputs \
  --input results/runs/run_YYYYMMDD_HHMMSS \
  --output results/runs/run_YYYYMMDD_HHMMSS/exports/collected_outputs.json
```

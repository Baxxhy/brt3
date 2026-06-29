# BRT3 Project Structure

## Directory Overview

```text
brt3/
  cli/          command-line entry points
  core/         config, schema, common utilities, input/output helpers
  llm/          API pool and OpenAI-compatible client
  prompts/      centralized prompt templates
  execution/    feedback loop, command execution, iCoRe env/runtime helpers
  context/      issue rewrite, host test context, protocol recovery
  generation/   BRT candidate generation and repair
  oracle/       observation probe and oracle rebinding
  patching/     surrogate patching and optional dual-version validation
  validation/   static guard, buggy verifier, strict semantic verifier
  evaluation/   formal true-patch direct evaluator
  mutation/     seed mutation planning
  scripts/      wrappers, monitors, exporters, collection utilities
  data/         preserved input data
  retrieval_results/ preserved retrieval artifacts
  logs/         compatibility log directory
  results/      generated/preserved experiment outputs
  docs/         refactor and maintenance notes
```

Root Python files are compatibility wrappers only:

| File | Real entry |
|---|---|
| `run.py` | `cli.run` |
| `run_issue_rewrite.py` | `cli.run_issue_rewrite` |
| `direct_eval.py` | `evaluation.direct_eval` |

## Key Code Files

| Path | Responsibility |
|---|---|
| `cli/run.py` | Full BRT generation CLI and worker scheduling. |
| `cli/run_issue_rewrite.py` | Standalone issue rewrite CLI. |
| `core/config.py` | Defaults, LLM config, worker/timeout/token settings. |
| `core/schema.py` | Shared dataclasses and JSON serialization. |
| `core/io_utils.py` | Issue/retrieval loading and instance context assembly. |
| `core/utils.py` | JSON/text helpers, code block cleanup, path utilities. |
| `llm/api_pool.py` | Local API account pool, without writing keys to logs. |
| `llm/llm_client.py` | OpenAI-compatible DeepSeek client with retry and rotation. |
| `execution/feedback.py` | Main per-instance generation/feedback pipeline. |
| `execution/executor.py` | Command execution and result classification. |
| `execution/icore_runtime.py` | Conda env setup and project-specific test commands. |
| `context/issue_rewriter.py` | Issue to `BehaviorTarget`. |
| `context/host_context.py` | Related-test ranking and seed host context. |
| `context/protocol_recovery.py` | Imports/fixtures/class/protocol recovery from one seed. |
| `generation/generator.py` | Candidate generation and repair. |
| `oracle/oracle.py` | Probe and assertion synthesis. |
| `oracle/observation_oracle.py` | Observation-driven oracle rebinding. |
| `patching/patch_utils.py` | Surrogate source patch generation and validation. |
| `patching/dual_version.py` | Optional explicit dual-version validation helper. |
| `validation/semantic_guard.py` | Static semantic safety checks. |
| `validation/verifier.py` | Buggy-only verifier. |
| `validation/strict_semantic_verifier.py` | Strict semantic accept/repair decision. |
| `evaluation/direct_eval.py` | Formal true-patch F2P evaluation. |
| `scripts/export_run_outputs.py` | Rich run export. |
| `scripts/collect_outputs.py` | Lightweight unified JSON collector. |
| `scripts/monitor_run.py` | Generation/evaluation progress monitor. |

## Prompt Files

All prompt templates live in:

```text
prompts/templates.py
```

It contains issue rewrite, protocol recovery, seed mutation, generation, repair,
oracle, strict verifier, and surrogate patch prompts. Runtime prompt instances
are written under each run's `generation/<instance_id>/prompts/` directory.

## Results And Logs

New experiments should write under:

```text
results/runs/run_YYYYMMDD_HHMMSS/
```

Important files:

| Path | Meaning |
|---|---|
| `generation/<instance_id>/summary.json` | Generation status and selected test metadata. |
| `generation/<instance_id>/final_test.py` | Final generated BRT. |
| `evaluation/merged_results.json` | Formal per-instance F2P records. |
| `evaluation/metrics.json` | Formal aggregate metrics. |
| `exports/final_summary.json` | Exported aggregate summary. |
| `exports/all_outputs.json` | Rich per-instance export. |
| `exports/collected_outputs.json` | Optional lightweight compatibility export. |
| `logs/generation.log` | Generation stage log. |
| `logs/evaluation.log` | Formal evaluation log. |
| `logs/export.log` | Export log. |

Historical full results are preserved under `results/preserved/`.

## Legacy Scripts

`scripts/legacy/` is retained for traceability and may still mention old
`python -m brt3.*` commands. New work should use `cli.*` and `evaluation.*`.


# BRT3 Refactor Plan

Generated after these required checks:

```bash
find . -maxdepth 1 -type f -name "*.py" | sort
grep -R "import .*api_pool\|from .*api_pool\|import .*generator\|from .*generator\|import .*prompts\|from .*prompts" -n .
```

The raw `grep -R` also matches large historical JSON/result payloads under
`data/` and `results/`. For actionable import updates, code scanning excludes
`results/`, `data/`, `retrieval_results/`, `logs/`, and `__pycache__/`.

This checkout is not detected as a Git working tree from `brt3/`, so moves will
use filesystem `mv`, which is the safe equivalent here.

| Original file | New location | Category | Import files to update |
|---|---|---|---|
| `api_pool.py` | `llm/api_pool.py` | LLM API config | `llm/llm_client.py`, scripts |
| `llm_client.py` | `llm/llm_client.py` | LLM client | `cli/run.py`, `cli/run_issue_rewrite.py`, docs |
| `prompts.py` | `prompts/templates.py` | Prompt templates | `context/protocol_recovery.py`, `context/issue_rewriter.py`, `generation/generator.py`, `oracle/*.py`, `patching/patch_utils.py`, `validation/*.py`, `mutation/seed_mutator.py`, docs |
| `config.py` | `core/config.py` | Defaults and config | `cli/*.py`, `llm/*.py`, docs |
| `schema.py` | `core/schema.py` | Shared dataclasses | all feature packages using `BehaviorTarget`, `CandidateTest`, etc. |
| `utils.py` | `core/utils.py` | JSON/text helpers | `context/*`, `generation/*`, `oracle/*`, `patching/*`, `validation/*` |
| `io_utils.py` | `core/io_utils.py` | Input/output helpers | `cli/*.py`, `context/*`, `generation/*`, `evaluation/direct_eval.py`, scripts |
| `run.py` | `cli/run.py` plus root wrapper | CLI entry | `scripts/run_latest_full_pipeline.sh`, docs |
| `run_issue_rewrite.py` | `cli/run_issue_rewrite.py` plus root wrapper | CLI entry | docs |
| `direct_eval.py` | `evaluation/direct_eval.py` plus root wrapper | Formal true-patch eval | docs |
| `feedback.py` | `execution/feedback.py` | Generation execution loop | `cli/run.py`, docs |
| `executor.py` | `execution/executor.py` | Command execution | `execution/feedback.py`, `context/host_context.py`, `generation/*`, `oracle/*`, `patching/dual_version.py`, docs |
| `icore_env_constants.py` | `execution/icore_env_constants.py` | iCoRe env model | `execution/icore_env_utils.py`, `execution/icore_exec_spec.py`, docs |
| `icore_env_utils.py` | `execution/icore_env_utils.py` | iCoRe env utilities | `execution/icore_exec_spec.py`, docs |
| `icore_exec_spec.py` | `execution/icore_exec_spec.py` | Exec spec | `execution/icore_runtime.py`, `execution/feedback.py`, docs |
| `icore_runtime.py` | `execution/icore_runtime.py` | Runtime command generation | `execution/feedback.py`, `context/host_context.py`, `context/protocol_recovery.py`, `oracle/*`, docs |
| `host_context.py` | `context/host_context.py` | Host test context | `execution/feedback.py`, docs |
| `issue_rewriter.py` | `context/issue_rewriter.py` | Issue rewrite | `execution/feedback.py`, `cli/run_issue_rewrite.py`, docs |
| `generator.py` | `generation/generator.py` | BRT candidate generation | `execution/feedback.py`, docs |
| `oracle.py` | `oracle/oracle.py` | Observation and assertion oracle | `execution/feedback.py`, docs |
| `observation_oracle.py` | `oracle/observation_oracle.py` | Observation oracle rebinding | `execution/feedback.py`, docs |
| `patch_utils.py` | `patching/patch_utils.py` | Surrogate patching | `execution/feedback.py`, docs |
| `dual_version.py` | `patching/dual_version.py` | Optional dual-version validation | docs |
| `semantic_guard.py` | `validation/semantic_guard.py` | Static semantic guard | `execution/feedback.py`, docs |
| `verifier.py` | `validation/verifier.py` | Buggy-only verifier | `execution/feedback.py`, docs |
| `strict_semantic_verifier.py` | `validation/strict_semantic_verifier.py` | Strict semantic verifier | `execution/feedback.py`, docs |
| Root wrappers except `run.py`, `direct_eval.py`, `run_issue_rewrite.py` | removed | Compatibility cleanup | All code must import new package paths |

Root-level compatibility wrappers retained:

| Wrapper | Target |
|---|---|
| `run.py` | `cli.run.main` |
| `run_issue_rewrite.py` | `cli.run_issue_rewrite.main` |
| `direct_eval.py` | `evaluation.direct_eval.main` |

Recommended commands after refactor:

```bash
python -m cli.run --help
python -m cli.run_issue_rewrite --help
python -m evaluation.direct_eval --help
python -m scripts.collect_outputs --help
```

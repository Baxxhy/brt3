# Current Formal F2P vs 45% Baseline

## Result Selection

- Current result: `/root/Baxxhy/BugReproduce/brt3/results/runs/run_20260628_182802_method_trigger_only_oracle_repair_deep_t01_full/evaluation/formal_eval_summary.json`
- Current run is complete: `returncode=0`, `completed=276`, no missing instances.
- Historical 45% result: `/root/Baxxhy/BugReproduce/brt3/results/runs/run_20260624_refactor_deepseek7/evaluation/metrics.json`
- The historical result is 125/276 = 45.2899%. The comparison below uses the requested 45.0% baseline.

## Formal Comparison

| Metric | Current | Baseline | Gap |
| --- | ---: | ---: | ---: |
| Total instances | 276 | 276 | 0 |
| Formal F2P success | 113 | 124.2 expected at 45% | -11.2 |
| Formal F2P rate | 40.9420% | 45.0000% | -4.0580 pp |
| Relative rate gap | - | - | -9.0177% |

The current complete run is 4.0580 percentage points below the requested 45% baseline.

## Failure Breakdown

Formal evaluation:

| Status | Count |
| --- | ---: |
| `BUGGY_PASS` | 36 |
| `BUGGY_FAIL + FIXED_FAIL` (`FIXED_FAIL`) | 126 |
| `FLAKY_EVAL` | 1 |
| Formal mechanical setup failure | 0 |

Generation-stage final status from the same run:

| Status | Count |
| --- | ---: |
| `ISSUE_ALIGNED_FAIL` | 83 |
| `SURROGATE_F2P_SUCCESS` | 65 |
| `UNRELATED_FAIL` | 84 |
| `PASS` | 36 |
| `ENV_UNRESOLVED` | 8 |

Generation-stage final buggy execution status:

| Status | Count |
| --- | ---: |
| `SETUP_ERROR` | 5 |
| `COLLECT_ERROR` | 2 |
| `SYNTAX_ERROR` | 1 |
| `TIMEOUT` | 0 |

These categories belong to different stages and are intentionally not summed into one denominator. Formal F2P uses only the official formal evaluation result; mutation diagnostics use the generation-stage statuses.

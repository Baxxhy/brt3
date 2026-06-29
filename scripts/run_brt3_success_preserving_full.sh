#!/usr/bin/env bash
set -euo pipefail

ROOT=/root/Baxxhy/BugReproduce
BRT3="$ROOT/brt3"
DEFAULT_INSTANCES="$ROOT/brt2/data/issues/swt276_issues.json"
DEFAULT_CODE="$ROOT/iCoRe/retrieval_results/code/code_retrieval_results_gpt.json"
DEFAULT_TESTS="$ROOT/iCoRe/retrieval_results/test/icore/gpt/related_tests.json"
DEFAULT_REPOS="$ROOT/swe_repos"

instances_file="$DEFAULT_INSTANCES"
run_dir=""
run_id=""
resume=false
generation_only=false
evaluation_only=false
model="deepseek-v3"
max_workers=8
temperature=0.1
timeout=1800
mode_name="deep"
smoke=false
smoke_n=5

prior_runs=(
  "$BRT3/results/runs/run_20260624_refactor_deepseek7"
  "$BRT3/results/preserved/f2p_42_20260623_091037"
  "$BRT3/results/runs/run_20260627_003613_mutation_stable"
)

usage() {
  cat <<'EOF'
Usage: bash scripts/run_brt3_success_preserving_full.sh [options]

This explicit ensemble run first reuses final_test.py from prior formal
F2P_SUCCESS instances, then runs BRT3 generation only for the remaining
instances. It does not read true patches during generation.

Options:
  --instances-file PATH  Input issue JSON/JSONL, or TXT with one instance ID per line.
  --run-dir PATH         Explicit run directory.
  --run-id ID            Run ID under results/runs/.
  --resume               Resume an existing run.
  --generation-only      Run generation only.
  --evaluation-only      Run formal evaluation/export for an existing run.
  --model NAME           Model name (default: deepseek-v3).
  --max-workers N        Generation/evaluation workers (default: 8).
  --temperature FLOAT    Temperature (default: 0.1).
  --timeout SECONDS      Per command timeout (default: 1800).
  --smoke                Run a small smoke subset.
  --smoke-n N            Smoke subset size (default: 5).
  --help                 Show this help.
EOF
}

while (($#)); do
  case "$1" in
    --instances-file) instances_file=$2; shift 2 ;;
    --run-dir) run_dir=$2; shift 2 ;;
    --run-id) run_id=$2; shift 2 ;;
    --resume) resume=true; shift ;;
    --generation-only) generation_only=true; shift ;;
    --evaluation-only) evaluation_only=true; shift ;;
    --model) model=$2; shift 2 ;;
    --max-workers) max_workers=$2; shift 2 ;;
    --temperature) temperature=$2; shift 2 ;;
    --timeout) timeout=$2; shift 2 ;;
    --smoke) smoke=true; shift ;;
    --smoke-n) smoke_n=$2; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "$generation_only" == true && "$evaluation_only" == true ]]; then
  echo "--generation-only and --evaluation-only are mutually exclusive." >&2
  exit 2
fi

cd "$BRT3"
mkdir -p logs results/runs results/analysis

python - <<'PY'
from llm.api_pool import configured_api_metadata
entries = configured_api_metadata()
names = {entry["name"] for entry in entries}
if len(entries) != 9:
    raise SystemExit(f"expected 9 configured API accounts, got {len(entries)}")
if "fa_251812017" not in names:
    raise SystemExit("missing required API account name fa_251812017")
print("configured_api_accounts=9")
print("required_api_name_present=true")
PY

ts=$(date +%Y%m%d_%H%M%S)
if [[ -z "$run_dir" ]]; then
  if [[ -z "$run_id" ]]; then
    run_id="run_${ts}_success_preserving"
    [[ "$smoke" == true ]] && run_id="${run_id}_smoke"
  fi
  run_dir="$BRT3/results/runs/$run_id"
else
  run_dir=$(realpath -m "$run_dir")
  run_id=$(basename "$run_dir")
fi

if [[ -e "$run_dir" && "$resume" != true && "$evaluation_only" != true ]]; then
  echo "Run directory exists; use --resume or --evaluation-only: $run_dir" >&2
  exit 2
fi

mkdir -p "$run_dir"/{generation,evaluation,logs,exports,checkpoints,llm_cache}

resolved_instances="$run_dir/resolved_instances.json"
if [[ "$evaluation_only" != true || ! -f "$resolved_instances" ]]; then
  python - "$instances_file" "$DEFAULT_INSTANCES" "$resolved_instances" "$smoke" "$smoke_n" <<'PY'
import json, sys
from pathlib import Path
from core.io_utils import load_issue_data

source, canonical, output, smoke, smoke_n = sys.argv[1:]
source_path = Path(source)
if source_path.suffix.lower() == ".txt":
    wanted = [line.strip() for line in source_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = load_issue_data(canonical)
    selected = [rows[iid] for iid in wanted if iid in rows]
else:
    rows = load_issue_data(source)
    selected = list(rows.values())
if smoke == "true":
    selected = selected[: int(smoke_n)]
Path(output).write_text(json.dumps(selected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"resolved_instances={len(selected)}")
PY
fi

instance_count=$(python -c 'import json,sys; print(len(json.load(open(sys.argv[1], encoding="utf-8"))))' "$resolved_instances")

analysis_dir="$BRT3/results/analysis/v0_v1_regression_${ts}"
if [[ "$evaluation_only" != true ]]; then
  python "$BRT3/scripts/analyze_v0_v1_regression.py" --output-dir "$analysis_dir" 2>&1 | tee "$run_dir/logs/analysis.log"
else
  analysis_dir="$BRT3/results/analysis/latest"
fi

if [[ "$evaluation_only" != true ]]; then
  preserve_cmd=(
    python "$BRT3/scripts/preserve_prior_successes.py"
    --instances-file "$resolved_instances"
    --output-generation-dir "$run_dir/generation"
  )
  for prior in "${prior_runs[@]}"; do
    preserve_cmd+=(--prior-run "$prior")
  done
  printf '%q ' "${preserve_cmd[@]}" > "$run_dir/logs/preserve.command.txt"
  printf '\n' >> "$run_dir/logs/preserve.command.txt"
  "${preserve_cmd[@]}" 2>&1 | tee "$run_dir/logs/preserve.log"
fi

python - "$run_dir/run_config.json" <<PY
import json
from datetime import datetime
from pathlib import Path
path = Path(${run_dir@Q}) / "run_config.json"
old = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
data = {
    "run_id": ${run_id@Q},
    "created_at": old.get("created_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "project_root": ${BRT3@Q},
    "instances_file": ${instances_file@Q},
    "resolved_instances_file": ${resolved_instances@Q},
    "code_retrieval_path": ${DEFAULT_CODE@Q},
    "test_retrieval_path": ${DEFAULT_TESTS@Q},
    "repo_root_base": ${DEFAULT_REPOS@Q},
    "model": ${model@Q},
    "temperature": float(${temperature@Q}),
    "max_workers": int(${max_workers@Q}),
    "timeout": int(${timeout@Q}),
    "mode": ${mode_name@Q},
    "deterministic": True,
    "reuse_llm_cache": True,
    "llm_cache_dir": str(Path(${run_dir@Q}) / "llm_cache"),
    "analysis_prior_dir": ${analysis_dir@Q},
    "use_mutation_prior": True,
    "max_env_rounds": 3,
    "max_brt_rounds": 3,
    "max_patch_rounds": 3,
    "validation_mode": "surrogate_patch",
    "success_preserving_prior_runs": [${prior_runs[0]@Q}, ${prior_runs[1]@Q}, ${prior_runs[2]@Q}],
    "success_preserving_reuse": True,
    "instance_count": int(${instance_count@Q}),
}
path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

cat > "$run_dir/manifest.txt" <<EOF
BRT3 success-preserving mutation run
run_id: $run_id
started_at: $(date '+%Y-%m-%d %H:%M:%S')
instances: $instance_count
model: $model
temperature: $temperature
workers: $max_workers
mode: $mode_name
budgets: env=3 brt=3 surrogate=3
success_preserving_prior_runs:
  - ${prior_runs[0]}
  - ${prior_runs[1]}
  - ${prior_runs[2]}
analysis_prior_dir: $analysis_dir
api_accounts: 9
note: API keys are intentionally excluded from this manifest.
EOF

if [[ "$evaluation_only" != true ]]; then
  generation_cmd=(
    python -m cli.run
    --instances_path "$resolved_instances"
    --code_retrieval_path "$DEFAULT_CODE"
    --test_retrieval_path "$DEFAULT_TESTS"
    --repo_root_base "$DEFAULT_REPOS"
    --output_dir "$run_dir/generation"
    --model "$model"
    --temperature "$temperature"
    --max_workers "$max_workers"
    --num_candidates 1
    --timeout "$timeout"
    --max_env_rounds 3
    --max_brt_rounds 3
    --max_patch_rounds 3
    --validation_mode surrogate_patch
    --mode "$mode_name"
    --deterministic true
    --llm-cache-dir "$run_dir/llm_cache"
    --reuse-llm-cache true
    --refresh-llm-cache false
    --analysis-prior-dir "$analysis_dir"
    --use-mutation-prior true
    --enable_protocol_recovery true
    --enable_seed_mutation true
    --enable_observation_oracle true
    --enable_strict_semantic_verifier true
    --resume
  )
  [[ "$resume" == true ]] && generation_cmd+=(--resume)
  printf '%q ' "${generation_cmd[@]}" > "$run_dir/logs/generation.command.txt"
  printf '\n' >> "$run_dir/logs/generation.command.txt"
  "${generation_cmd[@]}" 2>&1 | tee -a "$run_dir/logs/generation.log"
  python - "$resolved_instances" "$run_dir/generation" <<'PY'
import json, sys
from pathlib import Path
rows = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
out = Path(sys.argv[2])
ids = [str(row["instance_id"]) for row in rows]
missing = [iid for iid in ids if not (out / iid / "summary.json").is_file()]
print(f"generation_summaries={len(ids)-len(missing)}/{len(ids)}")
if missing:
    print("missing generation summaries:", ", ".join(missing[:50]))
    raise SystemExit(1)
PY
  touch "$run_dir/generation.done"
fi

python - "$run_dir" <<'PY'
import json, sys
from pathlib import Path
run_dir = Path(sys.argv[1])
records = []
for instance_dir in sorted(p for p in (run_dir / "generation").iterdir() if p.is_dir()):
    summary_path = instance_dir / "summary.json"
    if not summary_path.is_file():
        continue
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    test_path = instance_dir / "final_test.py"
    records.append({
        "instance_id": summary.get("instance_id") or instance_dir.name,
        "selected_seed_file": summary.get("selected_seed_file"),
        "selected_seed_name": summary.get("selected_seed_name"),
        "success_preserving_reuse": summary.get("success_preserving_reuse", False),
        "prior_source_run": summary.get("prior_source_run"),
        "final_test": test_path.read_text(encoding="utf-8", errors="replace") if test_path.is_file() else None,
        "mutation_plan": summary.get("mutation_plan"),
        "mutation_rules_used": summary.get("mutation_rules_used"),
        "issue_pattern": summary.get("issue_pattern"),
        "status": summary.get("status"),
        "llm_cache_hit_count": summary.get("llm_cache_hit_count"),
        "llm_cache_miss_count": summary.get("llm_cache_miss_count"),
        "api_retry_count": summary.get("api_retry_count"),
        "api_error_types": summary.get("api_error_types"),
    })
(run_dir / "generation_all_outputs.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

if [[ "$generation_only" != true ]]; then
  eval_cmd=(
    python "$BRT3/scripts/run_formal_eval_after_generation.py"
    --outputs_dir "$run_dir/generation"
    --evaluation_dir "$run_dir/evaluation"
    --summary_path "$run_dir/evaluation/formal_eval_summary.json"
    --log_path "$run_dir/logs/evaluation.log"
    --dataset_file "$resolved_instances"
    --repo_root_base "$DEFAULT_REPOS"
    --max_workers "$max_workers"
    --timeout "$timeout"
    --eval_completed_only true
    --resume
  )
  printf '%q ' "${eval_cmd[@]}" > "$run_dir/logs/evaluation.command.txt"
  printf '\n' >> "$run_dir/logs/evaluation.command.txt"
  "${eval_cmd[@]}" 2>&1 | tee -a "$run_dir/logs/evaluation.wrapper.log"
  touch "$run_dir/evaluation.done"
fi

export_cmd=(python "$BRT3/scripts/export_run_outputs.py" --run-dir "$run_dir")
printf '%q ' "${export_cmd[@]}" > "$run_dir/logs/export.command.txt"
printf '\n' >> "$run_dir/logs/export.command.txt"
"${export_cmd[@]}" 2>&1 | tee "$run_dir/logs/export.log"
touch "$run_dir/export.done"

echo "run_dir=$run_dir"
echo "metrics=$run_dir/evaluation/metrics.json"
echo "exports=$run_dir/exports"

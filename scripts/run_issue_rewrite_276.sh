#!/usr/bin/env bash
set -euo pipefail

ROOT=/root/Baxxhy/BugReproduce
BRT3="$ROOT/brt3"
INSTANCES="$ROOT/brt2/data/issues/swt276_issues.json"
CODE_RETRIEVAL="$ROOT/iCoRe/retrieval_results/code/code_retrieval_results_gpt.json"
TEST_RETRIEVAL="$ROOT/iCoRe/retrieval_results/test/icore/gpt/related_tests.json"
OUTPUT_DIR="$BRT3/results/issue_rewrite"

max_workers=9
model="deepseek-v3"
resume=false
max_passes=4

usage() {
  cat <<'EOF'
Usage: bash scripts/run_issue_rewrite_276.sh [options]

Options:
  --max-workers N  Concurrent issue rewrite workers (default: 9).
  --model NAME     LLM model (default: deepseek-v3).
  --resume         Skip instances with an existing behavior_target.json.
  --max-passes N   Retry incomplete/error instances for up to N passes (default: 4).
  --help           Show this help.
EOF
}

while (($#)); do
  case "$1" in
    --max-workers) max_workers=$2; shift 2 ;;
    --model) model=$2; shift 2 ;;
    --resume) resume=true; shift ;;
    --max-passes) max_passes=$2; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ "$max_workers" =~ ^[1-9][0-9]*$ ]] || {
  echo "--max-workers must be a positive integer." >&2
  exit 2
}
[[ "$max_passes" =~ ^[1-9][0-9]*$ ]] || {
  echo "--max-passes must be a positive integer." >&2
  exit 2
}

mkdir -p "$OUTPUT_DIR"
cd "$BRT3"

base_cmd=(
  python -m cli.run_issue_rewrite
  --instances_path "$INSTANCES"
  --code_retrieval_path "$CODE_RETRIEVAL"
  --test_retrieval_path "$TEST_RETRIEVAL"
  --output_dir "$OUTPUT_DIR"
  --model "$model"
  --max_workers "$max_workers"
)

for ((pass=1; pass<=max_passes; pass++)); do
  cmd=("${base_cmd[@]}")
  if [[ "$resume" == true || "$pass" -gt 1 ]]; then
    cmd+=(--resume)
  fi
  {
    printf 'pass=%d ' "$pass"
    printf '%q ' "${cmd[@]}"
    printf '\n'
  } >> "$OUTPUT_DIR/command.txt"
  echo "issue rewrite pass $pass/$max_passes" | tee -a "$OUTPUT_DIR/run.log"
  "${cmd[@]}" 2>&1 | tee -a "$OUTPUT_DIR/run.log"
  if python - "$OUTPUT_DIR/issue_rewrite.json" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.is_file():
    raise SystemExit(1)
data = json.loads(path.read_text(encoding="utf-8"))
if data.get("count") != 276 or len(data.get("instances") or {}) != 276:
    raise SystemExit(1)
print(f"complete aggregate validated: {path}")
PY
  then
    exit 0
  fi
done

echo "Issue rewrite remains incomplete after $max_passes passes." >&2
exit 1

#!/usr/bin/env bash
set -euo pipefail

BRT3=/root/Baxxhy/BugReproduce/brt3
run_dir="${1:-}"
if [[ -z "$run_dir" ]]; then
  echo "Usage: bash scripts/resume_brt3_run.sh <run_dir> [extra args...]" >&2
  exit 2
fi
shift || true
bash "$BRT3/scripts/run_brt3_mutation_stable_full.sh" --run-dir "$run_dir" --resume "$@"

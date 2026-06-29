#!/usr/bin/env bash
set -euo pipefail

BRT3=/root/Baxxhy/BugReproduce/brt3
run_dir="${1:-}"
if [[ -z "$run_dir" ]]; then
  run_dir=$(find "$BRT3/results/runs" -maxdepth 1 -type d -name 'run_*' -printf '%T@ %p\n' 2>/dev/null | sort -n | tail -1 | cut -d' ' -f2-)
fi
if [[ -z "$run_dir" || ! -d "$run_dir" ]]; then
  echo "No run directory found." >&2
  exit 1
fi

python - "$run_dir" <<'PY'
import json, re, sys
from collections import Counter
from pathlib import Path

run = Path(sys.argv[1])
generation = run / "generation"
summaries = sorted(generation.glob("*/summary.json"))
final_tests = sorted(generation.glob("*/final_test.py"))
running = sorted(generation.glob("*/.running"))
status = Counter()
api_errors = Counter()
recent = []
for path in summaries:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        continue
    status[str(data.get("status") or "UNKNOWN")] += 1
    for err in data.get("api_error_types") or []:
        api_errors[str(err)] += 1
    if data.get("final_reason"):
        recent.append((path.stat().st_mtime, path.parent.name, data.get("status"), str(data.get("final_reason"))[:200]))
for log in (run / "logs").glob("*.log"):
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except Exception:
        continue
    api_errors["HTTP_429_log"] += len(re.findall(r"HTTP_429|HTTP 429|429", text))
    api_errors["timeout_log"] += len(re.findall(r"timeout|Timeout|TIMEOUT", text))
    api_errors["5xx_log"] += len(re.findall(r"HTTP_5\\d\\d|HTTP 5\\d\\d", text))
eval_started = (run / "evaluation").is_dir() and any((run / "evaluation").glob("worker_*/results.json"))
print("当前 run dir:", run)
print("summary.json 数量:", len(summaries))
print("final_test.py 数量:", len(final_tests))
print(".running 数量:", len(running))
print("生成状态分布:", dict(status))
print("API 429/timeout/5xx 统计:", dict(api_errors))
print("前10条完成情况:")
for path in summaries[:10]:
    data = json.loads(path.read_text(encoding="utf-8"))
    print(" ", path.parent.name, data.get("status"), "final_test=", (path.parent / "final_test.py").is_file())
print("正式评测是否开始:", bool(eval_started))
print("最近失败原因:")
for _, iid, st, reason in sorted(recent, reverse=True)[:10]:
    print(" ", iid, f"[{st}]", reason)
PY

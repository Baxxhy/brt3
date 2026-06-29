# BRT3 Self Check

Run from:

```bash
cd /root/Baxxhy/BugReproduce/brt3
```

## Static Checks

```bash
python -m compileall .
python -m cli.run --help
python -m cli.run_issue_rewrite --help
python -m evaluation.direct_eval --help
python -m scripts.collect_outputs --help
```

## Smoke Test

```bash
bash scripts/run_latest_full_pipeline.sh \
  --generation-only \
  --smoke \
  --smoke-n 1 \
  --max-workers 1 \
  --timeout 600
```

If API, Conda, or repository setup fails, keep the run directory and inspect:

```bash
python scripts/monitor_run.py --run-dir results/runs/<run_id> --once
tail -80 results/runs/<run_id>/logs/generation.log
```

## Output Collection Check

```bash
python -m scripts.collect_outputs \
  --input results/runs/<run_id> \
  --output results/runs/<run_id>/exports/collected_outputs.json
```

The collector writes one JSON record per instance with:

```json
{
  "instance_id": "...",
  "generated_test": "...",
  "final_prompt": "...",
  "final_status": "...",
  "test_path": "...",
  "logs": {},
  "metadata": {}
}
```

## Latest Experiment Summary

```bash
cat results/LATEST_EXPERIMENT_SUMMARY.md
```

## Files That Must Not Be Deleted

```text
results/
logs/
data/
retrieval_results/
README*.md
SELF_CHECK.md
swt.txt
```


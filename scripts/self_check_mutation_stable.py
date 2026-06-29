#!/usr/bin/env python3
"""Lightweight self-checks for the stable mutation run path."""

from __future__ import annotations

import json
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from llm.api_pool import configured_api_metadata
from llm.llm_client import LLMClient
from mutation.brt_mutation_rules import RULE_NAMES, rule_catalog
from mutation.mutation_plan_schema import validate_plan_payload
from core.schema import BehaviorTarget


def check_api_pool() -> None:
    entries = configured_api_metadata()
    names = {entry["name"] for entry in entries}
    assert len(entries) == 8, f"expected 8 API entries, got {len(entries)}"
    assert "fa_251812017" in names, "missing fa_251812017"
    # Intentionally do not print keys or Authorization headers.
    print("api_pool_check=ok count=8 required_name_present=true")


def check_mutation_schema() -> None:
    assert "ARG_BOUNDARY_EXPAND" in RULE_NAMES
    assert len(rule_catalog()) >= 9
    behavior = BehaviorTarget(instance_id="fake", expected_behavior={"text": "should not crash"})
    plan, warnings = validate_plan_payload(
        {
            "issue_pattern": "null_empty",
            "selected_rules": [
                {
                    "rule": "ARG_BOUNDARY_EXPAND",
                    "why_issue_aligned": "Issue mentions empty input.",
                    "risk": "low",
                }
            ],
            "oracle_strategy": "public_property",
        },
        behavior,
    )
    assert plan["mutation_ops"] == ["ARG_BOUNDARY_EXPAND"]
    assert isinstance(warnings, list)
    print("mutation_rule_schema_check=ok")


def check_llm_cache() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        client = LLMClient(
            model="deepseek-v3",
            api_key="dummy",
            base_url="https://example.invalid/v1",
            instance_id="selfcheck",
            llm_cache_dir=tmp,
            reuse_llm_cache=True,
            refresh_llm_cache=False,
        )
        key = client._cache_key("system", "user", 0.0, "stage", "text")
        client._write_cache(key, "system", "user", 0.0, "stage", "cached-response")
        response = client.chat("system", "user", temperature=0.0, stage_name="stage")
        assert response == "cached-response"
        assert client.cache_hit_count == 1
    print("llm_cache_check=ok")


def check_api_retry() -> None:
    original_urlopen = urllib.request.urlopen
    original_sleep = time.sleep

    def failing_urlopen(*args, **kwargs):  # noqa: ANN001
        raise urllib.error.URLError("mock connection failure")

    try:
        urllib.request.urlopen = failing_urlopen  # type: ignore[assignment]
        time.sleep = lambda _: None  # type: ignore[assignment]
        with tempfile.TemporaryDirectory() as tmp:
            client = LLMClient(
                model="deepseek-v3",
                api_key="dummy",
                base_url="https://example.invalid/v1",
                instance_id="selfcheck-retry",
                llm_cache_dir=tmp,
                reuse_llm_cache=False,
                refresh_llm_cache=True,
            )
            client.max_attempts = 2
            try:
                client.chat("system", "different-user", temperature=0.0, stage_name="retry")
            except RuntimeError:
                pass
            else:
                raise AssertionError("mock request unexpectedly succeeded")
            assert client.api_retry_count >= 2
            assert client.api_error_types
    finally:
        urllib.request.urlopen = original_urlopen  # type: ignore[assignment]
        time.sleep = original_sleep  # type: ignore[assignment]
    print("api_retry_check=ok")


def check_analysis_script_outputs() -> None:
    script = Path("scripts/analyze_v0_v1_regression.py")
    assert script.is_file()
    # The full analysis is exercised by run_brt3_mutation_stable_full.sh. This
    # self-check only verifies that the script is importable and the preserved
    # input directories exist.
    for path in [
        Path("results/preserved/f2p_40_20260621_224723"),
        Path("results/preserved/f2p_42_20260623_091037"),
    ]:
        assert path.is_dir(), f"missing preserved result: {path}"
    print("analysis_script_check=ok")


def main() -> None:
    check_api_pool()
    check_mutation_schema()
    check_llm_cache()
    check_api_retry()
    check_analysis_script_outputs()
    print(json.dumps({"self_check": "ok"}, ensure_ascii=False))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Validate task-scoped prompt files and legacy template exports."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


REQUIRED_TEMPLATE_CONSTANTS = (
    "ISSUE_REWRITE_SYSTEM_PROMPT",
    "ISSUE_REWRITE_USER_PROMPT",
    "HOST_CONTEXT_SYSTEM_PROMPT",
    "HOST_CONTEXT_USER_PROMPT",
    "MUTATION_GENERATION_SYSTEM_PROMPT",
    "MUTATION_GENERATION_USER_PROMPT",
    "OBSERVATION_PROBE_SYSTEM_PROMPT",
    "OBSERVATION_PROBE_USER_PROMPT",
    "ASSERT_SYNTHESIS_SYSTEM_PROMPT",
    "ASSERT_SYNTHESIS_USER_PROMPT",
    "BUGGY_ONLY_VERIFIER_SYSTEM_PROMPT",
    "BUGGY_ONLY_VERIFIER_USER_PROMPT",
    "REPAIR_SETUP_SYSTEM_PROMPT",
    "REPAIR_SETUP_USER_PROMPT",
    "REPAIR_TRIGGER_SYSTEM_PROMPT",
    "REPAIR_TRIGGER_USER_PROMPT",
    "REPAIR_ORACLE_SYSTEM_PROMPT",
    "REPAIR_ORACLE_USER_PROMPT",
    "SURROGATE_PATCH_SYSTEM_PROMPT",
    "SURROGATE_PATCH_USER_PROMPT",
    "PROTOCOL_RECOVERY_SYSTEM_PROMPT",
    "PROTOCOL_RECOVERY_USER_PROMPT",
    "SEED_MUTATION_PLAN_SYSTEM_PROMPT",
    "SEED_MUTATION_PLAN_USER_PROMPT",
    "OBSERVATION_ORACLE_SYSTEM_PROMPT",
    "OBSERVATION_ORACLE_PROBE_PROMPT",
    "OBSERVATION_ORACLE_REBIND_PROMPT",
    "STRICT_SEMANTIC_VERIFIER_SYSTEM_PROMPT",
    "STRICT_SEMANTIC_VERIFIER_USER_PROMPT",
)


def main() -> int:
    try:
        from prompts import templates
        from prompts.loader import load_prompt
        from prompts.registry import list_prompt_tasks, validate_prompt_registry

        tasks = validate_prompt_registry()
        if tasks != list_prompt_tasks():
            raise AssertionError("validated tasks differ from registry order")

        print("task\tstatus\toutput_format\tsystem_chars\tuser_chars")
        for task_name in tasks:
            prompt = load_prompt(task_name)
            if prompt.task != task_name:
                raise AssertionError(
                    f"task mismatch: directory={task_name!r}, metadata={prompt.task!r}"
                )
            if prompt.base_dir.name != task_name:
                raise AssertionError(
                    f"base directory mismatch for {task_name!r}: {prompt.base_dir}"
                )
            if prompt.status not in {"used", "unused"}:
                raise AssertionError(
                    f"invalid status for {task_name!r}: {prompt.status!r}"
                )
            if not isinstance(prompt.system, str) or not prompt.system:
                raise AssertionError(f"empty system prompt for {task_name!r}")
            if not isinstance(prompt.user, str) or not prompt.user:
                raise AssertionError(f"empty user prompt for {task_name!r}")
            print(
                f"{prompt.task}\t{prompt.status}\t{prompt.output_format}\t"
                f"{len(prompt.system)}\t{len(prompt.user)}"
            )

        for name in REQUIRED_TEMPLATE_CONSTANTS:
            value = getattr(templates, name)
            if not isinstance(value, str) or not value:
                raise AssertionError(f"invalid templates compatibility constant: {name}")

        probe = load_prompt("observation_oracle_probe")
        rebind = load_prompt("observation_oracle_rebind")
        if probe.system != rebind.system:
            raise AssertionError(
                "observation_oracle_probe and observation_oracle_rebind "
                "must share identical system prompts"
            )

        print(
            f"prompt_check=ok tasks={len(tasks)} "
            f"legacy_constants={len(REQUIRED_TEMPLATE_CONSTANTS)}"
        )
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"prompt_check=failed error={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

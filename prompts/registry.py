"""Registry of prompt tasks stored under the prompts package."""

from __future__ import annotations

from pathlib import Path


PROMPTS_DIR = Path(__file__).resolve().parent

PROMPT_TASKS = {
    "issue_rewrite": "issue_rewrite",
    "host_context": "host_context",
    "mutation_generation": "mutation_generation",
    "observation_probe": "observation_probe",
    "assert_synthesis": "assert_synthesis",
    "buggy_only_verifier": "buggy_only_verifier",
    "repair_setup": "repair_setup",
    "repair_trigger": "repair_trigger",
    "repair_oracle": "repair_oracle",
    "surrogate_patch": "surrogate_patch",
    "protocol_recovery": "protocol_recovery",
    "seed_mutation_plan": "seed_mutation_plan",
    "observation_oracle_probe": "observation_oracle_probe",
    "observation_oracle_rebind": "observation_oracle_rebind",
    "strict_semantic_verifier": "strict_semantic_verifier",
}

_REQUIRED_FILES = ("prompt.toml", "system.md", "user.md")


class PromptRegistryError(RuntimeError):
    """Raised when the prompt registry does not match the filesystem."""


def list_prompt_tasks() -> tuple[str, ...]:
    """Return registered task names in stable registry order."""
    return tuple(PROMPT_TASKS)


def validate_prompt_registry() -> tuple[str, ...]:
    """Validate task mappings, directories, and required prompt files."""
    errors: list[str] = []
    for task, directory_name in PROMPT_TASKS.items():
        if task != directory_name:
            errors.append(
                f"task mapping must use the same key and directory name: "
                f"{task!r} != {directory_name!r}"
            )
        task_dir = PROMPTS_DIR / directory_name
        if not task_dir.is_dir():
            errors.append(f"missing prompt task directory: {task_dir}")
            continue
        for filename in _REQUIRED_FILES:
            path = task_dir / filename
            if not path.is_file():
                errors.append(f"missing prompt file for {task!r}: {path}")
    if errors:
        raise PromptRegistryError(
            "prompt registry validation failed:\n- " + "\n- ".join(errors)
        )
    return list_prompt_tasks()

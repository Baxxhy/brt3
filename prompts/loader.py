"""Load task-scoped prompt templates from TOML metadata and Markdown files."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .registry import PROMPTS_DIR, PROMPT_TASKS


try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 compatibility
    tomllib = None  # type: ignore[assignment]


class PromptLoadError(RuntimeError):
    """Base error for prompt loading failures."""


class PromptNotFoundError(PromptLoadError):
    """Raised when a prompt task is not registered."""


class PromptConfigError(PromptLoadError):
    """Raised when prompt metadata is missing or invalid."""


@dataclass(frozen=True)
class PromptTemplate:
    task: str
    status: str
    description: str
    system: str
    user: str
    output_format: str
    base_dir: Path


def _parse_simple_toml(text: str, source: Path) -> dict[str, Any]:
    """Parse the string-only TOML subset used by prompt metadata."""
    data: dict[str, Any] = {}
    current: dict[str, Any] = data
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            if not section or "." in section:
                raise PromptConfigError(
                    f"unsupported TOML section in {source}:{line_number}: {line}"
                )
            existing = data.setdefault(section, {})
            if not isinstance(existing, dict):
                raise PromptConfigError(
                    f"duplicate TOML key in {source}:{line_number}: {section}"
                )
            current = existing
            continue
        if "=" not in line:
            raise PromptConfigError(
                f"invalid TOML assignment in {source}:{line_number}: {line}"
            )
        key, raw_value = (part.strip() for part in line.split("=", 1))
        if not key or not raw_value.startswith('"') or not raw_value.endswith('"'):
            raise PromptConfigError(
                f"only quoted string values are supported in "
                f"{source}:{line_number}: {line}"
            )
        try:
            value = json.loads(raw_value)
        except json.JSONDecodeError as exc:
            raise PromptConfigError(
                f"invalid quoted TOML value in {source}:{line_number}: {exc}"
            ) from exc
        current[key] = value
    return data


def _load_metadata(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise PromptConfigError(f"missing prompt metadata file: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PromptConfigError(f"cannot read prompt metadata file {path}: {exc}") from exc
    try:
        if tomllib is not None:
            return tomllib.loads(text)
        return _parse_simple_toml(text, path)
    except PromptConfigError:
        raise
    except Exception as exc:  # tomllib.TOMLDecodeError without version coupling
        raise PromptConfigError(f"cannot parse prompt metadata file {path}: {exc}") from exc


def _required_string(
    mapping: dict[str, Any],
    key: str,
    source: Path,
    *,
    section: str = "",
) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        location = f"[{section}].{key}" if section else key
        raise PromptConfigError(
            f"prompt metadata {source} requires a non-empty string at {location}"
        )
    return value


def _template_path(task_dir: Path, filename: str, source: Path) -> Path:
    path = (task_dir / filename).resolve()
    if path.parent != task_dir.resolve():
        raise PromptConfigError(
            f"prompt template path must stay inside {task_dir}: {filename!r}"
        )
    if not path.is_file():
        raise PromptConfigError(
            f"missing prompt template referenced by {source}: {path}"
        )
    return path


def _read_template(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PromptLoadError(f"cannot read prompt template {path}: {exc}") from exc


@lru_cache(maxsize=None)
def load_prompt(task_name: str) -> PromptTemplate:
    """Load one registered prompt task without formatting runtime variables."""
    directory_name = PROMPT_TASKS.get(task_name)
    if directory_name is None:
        available = ", ".join(PROMPT_TASKS)
        raise PromptNotFoundError(
            f"unknown prompt task {task_name!r}; available tasks: {available}"
        )

    task_dir = PROMPTS_DIR / directory_name
    metadata_path = task_dir / "prompt.toml"
    metadata = _load_metadata(metadata_path)
    task = _required_string(metadata, "task", metadata_path)
    status = _required_string(metadata, "status", metadata_path)
    description = _required_string(metadata, "description", metadata_path)
    if task != task_name:
        raise PromptConfigError(
            f"prompt task mismatch in {metadata_path}: expected {task_name!r}, got {task!r}"
        )
    if status not in {"used", "unused"}:
        raise PromptConfigError(
            f"invalid prompt status in {metadata_path}: {status!r}"
        )

    template = metadata.get("template")
    if not isinstance(template, dict):
        raise PromptConfigError(f"missing [template] section in {metadata_path}")
    system_name = _required_string(
        template, "system", metadata_path, section="template"
    )
    user_name = _required_string(
        template, "user", metadata_path, section="template"
    )

    output = metadata.get("output")
    if not isinstance(output, dict):
        raise PromptConfigError(f"missing [output] section in {metadata_path}")
    output_format = _required_string(
        output, "format", metadata_path, section="output"
    )
    if output_format not in {"json", "python", "text"}:
        raise PromptConfigError(
            f"invalid output format in {metadata_path}: {output_format!r}"
        )

    system_path = _template_path(task_dir, system_name, metadata_path)
    user_path = _template_path(task_dir, user_name, metadata_path)
    return PromptTemplate(
        task=task,
        status=status,
        description=description,
        system=_read_template(system_path),
        user=_read_template(user_path),
        output_format=output_format,
        base_dir=task_dir,
    )


def get_system_prompt(task_name: str) -> str:
    """Return the raw system prompt for a registered task."""
    return load_prompt(task_name).system


def get_user_prompt(task_name: str) -> str:
    """Return the raw user prompt template for a registered task."""
    return load_prompt(task_name).user


def clear_prompt_cache() -> None:
    """Clear cached prompt templates, primarily for local development checks."""
    load_prompt.cache_clear()

"""Local OpenAI-compatible API pool loaded from an untracked secrets file."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SECRETS_PATH = PROJECT_ROOT / ".secrets" / "api_pool.local.json"


def _secrets_path() -> Path:
    configured = os.environ.get("BRT3_API_POOL_SECRETS", "").strip()
    return Path(configured).expanduser().resolve() if configured else DEFAULT_SECRETS_PATH


def _load_secret_entries() -> list[dict[str, str]]:
    path = _secrets_path()
    if not path.is_file():
        raise FileNotFoundError(
            "BRT3 API pool secrets file is missing: "
            f"{path}. Create an untracked .secrets/api_pool.local.json file."
        )
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError(f"invalid BRT3 API pool secrets JSON at {path}: {exc}") from exc
    raw_entries = payload.get("apis") if isinstance(payload, dict) else None
    if not isinstance(raw_entries, list) or not raw_entries:
        raise ValueError(
            f"BRT3 API pool secrets at {path} must contain a non-empty 'apis' list"
        )
    entries: list[dict[str, str]] = []
    names: set[str] = set()
    for index, raw in enumerate(raw_entries):
        if not isinstance(raw, dict):
            raise ValueError(f"API pool entry {index} must be an object")
        entry = {
            "name": str(raw.get("name") or "").strip(),
            "base_url": str(raw.get("base_url") or "").strip(),
            "api_key": str(raw.get("api_key") or "").strip(),
            "model": str(raw.get("model") or "deepseek-v3").strip(),
        }
        missing = [key for key in ("name", "base_url", "api_key") if not entry[key]]
        if missing:
            raise ValueError(
                f"API pool entry {index} is missing required fields: {', '.join(missing)}"
            )
        if entry["name"] in names:
            raise ValueError(f"duplicate API pool name: {entry['name']}")
        names.add(entry["name"])
        entries.append(entry)
    return entries


def configured_apis() -> list[tuple[str, str, str]]:
    """Return validated (key, base_url, model) entries without logging secrets."""
    return [
        (entry["api_key"], entry["base_url"], entry["model"])
        for entry in _load_secret_entries()
    ]


def configured_api_name(index: int) -> str:
    entries = _load_secret_entries()
    return entries[index]["name"] if 0 <= index < len(entries) else f"key_{index}"


def _mask_key(value: str) -> str:
    if len(value) <= 8:
        return "****"
    return f"{value[:3]}****{value[-4:]}"


def configured_api_metadata() -> list[dict[str, str | int]]:
    """Return only masked, non-secret API metadata for logs and self-checks."""
    return [
        {
            "index": index,
            "name": entry["name"],
            "base_url": entry["base_url"],
            "model": entry["model"],
            "masked_key": _mask_key(entry["api_key"]),
        }
        for index, entry in enumerate(_load_secret_entries())
    ]

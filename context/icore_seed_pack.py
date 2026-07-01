"""iCoRe-anchored seed packaging for BRT generation."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.io_utils import read_repo_file
from core.schema import BehaviorTarget, RetrievedTest
from core.utils import truncate_text


SEED_POLICY = "icore_anchored_multi_seed"
ALLOW_SAME_FILE_EXPANSION = False


@dataclass
class ICoreSeedItem:
    seed_id: str
    icore_rank: int
    file: str
    name: str
    code_content: str
    exists_in_repo: bool = False
    full_file_found: bool = False
    exact_entry_found: bool = False
    host_recoverable: bool = False
    brief_score_breakdown: dict[str, Any] = field(default_factory=dict)
    role: str = "reference_only"
    preflight_status: str = ""
    fallback_reason: str = ""

    def to_retrieved_test(self, instance_id: str) -> RetrievedTest:
        return RetrievedTest(
            instance_id=instance_id,
            name=self.name,
            file=self.file,
            code_content=self.code_content,
            raw={
                "source": SEED_POLICY,
                "seed_id": self.seed_id,
                "icore_rank": self.icore_rank,
            },
        )

    def to_dict(self, max_code_chars: int = 12000) -> dict[str, Any]:
        return {
            "seed_id": self.seed_id,
            "icore_rank": self.icore_rank,
            "file": self.file,
            "name": self.name,
            "code_content": truncate_text(self.code_content, max_code_chars),
            "exists_in_repo": self.exists_in_repo,
            "full_file_found": self.full_file_found,
            "exact_entry_found": self.exact_entry_found,
            "host_recoverable": self.host_recoverable,
            "brief_score_breakdown": self.brief_score_breakdown,
            "role": self.role,
            "preflight_status": self.preflight_status,
            "fallback_reason": self.fallback_reason,
        }


def build_icore_seed_pack(
    related_tests: list[RetrievedTest],
    behavior: BehaviorTarget,
    buggy_repo: str,
    top_k: int = 5,
) -> list[ICoreSeedItem]:
    """Return the original iCoRe top-k seeds without same-file expansion."""
    seed_pack: list[ICoreSeedItem] = []
    api_names = _target_api_names(behavior)
    for rank, test in enumerate(related_tests[:top_k]):
        full_source = read_repo_file(buggy_repo, test.file) if test.file else ""
        exact_entry_found = _exact_entry_found(full_source, test.name)
        code_present = bool((test.code_content or "").strip())
        matched_apis = [
            name for name in api_names if name and _last_segment(name) in (test.code_content or "")
        ]
        item = ICoreSeedItem(
            seed_id=f"icore_{rank}",
            icore_rank=rank,
            file=test.file,
            name=test.name,
            code_content=test.code_content,
            exists_in_repo=bool(full_source),
            full_file_found=bool(full_source),
            exact_entry_found=exact_entry_found,
            host_recoverable=bool(exact_entry_found or code_present),
            brief_score_breakdown={
                "icore_rank": rank,
                "exact_entry_found": exact_entry_found,
                "retrieved_snippet_present": code_present,
                "target_api_name_overlap": matched_apis[:10],
            },
            role="anchor_candidate" if rank < 3 else "reference_only",
        )
        seed_pack.append(item)
    return seed_pack


def select_anchor_seed(
    seed_pack: list[ICoreSeedItem],
    max_fallback: int = 3,
) -> tuple[ICoreSeedItem | None, dict[str, Any]]:
    """Choose only from iCoRe top-N, preferring the first recoverable seed."""
    candidates = seed_pack[:max(1, max_fallback)]
    diagnostics: dict[str, Any] = {
        "seed_policy": SEED_POLICY,
        "allow_same_file_expansion": ALLOW_SAME_FILE_EXPANSION,
        "expanded_ast_candidates_disabled": True,
        "fallback_used": False,
        "fallback_reason": "",
    }
    for item in candidates:
        if item.host_recoverable:
            item.role = "anchor_candidate"
            diagnostics["anchor_level"] = (
                "exact_icore_top1" if item.icore_rank == 0 else "icore_topk_fallback"
            )
            return item, diagnostics
    if seed_pack:
        anchor = seed_pack[0]
        anchor.role = "anchor_candidate"
        diagnostics["fallback_used"] = True
        diagnostics["fallback_reason"] = (
            "no host_recoverable seed found in iCoRe top"
            f"{len(candidates)}; falling back to iCoRe top1"
        )
        diagnostics["anchor_level"] = "exact_icore_top1"
        return anchor, diagnostics
    diagnostics["fallback_used"] = True
    diagnostics["fallback_reason"] = "no iCoRe related_tests available"
    diagnostics["anchor_level"] = ""
    return None, diagnostics


def seed_pack_prompt_payload(seed_pack: list[ICoreSeedItem]) -> dict[str, Any]:
    return {
        "seed_policy": SEED_POLICY,
        "allow_same_file_expansion": ALLOW_SAME_FILE_EXPANSION,
        "expanded_ast_candidates_disabled": True,
        "reference_seeds": [item.to_dict(max_code_chars=5000) for item in seed_pack],
    }


def _exact_entry_found(source: str, entry: str) -> bool:
    if not source.strip() or not entry:
        return False
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    wanted_class = ""
    wanted_name = _normalize_entry(entry)
    if "." in wanted_name:
        wanted_class, wanted_name = wanted_name.rsplit(".", 1)
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            if wanted_class and node.name != wanted_class:
                continue
            if any(
                isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                and child.name == wanted_name
                for child in node.body
            ):
                return True
        elif (
            not wanted_class
            and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == wanted_name
        ):
            return True
    return False


def _normalize_entry(name: str) -> str:
    raw = re.sub(r"\[[^\]]*\]$", "", str(name or "").strip())
    if not raw:
        return ""
    if "::" in raw:
        parts = [part for part in raw.split("::") if part]
        if parts and parts[0].endswith(".py"):
            parts = parts[1:]
        return ".".join(parts[-2:]) if len(parts) >= 2 else (parts[-1] if parts else "")
    parts = [part for part in raw.split(".") if part]
    return ".".join(parts[-2:]) if len(parts) >= 2 else (parts[-1] if parts else "")


def _target_api_names(behavior: BehaviorTarget) -> list[str]:
    names: list[str] = []
    for item in behavior.target_apis:
        if isinstance(item, dict) and item.get("name"):
            names.append(str(item["name"]))
    return list(dict.fromkeys(names))


def _last_segment(name: str) -> str:
    return str(name or "").rsplit(".", 1)[-1]

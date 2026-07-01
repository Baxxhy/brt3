"""Create and validate a small, issue-guided mutation plan."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from prompts.loader import load_prompt
from core.schema import (
    BehaviorTarget,
    HostContext,
    HostScaffold,
    MutationPlan,
    ProtocolRecovery,
)
from core.utils import extract_json_object, safe_json_dump, truncate_text, write_text
from mutation.anchored_plan import (
    attach_anchored_fields,
    sanitize_anchored_plan,
)
from mutation.mutation_effect_check import check_mutation_effect
from mutation.mutation_operator_router import route_candidate_operators
from mutation.mutation_plan_schema import mutation_plan_from_payload


_SEED_MUTATION_PLAN_PROMPT = load_prompt("seed_mutation_plan")
SEED_MUTATION_PLAN_SYSTEM_PROMPT = _SEED_MUTATION_PLAN_PROMPT.system
SEED_MUTATION_PLAN_USER_PROMPT = _SEED_MUTATION_PLAN_PROMPT.user


def _normalize_plan(instance_id: str, round_id: int, data: dict[str, Any], behavior: BehaviorTarget) -> MutationPlan:
    plan, _ = mutation_plan_from_payload(instance_id, round_id, data, behavior)
    return plan


def _compact_for_prompt(value: Any, max_string_chars: int = 6000) -> Any:
    """Keep prompt inputs structurally useful without sending huge execution logs."""
    if isinstance(value, str):
        return truncate_text(value, max_string_chars)
    if isinstance(value, list):
        return [_compact_for_prompt(item, max_string_chars) for item in value[:20]]
    if isinstance(value, dict):
        compact: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if key_text in {"stdout", "stderr", "output", "log", "execution_log"}:
                compact[key] = truncate_text(str(item), 3000)
            elif key_text in {"seed_execution", "execution", "seed_execution_log"}:
                compact[key] = _compact_for_prompt(item, 3000)
            elif key_text in {"full_file_content", "full_test_file_content"}:
                compact[key] = truncate_text(str(item), 12000)
            else:
                compact[key] = _compact_for_prompt(item, max_string_chars)
        return compact
    return value


def build_mutation_plan(
    instance_id: str,
    round_id: int,
    behavior: BehaviorTarget,
    host: HostContext,
    host_scaffold: HostScaffold,
    protocol: ProtocolRecovery | None,
    llm_client: Any,
    output_dir: str,
    execution_feedback: str = "",
    verifier_feedback: dict[str, Any] | None = None,
    analysis_prior_hint: str = "",
    protocol_context_audit: dict[str, Any] | None = None,
    seed_pack: dict[str, Any] | None = None,
) -> MutationPlan:
    candidate_operators = route_candidate_operators(
        behavior,
        host,
        protocol,
        execution_feedback=execution_feedback,
        verifier_feedback=verifier_feedback,
        protocol_context_audit=protocol_context_audit,
        prior=analysis_prior_hint,
    )
    candidate_operators_path = (
        Path(output_dir) / f"candidate_operators_round_{round_id}.json"
    )
    safe_json_dump(candidate_operators, str(candidate_operators_path))
    prompt = SEED_MUTATION_PLAN_USER_PROMPT.format(
        behavior_json=json.dumps(_compact_for_prompt(behavior.to_dict(), 6000), ensure_ascii=False),
        host_context_json=json.dumps(_compact_for_prompt(host.to_dict(), 6000), ensure_ascii=False),
        host_scaffold_json=json.dumps(
            _compact_for_prompt(host_scaffold.to_dict(), 12000),
            ensure_ascii=False,
        ),
        protocol_json=json.dumps(_compact_for_prompt(protocol.to_dict() if protocol else {}, 6000), ensure_ascii=False),
        protocol_context_audit_json=json.dumps(_compact_for_prompt(protocol_context_audit or {}, 6000), ensure_ascii=False),
        execution_feedback=truncate_text(execution_feedback or "无", 12000),
        verifier_feedback=json.dumps(_compact_for_prompt(verifier_feedback or {}, 6000), ensure_ascii=False),
        candidate_operators_json=json.dumps(candidate_operators, ensure_ascii=False),
        analysis_prior_hint=analysis_prior_hint or "无",
    )
    if seed_pack:
        prompt += (
            "\n\n【iCoRe Anchored Multi-Seed Context】\n"
            + json.dumps(_compact_for_prompt(seed_pack, 6000), ensure_ascii=False)
            + "\nanchor_seed 是唯一允许继承 host scaffold 的测试。"
            "reference_seeds 只能用于参考 API usage、object construction、"
            "boundary values、assertion style 和 mock pattern；不得把 reference "
            "seed 的 class wrapper、fixtures 或 setup 搬进 anchor scaffold，"
            "除非它们已经存在于 HostContext/HostScaffold。"
            "\nMutationPlan 必须显式填写 anchor_seed_used、reference_seeds_used、"
            "borrowed_elements、mutated_elements、issue_alignment、"
            "buggy_expected_behavior、fixed_expected_behavior、oracle_plan。"
        )
    prompt_path = Path(output_dir) / "prompts" / f"mutation_plan_round_{round_id}.txt"
    response_path = Path(output_dir) / "responses" / f"mutation_plan_round_{round_id}.txt"
    write_text(str(prompt_path), SEED_MUTATION_PLAN_SYSTEM_PROMPT + "\n\n" + prompt)
    response = llm_client.chat(
        SEED_MUTATION_PLAN_SYSTEM_PROMPT,
        prompt,
        stage_name=f"mutation_plan_round_{round_id}",
        response_format="json",
    )
    write_text(str(response_path), response)
    try:
        data = extract_json_object(response)
    except ValueError as first_error:
        retry_prompt = (
            prompt
            + "\n\n上一次 mutation plan 无法解析："
            + str(first_error)
            + "。请重新输出一个完整合法 JSON 对象，不要 Markdown、注释或解释。"
        )
        response = llm_client.chat(
            SEED_MUTATION_PLAN_SYSTEM_PROMPT,
            retry_prompt,
            stage_name=f"mutation_plan_round_{round_id}_json_retry",
            response_format="json",
        )
        write_text(str(Path(output_dir) / "responses" / f"mutation_plan_round_{round_id}_json_retry.txt"), response)
        data = extract_json_object(response)
    legacy_plan, warnings = mutation_plan_from_payload(
        instance_id,
        round_id,
        data,
        behavior,
        candidate_operators,
    )
    plan = attach_anchored_fields(
        copy.deepcopy(legacy_plan),
        data,
        behavior,
        host_scaffold,
    )
    sanitizer = sanitize_anchored_plan(plan, host_scaffold)
    repair_attempted = False
    repair_error = ""
    if (
        sanitizer["status"] != "PASS"
        and host_scaffold.host_scaffold_mode == "ast_scaffold"
    ):
        repair_attempted = True
        repair_prompt = (
            prompt
            + "\n\n上一次 Anchored MutationPlan 未通过静态校验。"
            + "保持同一 BehaviorTarget、HostScaffold 和候选算子，只修复以下错误：\n"
            + "\n".join(f"- {item}" for item in sanitizer["errors"])
            + "\n重新输出完整合法 JSON。before_pattern 必须逐字来自 HostScaffold，"
            + "且在对应 anchor_scope 中只出现一次。不要输出 Markdown 或解释。"
        )
        try:
            repair_response = llm_client.chat(
                SEED_MUTATION_PLAN_SYSTEM_PROMPT,
                repair_prompt,
                stage_name=f"mutation_plan_round_{round_id}_anchor_repair",
                response_format="json",
            )
            write_text(
                str(
                    Path(output_dir)
                    / "responses"
                    / f"mutation_plan_round_{round_id}_anchor_repair.txt"
                ),
                repair_response,
            )
            repair_data = extract_json_object(repair_response)
            repaired_legacy, repaired_warnings = mutation_plan_from_payload(
                instance_id,
                round_id,
                repair_data,
                behavior,
                candidate_operators,
            )
            repaired_plan = attach_anchored_fields(
                repaired_legacy,
                repair_data,
                behavior,
                host_scaffold,
            )
            repaired_sanitizer = sanitize_anchored_plan(
                repaired_plan,
                host_scaffold,
            )
            if repaired_sanitizer["status"] == "PASS":
                plan = repaired_plan
                sanitizer = repaired_sanitizer
                warnings.extend(repaired_warnings)
            else:
                repair_error = "; ".join(repaired_sanitizer["errors"])
                sanitizer = repaired_sanitizer
        except Exception as exc:  # noqa: BLE001
            repair_error = str(exc)
    elif sanitizer["status"] != "PASS":
        repair_error = (
            "HostScaffold extraction fell back to old context; "
            "anchor repair skipped"
        )

    if sanitizer["status"] == "PASS":
        plan.mutation_plan_mode = "anchored"
        plan.fallback_reason = ""
    else:
        fallback_errors = list(sanitizer.get("errors") or [])
        if repair_error:
            fallback_errors.append(f"anchor repair failed: {repair_error}")
        plan = legacy_plan
        plan.mutation_plan_mode = "fallback_old"
        plan.selected_operators = list(plan.mutation_ops[:2])
        plan.mutation_targets = []
        plan.preserve_constraints = []
        plan.before_pattern_found = bool(
            sanitizer.get("before_pattern_found")
        )
        plan.before_pattern_unique = bool(
            sanitizer.get("before_pattern_unique")
        )
        plan.sanitizer_status = "FALLBACK_OLD"
        plan.sanitizer_warnings = fallback_errors
        plan.fallback_reason = (
            "anchored mutation sanitization failed after one repair; "
            "using legacy mutation plan"
        )
        plan.scaffold_hash = host_scaffold.scaffold_hash

    sanitizer_payload = {
        **sanitizer,
        "repair_attempted": repair_attempted,
        "repair_error": repair_error,
        "mutation_plan_mode": plan.mutation_plan_mode,
        "fallback_reason": plan.fallback_reason,
    }
    safe_json_dump(
        sanitizer_payload,
        str(
            Path(output_dir)
            / f"mutation_sanitizer_round_{round_id}.json"
        ),
    )
    effect_check = check_mutation_effect(
        plan,
        behavior,
        execution_feedback=execution_feedback,
        verifier_feedback=verifier_feedback,
    )
    safe_json_dump(
        effect_check,
        str(Path(output_dir) / f"mutation_effect_check_round_{round_id}.json"),
    )
    payload = plan.to_dict()
    payload["validation_warnings"] = warnings
    payload["sanitizer"] = sanitizer_payload
    payload["mutation_effect_check"] = effect_check
    payload["mutation_effect_warnings"] = effect_check["warnings"]
    safe_json_dump(payload, str(Path(output_dir) / f"mutation_round_{round_id}_plan.json"))
    return plan

"""Create and validate a small, issue-guided mutation plan."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from prompts.templates import SEED_MUTATION_PLAN_SYSTEM_PROMPT, SEED_MUTATION_PLAN_USER_PROMPT
from core.schema import BehaviorTarget, HostContext, MutationPlan, ProtocolRecovery
from core.utils import extract_json_object, safe_json_dump, truncate_text, write_text
from mutation.brt_mutation_rules import trigger_rule_catalog
from mutation.mutation_plan_schema import mutation_plan_from_payload


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
    protocol: ProtocolRecovery | None,
    llm_client: Any,
    output_dir: str,
    execution_feedback: str = "",
    verifier_feedback: dict[str, Any] | None = None,
    analysis_prior_hint: str = "",
) -> MutationPlan:
    prompt = SEED_MUTATION_PLAN_USER_PROMPT.format(
        behavior_json=json.dumps(_compact_for_prompt(behavior.to_dict(), 6000), ensure_ascii=False),
        host_context_json=json.dumps(_compact_for_prompt(host.to_dict(), 6000), ensure_ascii=False),
        protocol_json=json.dumps(_compact_for_prompt(protocol.to_dict() if protocol else {}, 6000), ensure_ascii=False),
        execution_feedback=truncate_text(execution_feedback or "无", 12000),
        verifier_feedback=json.dumps(_compact_for_prompt(verifier_feedback or {}, 6000), ensure_ascii=False),
        mutation_rules_json=json.dumps(trigger_rule_catalog(), ensure_ascii=False),
        analysis_prior_hint=analysis_prior_hint or "无",
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
    plan, warnings = mutation_plan_from_payload(instance_id, round_id, data, behavior)
    payload = plan.to_dict()
    payload["validation_warnings"] = warnings
    safe_json_dump(payload, str(Path(output_dir) / f"mutation_round_{round_id}_plan.json"))
    return plan

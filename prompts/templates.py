"""Compatibility exports for legacy prompt constant imports.

New code should load task-scoped templates through :mod:`prompts.loader`.
"""

from .loader import get_system_prompt, get_user_prompt


# Legacy shared fragments. Task Markdown files contain fully expanded text and
# do not depend on these constants.
_JSON_RULES = "只输出一个合法 JSON 对象；不要 markdown；不要解释；不要使用真实 patch、patched version 或 golden test；不要生成无关测试。"
_CODE_RULES = "只输出 Python 代码；不要 markdown；不要解释；不要使用真实 patch、patched version 或 golden test；优先复用相似测试上下文；只改必要部分。"
_ENHANCEMENT_RULES = """
通用硬约束：
1. 不得使用、猜测或请求真实 patch、golden patch、golden test、FAIL_TO_PASS 或 PASS_TO_PASS。
2. 只能生成一个测试入口，不得修改原测试文件。
3. 不得吞异常，不得写 assert True/assert False，不得使用 pytest.raises(Exception)，不得无条件 skip。
4. expected_behavior 必须来自 Issue；buggy observation 只能帮助选择观察对象，不能直接作为 expected value。
5. 优先断言公开行为，保留 seed test 的测试协议，只做 Issue 相关的小变异。
"""


ISSUE_REWRITE_SYSTEM_PROMPT = get_system_prompt("issue_rewrite")
ISSUE_REWRITE_USER_PROMPT = get_user_prompt("issue_rewrite")

HOST_CONTEXT_SYSTEM_PROMPT = get_system_prompt("host_context")
HOST_CONTEXT_USER_PROMPT = get_user_prompt("host_context")

MUTATION_GENERATION_SYSTEM_PROMPT = get_system_prompt("mutation_generation")
MUTATION_GENERATION_USER_PROMPT = get_user_prompt("mutation_generation")

OBSERVATION_PROBE_SYSTEM_PROMPT = get_system_prompt("observation_probe")
OBSERVATION_PROBE_USER_PROMPT = get_user_prompt("observation_probe")

ASSERT_SYNTHESIS_SYSTEM_PROMPT = get_system_prompt("assert_synthesis")
ASSERT_SYNTHESIS_USER_PROMPT = get_user_prompt("assert_synthesis")

BUGGY_ONLY_VERIFIER_SYSTEM_PROMPT = get_system_prompt("buggy_only_verifier")
BUGGY_ONLY_VERIFIER_USER_PROMPT = get_user_prompt("buggy_only_verifier")

REPAIR_SETUP_SYSTEM_PROMPT = get_system_prompt("repair_setup")
REPAIR_SETUP_USER_PROMPT = get_user_prompt("repair_setup")

REPAIR_TRIGGER_SYSTEM_PROMPT = get_system_prompt("repair_trigger")
REPAIR_TRIGGER_USER_PROMPT = get_user_prompt("repair_trigger")

REPAIR_ORACLE_SYSTEM_PROMPT = get_system_prompt("repair_oracle")
REPAIR_ORACLE_USER_PROMPT = get_user_prompt("repair_oracle")

SURROGATE_PATCH_SYSTEM_PROMPT = get_system_prompt("surrogate_patch")
SURROGATE_PATCH_USER_PROMPT = get_user_prompt("surrogate_patch")

PROTOCOL_RECOVERY_SYSTEM_PROMPT = get_system_prompt("protocol_recovery")
PROTOCOL_RECOVERY_USER_PROMPT = get_user_prompt("protocol_recovery")

SEED_MUTATION_PLAN_SYSTEM_PROMPT = get_system_prompt("seed_mutation_plan")
SEED_MUTATION_PLAN_USER_PROMPT = get_user_prompt("seed_mutation_plan")

OBSERVATION_ORACLE_SYSTEM_PROMPT = get_system_prompt(
    "observation_oracle_probe"
)
OBSERVATION_ORACLE_PROBE_PROMPT = get_user_prompt(
    "observation_oracle_probe"
)
OBSERVATION_ORACLE_REBIND_PROMPT = get_user_prompt(
    "observation_oracle_rebind"
)

STRICT_SEMANTIC_VERIFIER_SYSTEM_PROMPT = get_system_prompt(
    "strict_semantic_verifier"
)
STRICT_SEMANTIC_VERIFIER_USER_PROMPT = get_user_prompt(
    "strict_semantic_verifier"
)

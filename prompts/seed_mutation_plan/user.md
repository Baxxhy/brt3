根据 Issue 目标、单一 seed、测试协议和候选算子生成一个小变异计划。最多选择 3 个 selected_rules；不得重写无关 setup，不得编造 expected value。
这是 seed mutation / trigger planning 阶段，只允许规划输入、参数、状态、配置、调用链、生命周期或 fixture/mock 数据的小变异。
禁止在本阶段选择 ORACLE_REBIND；断言重绑定只能在 strict verifier 明确给出 oracle_wrong、oracle_too_strong 或 assertion_mismatch 后，由 observation oracle 阶段单独执行。

BehaviorTarget：{behavior_json}
HostContext：{host_context_json}
ProtocolRecovery：{protocol_json}
ProtocolContextAudit：{protocol_context_audit_json}
CandidateOperators（只能从这里选择 rule 和 recommended_subtypes，allowed_scope 必须为 trigger）：{candidate_operators_json}
聚合 mutation prior（只表示 repo/issue_pattern/rule 的历史风险，不包含当前 instance 特判）：{analysis_prior_hint}
上一轮执行反馈：{execution_feedback}
Verifier 反馈：{verifier_feedback}

规划约束：
1. selected_rules 必须改变输入、参数、状态、调用链、配置、lifecycle 或 fixture/mock 数据。
2. 每个 selected_rule 必须包含具体且彼此不同的 before_pattern 和 after_pattern，并说明 expected_trigger_effect 与 observable_difference。
3. 禁止使用“change input”、“modify assertion”、“strengthen test”等空泛表达；必须指出 seed 中哪个元素从什么改成什么。
4. 如果上一轮 Buggy PASS 或 target_not_hit，说明上一轮为何未触发，并选择更强 trigger；优先 CALL_CHAIN_EXTEND、LIFECYCLE_TRIGGER、ARG_BOUNDARY_EXPAND、STATE_MUTATION，不得改 oracle。
5. 如果上一轮 UNRELATED_FAIL，说明如何收紧 target_api 和 seed_element，避免 off-target failure。
6. 如果上一轮是 SETUP_ERROR、COLLECT_ERROR 或 SYNTAX_ERROR，保持 seed protocol，不扩大 trigger，优先让 setup/protocol repair 生效。
7. 如果已经 ISSUE_ALIGNED_FAIL，保持 trigger 最小；oracle 不稳时留给后续 observation oracle。
8. 对 query_sql、repr_string_format、serialization、parser_render、io_path、warning，优先使用可观察公开行为的 oracle_strategy。
9. fault_proxy 只能概括 Issue 中的触发前提、buggy 行为、fixed 行为和公开可观察症状，不得引入 golden patch/test 信息。
10. implementation_mode 只能是 deterministic_ast、llm_edit、hybrid、observation_only；trigger planning 不得使用 observation_only。
11. ast_feasibility 只能是 none、partial、high。

只输出：
{{
  "mutation_goal": "",
  "issue_pattern": "boundary|null_empty|exception|warning|configuration|lifecycle|cache_state|serialization|query_sql|repr_string_format|dtype_shape|parser_render|io_path|api_call_chain|unknown",
  "fault_proxy": {{
    "trigger_precondition": "",
    "buggy_behavior": "",
    "expected_fixed_behavior": "",
    "observable_symptom": "",
    "target_api": "",
    "oracle_type": "",
    "why_issue_aligned": ""
  }},
  "selected_rules": [
    {{
      "rule": "",
      "operator_subtype": "",
      "mutation_scope": "trigger",
      "confidence": 0.0,
      "confidence_reason": "",
      "pre_requisite": [],
      "depends_on": [],
      "implementation_mode": "llm_edit",
      "ast_feasibility": "none",
      "target_code": "",
      "seed_element": "",
      "before_pattern": "",
      "after_pattern": "",
      "expected_trigger_effect": "",
      "observable_difference": "",
      "why_issue_aligned": "",
      "expected_buggy_observation": "",
      "expected_fixed_behavior": "",
      "risk": "low|medium|high"
    }}
  ],
  "preserve_from_seed": ["imports", "fixtures", "class wrapper", "runner", "setup"],
  "do_not_change": ["test framework", "unrelated fixtures", "global environment"],
  "target_api": [],
  "target_path": [],
  "expected_behavior": "只复述 Issue 明确行为",
  "oracle_strategy": "exception|warning|return_value|state_change|query_string|render_output|public_property|format_string|type_property",
  "why_this_should_trigger": "",
  "risk": "low|medium|high",
  "fallback_if_buggy_pass": "",
  "fallback_if_fixed_fail": ""
}}

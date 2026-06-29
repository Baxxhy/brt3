根据 Issue 目标、单一 seed 和测试协议生成一个小变异计划。最多选择 3 个 selected_rules；不得重写无关 setup，不得编造 expected value。
这是 seed mutation / trigger planning 阶段，只允许规划输入、参数、状态、配置、调用链、生命周期或 fixture 数据的小变异。
禁止在本阶段选择 ORACLE_REBIND；断言重绑定只能在 strict verifier 明确给出 oracle_wrong、oracle_too_strong 或 assertion_mismatch 后，由 observation oracle 阶段单独执行。
如果 buggy PASS 或 target_not_hit，必须加强 trigger；不要改 oracle。
如果 fixed fail，当前阶段只记录 fallback_if_fixed_fail，不能直接把 oracle 规则放进 selected_rules。

BehaviorTarget：{behavior_json}
HostContext：{host_context_json}
ProtocolRecovery：{protocol_json}
可用 BRT mutation rules：{mutation_rules_json}
聚合 mutation prior（只表示 repo/issue_pattern/rule 的历史风险，不包含当前 instance 特判）：{analysis_prior_hint}
上一轮执行反馈：{execution_feedback}
Verifier 反馈：{verifier_feedback}

如果 buggy PASS 或 target_not_hit，优先 CALL_CHAIN_EXTEND、LIFECYCLE_TRIGGER、CONFIG_MUTATION。
如果已进入目标 API 但仍 PASS，优先 ARG_BOUNDARY_EXPAND、ARG_VALUE_REPLACE、OPERATOR_FLIP、STATE_MUTATION、FIXTURE_DATA_MUTATION。
如果 oracle 可疑，不要继续扩大 trigger。

只输出：
{{
  "mutation_goal": "",
  "issue_pattern": "boundary|null_empty|exception|warning|configuration|lifecycle|cache_state|serialization|query_sql|repr_string_format|dtype_shape|parser_render|io_path|api_call_chain|unknown",
  "selected_rules": [
    {{
      "rule": "ARG_BOUNDARY_EXPAND",
      "target_code": "",
      "seed_element": "",
      "mutation": "",
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
  "mutation_ops": [],
  "expected_behavior": "只复述 Issue 明确行为",
  "oracle_strategy": "exception|warning|return_value|state_change|query_string|render_output|public_property|format_string|type_property",
  "why_this_should_trigger": "",
  "risk": "low|medium|high",
  "fallback_if_buggy_pass": "",
  "fallback_if_fixed_fail": ""
}}
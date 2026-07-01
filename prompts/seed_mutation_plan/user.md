根据 Issue 目标、单一 seed、HostScaffold、测试协议和候选算子生成一个锚定小变异计划。最多选择 2 个 selected_operators、2 个 mutation_targets 和 2 个兼容 selected_rules；不得重写无关 setup，不得编造 expected value。
这是 seed mutation / trigger planning 阶段，只允许规划输入、参数、状态、配置、调用链、生命周期或 fixture/mock 数据的小变异。
禁止在本阶段选择 ORACLE_REBIND；断言重绑定只能在 strict verifier 明确给出 oracle_wrong、oracle_too_strong 或 assertion_mismatch 后，由 observation oracle 阶段单独执行。

BehaviorTarget：{behavior_json}
HostContext：{host_context_json}
HostScaffold（before_pattern 的唯一事实来源）：{host_scaffold_json}
ProtocolRecovery：{protocol_json}
ProtocolContextAudit：{protocol_context_audit_json}
CandidateOperators（只能从这里选择 rule 和 recommended_subtypes，allowed_scope 必须为 trigger）：{candidate_operators_json}
聚合 mutation prior（只表示 repo/issue_pattern/rule 的历史风险，不包含当前 instance 特判）：{analysis_prior_hint}
上一轮执行反馈：{execution_feedback}
Verifier 反馈：{verifier_feedback}

规划约束：
1. selected_rules 必须改变输入、参数、状态、调用链、配置、lifecycle 或 fixture/mock 数据。
2. 每个 mutation_target 和对应 selected_rule 必须包含相同、具体且彼此不同的 before_pattern 和 after_pattern；before_pattern 必须逐字来自 HostScaffold 对应 anchor_scope，且应短小、唯一。
3. 禁止使用“change input”、“modify assertion”、“strengthen test”等空泛表达；必须指出 seed 中哪个元素从什么改成什么。
4. 如果上一轮 Buggy PASS 或 target_not_hit，说明上一轮为何未触发，并选择更强 trigger；优先 CALL_CHAIN_EXTEND、LIFECYCLE_TRIGGER、ARG_BOUNDARY_EXPAND、STATE_MUTATION，不得改 oracle。
5. 如果上一轮 UNRELATED_FAIL，说明如何收紧 target_api 和 seed_element，避免 off-target failure。
6. 如果上一轮是 SETUP_ERROR、COLLECT_ERROR 或 SYNTAX_ERROR，保持 seed protocol，不扩大 trigger，优先让 setup/protocol repair 生效。
7. 如果已经 ISSUE_ALIGNED_FAIL，保持 trigger 最小；oracle 不稳时留给后续 observation oracle。
8. 对 query_sql、repr_string_format、serialization、parser_render、io_path、warning，优先使用可观察公开行为的 oracle_strategy。
9. fault_proxy 只能概括 Issue 中的触发前提、buggy 行为、fixed 行为和公开可观察症状，不得引入 golden patch/test 信息。
10. implementation_mode 只能是 deterministic_ast、llm_edit、hybrid、observation_only；trigger planning 不得使用 observation_only。
11. ast_feasibility 只能是 none、partial、high。
12. anchor_scope 只能是 seed_function_body、setup、fixture、call_chain、assertion。优先 seed_function_body；setup 只允许 CONFIG_MUTATION/FIXTURE_DATA_MUTATION，fixture 只允许 fixture/argument 类算子。
13. after_pattern 只能是局部 Python 片段，不得包含完整测试文件、import、class/def wrapper、fixture 参数删除、setup/teardown 定义。
14. 禁止 assert True、无条件 skip/xfail、pytest.raises(Exception)、吞异常、无关 sleep。
15. oracle_strategy 不会被 Generator 自动翻译成代码。若第一个 target 改变输入或返回值形状，使 seed 原断言不再对应 expected fixed behavior，必须增加第二个 anchor_scope="assertion" 的 mutation_target；before_pattern 必须来自 seed 原断言，after_pattern 只能表达 BehaviorTarget 明确支持的 expected behavior。

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
  "selected_operators": [
    "ARG_VALUE_REPLACE|ARG_BOUNDARY_EXPAND|OPERATOR_FLIP|CALL_CHAIN_EXTEND|STATE_MUTATION|CONFIG_MUTATION|LIFECYCLE_TRIGGER|FIXTURE_DATA_MUTATION"
  ],
  "mutation_targets": [
    {{
      "operator": "",
      "anchor_scope": "seed_function_body|setup|fixture|call_chain|assertion",
      "before_pattern": "",
      "after_pattern": "",
      "target_api": "",
      "expected_buggy_symptom": ""
    }}
  ],
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
  "preserve_constraints": [
    "不要修改 imports",
    "不要删除 fixtures",
    "不要修改 class wrapper",
    "不要改变 runner/nodeid",
    "只在 seed function body 或指定 anchor 内变异"
  ],
  "do_not_change": ["test framework", "unrelated fixtures", "global environment"],
  "target_api": [],
  "target_path": [],
  "expected_behavior": "只复述 Issue 明确行为",
  "oracle_strategy": {{
    "observation_points": [],
    "assertion_goal": "",
    "preferred_assertion_style": "exception|warning|return_value|state_change|query_string|render_output|public_property|format_string|type_property",
    "avoid": ""
  }},
  "why_this_should_trigger": "",
  "risk": "low|medium|high",
  "fallback_if_buggy_pass": "",
  "fallback_if_fixed_fail": "",
  "anchor_seed_used": "icore_0|icore_1|icore_2",
  "reference_seeds_used": ["icore_0"],
  "borrowed_elements": [
    "从 reference seed 借用的 API usage / object construction / boundary value / assertion style"
  ],
  "mutated_elements": [
    "anchor seed 中被改变的输入、状态、调用链或断言片段"
  ],
  "issue_alignment": "说明该变异如何对齐 Issue trigger 和 expected behavior",
  "buggy_expected_behavior": "buggy 版本预期表现",
  "fixed_expected_behavior": "fixed 版本预期表现",
  "oracle_plan": "断言或观测计划"
}}

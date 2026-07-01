请分析下面这个缺陷复现任务。

你的任务是把原始 Issue、iCoRe 检索源码片段、iCoRe 检索测试片段压缩成一个高密度 BehaviorTarget。

BehaviorTarget 的作用：
它不是测试代码，不是真实修复补丁，也不是最终 oracle。
它是后续 seed selection、mutation plan、BRT generation、observation oracle 和 strict verifier 使用的结构化行为目标。
后续模块会基于它选择 seed、生成变异计划、插入观测点、生成断言和判断失败是否与 Issue 对齐。

输入说明：
1. issue_text：
   原始 GitHub Issue 文本。它可能包含问题描述、错误日志、代码片段、期望行为或复现步骤。
   你只能从中提取 Issue 明确表达或可合理支持的信息。

2. code_context：
   iCoRe 检索出的相关源码片段，通常是函数级、类级或对象级片段，可能包含文件路径、对象名、行号范围和代码。
   它不一定是完整源码文件。
   你可以用它识别真实 API 名称、相关源码位置、公开行为和可能的缺陷路径。
   不要假设没有出现的源码逻辑。

3. test_context：
   iCoRe 检索出的相关测试片段，通常是测试函数级片段，可能包含测试文件、测试名、fixture、TestCase、imports、对象构造、API 调用和断言风格。
   它不一定是完整测试文件。
   你可以用它提取 seed 线索、可复用测试模式、setup 线索和可能的变异 gap。
   不要把这里的测试片段当成完整测试协议；完整 imports、fixture、class setup 和相邻测试会由后续 HostContext 阶段恢复。

核心要求：
1. 不要复述 original_issue，原始 Issue 会由 InstanceContext 单独保留。
2. 不要输出 evidence、reason、confidence、facts_from_issue、facts_from_retrieved_context、inferences、do_not_assume。
3. 不要复制大段源码或测试代码。
4. 不要生成测试代码。
5. 不要使用 patched version、golden patch、golden test、test_patch、FAIL_TO_PASS、PASS_TO_PASS 信息。
6. 所有字段必须基于原始 Issue、检索源码或检索测试，不能编造。
7. target_apis.name 必须是真实代码中可匹配的代码标识符或 dotted identifier，例如 get_foo、QuerySet.filter、ValueError。可以包含点号，但禁止括号、参数、中文、空格或自然语言描述。
8. 如果只能描述模糊缺陷位置，不要写进 target_apis.name，应写入 suspected_bug_locations。
9. expected_behavior 必须是根据 Issue 推出的修复后期望正向语义，不能复述 buggy 行为，也不能假设真实 patch 的具体实现。
10. assertion_hints 的极性必须与 expected_behavior 一致。
11. 如果修复后应正常执行，不要建议 raises。
12. 如果修复后应存在、支持、包含、更新或保持某种行为，不要建议 not hasattr、not in 或“保持缺失”。
13. 只有当 expected_behavior 明确是“某个错误片段、错误状态或错误输出不应出现”时，才允许建议 not_contains_fragment。
14. 如果 Issue 没给出完整精确字符串，不要猜完整 patched 输出，只提取稳定片段、类型、关系或公开行为。
15. SQL、repr、HTML、serialization、file output 等场景，优先建议稳定片段、类型、关系或 before/after 关系，避免完整字符串相等。
16. 优先检查 public behavior，不要建议检查私有字段、内部缓存或实现细节。
17. observation_points.expression_hint 必须是短小、高容错的公开行为观察表达式，例如 str(query)、type(result).__name__、len(result)、warnings、return_value、public_attr、file_bytes。禁止输出大段复合逻辑代码。
18. 输出必须是单个合法 JSON 对象，能被 Python 的 json.loads 直接解析。
19. 输出总长度必须控制在 4096 字符以内。
20. 不要把下面 schema 中的说明文字原样输出，要根据当前 Issue 填写具体内容。

字段含义说明：
- issue_summary：给后续模块快速理解任务目标的一句话摘要。
- clarified_issue：把原始 Issue 改写成更清楚的复现描述，但不能加入无依据事实。
- trigger_condition：描述测试应该如何触发 bug，给 mutation plan 和 test generation 使用。
- error_symptom：描述 buggy version 上应该出现的错误现象，给 verifier 判断 issue-aligned failure 使用。
- expected_behavior：描述修复后应该成立的正向语义，给 oracle 和 fixed-pass 判断使用。
- target_apis：后续测试可能需要直接调用或覆盖的真实 API 名称。
- suspected_bug_locations：可能相关的源码位置；只作为定位线索，不代表真实修复位置。
- related_test_seeds：从检索测试片段中提取的 seed 候选线索，不是最终 seed 选择结果。
- mutation_hints：从相似测试或正常路径变异到缺陷触发路径的建议。
- observation_points：后续 probe 测试应观察的公开运行时行为。
- assertion_hints：最终断言应验证的语义目标和推荐断言风格。
- setup_hints：从检索测试或源码中看到的测试运行上下文线索，不代表完整环境恢复结果。
- uncertainties：仍需后续通过执行、插桩或 seed 恢复确认的信息。

====================
【原始 Issue】

{issue_text}

====================
【iCoRe 检索出的相关源码片段】

{code_context}

====================
【iCoRe 检索出的相关测试片段】

{test_context}

====================

请只输出一个合法 JSON 对象，字段必须严格如下：

{{
  "issue_summary": "一句话概括 Issue 核心问题，不超过 120 字。",

  "clarified_issue": {{
    "text": "更清楚的缺陷复现描述，包含触发条件、错误现象、期望行为、可能相关 API 或文件。不能引入无依据事实，不超过 450 字。"
  }},

  "trigger_condition": {{
    "text": "后续测试可执行的触发条件：输入、参数、对象状态、配置、API 调用链或操作步骤。不超过 280 字。"
  }},

  "error_symptom": {{
    "text": "buggy 版本上观察到的错误表现，例如异常类型、warning 缺失、返回值错误、SQL 片段错误、顺序错误、状态未更新等。不超过 180 字。",
    "symptom_type": "exception|warning|wrong_return|wrong_type|wrong_sql|wrong_order|state_not_updated|serialization_error|performance|unknown"
  }},

  "expected_behavior": {{
    "text": "根据 Issue 推出的修复后正向语义，例如应该成功、应该包含、应该 warning、应该保持顺序、应该更新状态、应该不崩溃等。不超过 220 字。"
  }},

  "target_apis": [
    {{
      "name": "真实存在的代码标识符或 dotted identifier，禁止括号、参数、中文、空格。",
      "kind": "function|method|class|module|unknown",
      "source_path": "源码路径；不知道则为空字符串。"
    }}
  ],

  "suspected_bug_locations": [
    {{
      "path": "相关源码文件路径。",
      "object": "相关函数、类或方法名；无法确定则为空字符串。"
    }}
  ],

  "related_test_seeds": [
    {{
      "test_name": "检索测试片段中的相关测试名称；不知道则为空字符串。",
      "test_file": "检索测试片段中的相关测试文件路径；不知道则为空字符串。",
      "reusable_parts": ["最多 5 个可复用部分，例如 imports、fixture、class setup、object construction、assert style。"],
      "possible_gap": "相似测试与当前 Issue 之间最需要变异的差异，例如参数、边界值、调用链、配置或对象状态。不超过 160 字。"
    }}
  ],

  "mutation_hints": [
    {{
      "slot": "input|argument|object_state|mock|config|call_chain|operator|boundary_value|unknown",
      "suggested_operator": "ARG_VALUE_REPLACE|ARG_BOUNDARY_EXPAND|OPERATOR_FLIP|CALL_CHAIN_EXTEND|STATE_MUTATION|CONFIG_MUTATION|LIFECYCLE_TRIGGER|FIXTURE_DATA_MUTATION|UNKNOWN",
      "current_pattern": "相似测试或正常路径中的已有模式。不超过 100 字。",
      "target_pattern": "根据 Issue 需要变异成的触发模式，必须是具体输入、参数、状态、配置、fixture 或调用链变化。不超过 150 字。"
    }}
  ],

  "observation_points": [
    {{
      "kind": "exception|warning|return_value|type|repr|str|sql|order|state|cache|config|file_output|serialization|unknown",
      "expression_hint": "短小、高容错的公开行为观察表达式，例如 str(query)、type(result).__name__、len(result)、warnings、return_value、public_attr、file_bytes。"
    }}
  ],

  "assertion_hints": [
    {{
      "assertion_goal": "最终 assert 应验证的语义目标，必须与 expected_behavior 极性一致。不超过 180 字。",
      "preferred_assertion_style": "contains_fragment|not_contains_fragment|equals|isinstance|raises|warns|before_after_relation|order_equals|unknown",
      "avoid": "需要避免的脆弱断言，例如完整 SQL、完整 repr、完整 HTML、私有字段、内部缓存、无关数量、过强 warning message。不超过 140 字。"
    }}
  ],

  "setup_hints": [
    {{
      "hint": "运行测试可能需要的上下文线索，例如 pytest fixture、Django TestCase、settings、database、tmp_path、monkeypatch、mock、临时文件、项目 runner。",
      "source": "issue|retrieved_test|retrieved_source|inference"
    }}
  ],

  "uncertainties": [
    "最多 3 条仍需后续通过运行相似测试或插桩观测确认的关键不确定点。"
  ]
}}

额外限制：
1. target_apis 最多 5 个。
2. suspected_bug_locations 最多 3 个。
3. related_test_seeds 最多 3 个。
4. mutation_hints 最多 5 个。
5. observation_points 最多 3 个。
6. assertion_hints 最多 3 个。
7. setup_hints 最多 3 个。
8. uncertainties 最多 3 个。
9. 如果没有足够依据，填空数组、空字符串或 unknown。
10. 不要为了填满字段而编造信息。
11. 不要输出 JSON 之外的任何内容。
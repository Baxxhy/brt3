请对下面这个 BRT 生成实例做协议上下文审计。

注意：静态 ProtocolRecovery 已经完成。你不能替代静态抽取结果，也不能重写事实字段。你只能补充 audit hints，用于指导后续 Mutation Plan、Candidate BRT Generation、repair_setup、repair_trigger、repair_oracle 和 Strict Verifier。

====================
【BehaviorTarget：结构化行为目标】
{behavior_json}

====================
【Selected ProtocolRecovery：静态恢复出的测试协议】
{protocol_json}

====================
【Selected Seed Test：当前选中的种子测试】
{selected_seed_test}

====================
【Top-k Related Tests：iCoRe 检索到的相关测试】
{related_tests_context}

====================
【Retrieved Source：iCoRe 检索到的相关源码】
{source_context}

====================

请只输出一个合法 JSON 对象，字段必须严格如下：

{{
  "audit_summary": "用一两句话总结当前 seed protocol 是否适合后续生成 BRT，以及主要风险是什么。",

  "selected_seed_role": {{
    "role": "primary_seed|setup_reference|oracle_reference|trigger_reference|weak_seed|unknown",
    "reason": "说明当前 selected seed 更适合作为什么角色。"
  }},

  "protocol_risks": [
    {{
      "risk": "协议风险描述，例如 fixture 来源不明、HTTP 层上下文过重、class setup 复杂、runner 约束强、目标 API 不是直接调用等。",
      "severity": "high|medium|low",
      "evidence": "来自 ProtocolRecovery、seed test、related tests 或 source 的依据。",
      "recommended_action": "后续生成或修复时应该如何规避。"
    }}
  ],

  "do_not_merge": [
    {{
      "source": "说明来自哪个 related test、fixture、class、setup、runner 或文件。",
      "reason": "为什么不能和 selected seed protocol 混合。",
      "risk_if_merged": "如果混合可能导致什么问题，例如 fixture 冲突、runner 错误、Django settings 错误、上下文污染。"
    }}
  ],

  "reusable_patterns_from_related_tests": [
    {{
      "test_name": "相关测试名。",
      "test_file": "相关测试文件。",
      "reusable_pattern": "可以借鉴的模式，例如断言风格、对象构造、目标 API 调用、异常/警告捕获、文件读写方式。",
      "how_to_reuse_safely": "如何在不混合不兼容 setup 的前提下安全复用这个模式。",
      "relevance_to_issue": "为什么这个模式和 BehaviorTarget 对齐。"
    }}
  ],

  "source_behavior_constraints": [
    {{
      "constraint": "从 retrieved source 中得到的行为约束，例如必须调用某个 public API、必须触发 lazy evaluation、必须构造特定对象状态。",
      "evidence": "来自源码片段或 BehaviorTarget 的依据。",
      "impact_on_mutation": "对后续 mutation plan 的影响。"
    }}
  ],

  "generation_constraints": [
    "后续 Candidate BRT Generation 必须遵守的约束，例如保留 selected seed 的 class wrapper，不要引入其他文件 fixture，不要改 runner，不要走 HTTP 层而应直接调用目标 API。"
  ],

  "mutation_plan_hints": [
    {{
      "hint": "给 Mutation Plan 的建议，例如应该修改输入、参数、对象状态、配置、调用链、生命周期触发。",
      "mutation_type": "input|argument|object_state|mock|config|call_chain|operator|boundary_value|fixture_data|lifecycle|unknown",
      "why": "为什么这个变异更可能触发 issue bug path。"
    }}
  ],

  "oracle_hints": [
    {{
      "oracle_goal": "最终断言应该验证的语义目标。",
      "preferred_observation": "建议观察的 public behavior，例如 return value、exception、warning、file_output、SQL fragment、serialization output。",
      "avoid": "应该避免的脆弱断言或无关断言。",
      "reason": "为什么这个 oracle 和 expected_behavior 对齐。"
    }}
  ],

  "setup_notes": [
    {{
      "note": "关于 imports、fixtures、class wrapper、setup、runner 的注意事项。",
      "source": "protocol|selected_seed|related_tests|source|inference",
      "confidence": "high|medium|low"
    }}
  ],

  "alternative_seed_notes": [
    {{
      "test_name": "如果某个 related test 看起来更适合做 trigger/oracle 参考，在这里说明。",
      "test_file": "测试文件路径。",
      "why_not_selected_protocol": "为什么不建议直接替代 selected seed 的协议，或者为什么只作为参考。",
      "use_as": "setup_reference|oracle_reference|trigger_reference|not_recommended"
    }}
  ],

  "strict_verifier_focus": [
    "Strict Verifier 后续应该重点检查什么，例如是否命中 target API、失败是否为 issue-aligned、oracle 是否来自 expected_behavior、是否检查 public behavior。"
  ],

  "uncertainties": [
    "当前仍然不确定、需要后续执行、插桩或 verifier 判断的信息。"
  ]
}}

规则：
1. 所有字段都必须出现；
2. 如果没有内容，填写空数组或 unknown；
3. 不要输出 JSON 之外的任何文字；
4. 不要生成测试代码；
5. 不要重写 ProtocolRecovery 的 imports、fixtures、test_command、placement_dir；
6. 不要把多个 related tests 的 setup、fixture、class、runner 混合成一个虚假的协议；
7. 可以借鉴其他 related tests 的对象构造、调用模式、assert 风格，但必须说明如何安全复用；
8. 如果 selected seed 是 HTTP/view/template 层测试，而 BehaviorTarget 更适合直接 API 调用，要明确写入 generation_constraints 和 mutation_plan_hints；
9. 如果 selected seed 协议适合保留，但 trigger path 不够直接，要说明后续 mutation plan 应该如何缩短路径；
10. 输出必须能被 Python 的 json.loads 直接解析。

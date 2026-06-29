# Mutation-Plan-Guided BRT Generation with Semantic Verification

中文名称：语义约束的计划式种子变异 BRT 生成方法

## 1. 问题定义

给定 issue 描述、iCoRe 检索得到的相关源码和相关测试，以及 buggy 版本仓库，目标是生成一个完整测试文件，使其满足：

```text
buggy version: Fail
patched/fixed version: Pass
```

生成阶段不能读取真实 patch、golden patch、test_patch、FAIL_TO_PASS 或 PASS_TO_PASS。真实 patch 只用于最终独立 formal F2P 评测。

## 2. 总体框架

当前代码实现的主流程为：

```text
Instance Context Construction
→ Issue-to-Behavior Target
→ Seed Selection
→ Host Context Recovery
→ Protocol Recovery
→ Explicit Mutation Plan
→ Candidate BRT Generation
→ Environment Qualification
→ Buggy Execution and Feedback Repair
→ Observation-Oriented Oracle Rebinding
→ Strict Semantic Verification
→ Surrogate F2P Validation
→ Candidate Scoring and Selection
```

关键代码证据：

- `context/issue_rewriter.py`
- `context/host_context.py`
- `context/protocol_recovery.py`
- `mutation/seed_mutator.py`
- `mutation/brt_mutation_rules.py`
- `generation/generator.py`
- `execution/feedback.py`
- `oracle/observation_oracle.py`
- `validation/strict_semantic_verifier.py`
- `patching/patch_utils.py`
- `evaluation/direct_eval.py`

## 3. 模块 1：Issue-to-Behavior Target

### 输入

- issue 原文；
- top-k retrieved source snippets；
- top-k retrieved related tests。

### 处理

`context/issue_rewriter.py` 调用模型，将自然语言 issue 和检索上下文转换为结构化 `BehaviorTarget`。字段包括：

- `issue_summary`
- `trigger_condition`
- `error_symptom`
- `expected_behavior`
- `target_apis`
- `suspected_bug_locations`
- `related_test_seeds`
- `mutation_hints`
- `observation_points`
- `assertion_hints`
- `setup_hints`
- `uncertainties`

解析结果会保存为：

```text
behavior_target.json
enhanced_issue.json
enhanced_issue.txt
```

### 输出

结构化行为目标，用于 seed 评分、mutation plan、verifier 和 oracle 构造。

## 4. 模块 2：Context and Seed Test Recovery

### 输入

- retrieved related tests；
- BehaviorTarget；
- buggy worktree；
- repo/version runner 信息。

### 处理

`context/host_context.py` 对相关测试排序并选择主 seed。评分规则包括：

- 如果测试文件被 `related_test_seeds.test_file` 推荐：加 `100 - rank`；
- 如果测试名被 `related_test_seeds.test_name` 推荐：加 `80 - rank`；
- 每命中一个 target API 名称：加 8；
- 有文件和代码：加 2；
- 同分时保留 iCoRe 原始检索顺序靠前者。

随后系统读取完整测试文件，恢复：

- imports；
- pytestmark；
- decorators；
- fixtures；
- class wrapper；
- setup/teardown；
- 相邻测试；
- 本地 model context；
- 项目测试命令。

### 输出

`HostContext`，包含 seed test、测试命令、执行状态和放置策略。新 BRT 默认生成在 seed test 同级目录，而不修改原测试文件。

## 5. 模块 3：Protocol Recovery

### 输入

- selected seed test；
- buggy worktree；
- BehaviorTarget；
- related source。

### 处理

`context/protocol_recovery.py` 使用 AST 和本地文件分析恢复更细的测试协议，包括：

- `test_framework`：pytest / unittest / django / unknown；
- imports；
- fixtures；
- pytest marks；
- decorators；
- class context；
- setup/teardown methods；
- conftest fixture definitions；
- local helpers；
- local models；
- runner hints；
- protocol risks。

该模块尽量使用本地静态分析；模型 audit 只用于补充风险识别。

### 输出

`protocol_recovery.json`，作为后续生成和修复 prompt 的约束。

## 6. 模块 4：Mutation-Plan-Guided Test Generation

### 输入

- BehaviorTarget；
- HostContext；
- ProtocolRecovery；
- analysis prior；
- execution feedback；
- verifier feedback。

### 处理

`mutation/seed_mutator.py` 先生成显式 mutation plan，再由 `generation/generator.py` 根据 plan 写完整 BRT。当前 mutation rule taxonomy 位于 `mutation/brt_mutation_rules.py`，包含：

- `ARG_VALUE_REPLACE`
- `ARG_BOUNDARY_EXPAND`
- `OPERATOR_FLIP`
- `CALL_CHAIN_EXTEND`
- `STATE_MUTATION`
- `CONFIG_MUTATION`
- `LIFECYCLE_TRIGGER`
- `FIXTURE_DATA_MUTATION`
- `ORACLE_REBIND`

其中 seed mutation / trigger repair 阶段只允许 trigger rules；`ORACLE_REBIND` 被排除在 trigger planning 之外，只在 verifier 明确诊断 oracle 问题后由 observation oracle 处理。

Mutation plan 包含：

- `mutation_goal`
- `issue_pattern`
- `selected_rules`
- `preserve_from_seed`
- `do_not_change`
- `target_api`
- `target_path`
- `mutation_ops`
- `expected_behavior`
- `oracle_strategy`
- `why_this_should_trigger`
- `risk`
- `fallback_if_buggy_pass`
- `fallback_if_fixed_fail`

### 输出

- `mutation_round_<n>_plan.json`
- `candidate_round_<n>.py`
- `mutation_round_<n>_test.py`

## 7. 模块 5：Seed Mutation

当前方法约束模型不要从零自由重写测试，而是保留 seed 的可执行协议，只修改与 issue 触发条件相关的局部要素：

- 输入值；
- 参数；
- 对象状态；
- mock 行为；
- 配置；
- 调用链；
- 边界条件；
- operator；
- fixture 数据。

该设计把 related test 作为路径锚点，降低生成测试不可执行或偏离目标 API 的风险。

## 8. 模块 6：Execution-Feedback Repair

### 输入

- 候选 BRT；
- buggy worktree；
- Conda 环境；
- BehaviorTarget；
- HostContext；
- ProtocolRecovery。

### 处理

系统先运行候选测试。`execution/executor.py` 将执行结果分类为：

- `PASS`
- `SETUP_ERROR`
- `SYNTAX_ERROR`
- `COLLECT_ERROR`
- `ASSERTION_FAIL`
- `ISSUE_ALIGNED_FAIL`
- `UNRELATED_FAIL`
- `TIMEOUT`

反馈修复分三类：

- `repair_setup`：只修 imports、fixtures、class wrapper、setup、runner；
- `repair_trigger`：只修输入、参数、状态、配置、调用链、生命周期触发；
- `repair_oracle`：进入 observation oracle，只改观测对象和断言。

### 输出

每轮保存执行日志、verifier 输出、修复 prompt/response 和候选 checkpoint。

## 9. 模块 7：Observation-Oriented Oracle Rebinding

### 输入

- 当前候选测试；
- 执行失败日志；
- BehaviorTarget.expected_behavior；
- ProtocolRecovery。

### 处理

`oracle/observation_oracle.py` 先生成 probe test，在 buggy 上运行并收集公开行为。probe 输出固定标记：

```text
BRT_OBS_START
<JSON>
BRT_OBS_END
```

可观测内容包括：

- exception；
- warning；
- return value；
- repr/str；
- SQL/query；
- object state；
- cache/config；
- serialization；
- before/after state。

之后模型根据 observation 和 expected behavior 重写断言。代码中对 observation、execution log、raw output 进行截断，避免把大日志直接塞回 prompt。

### 输出

- `oracle_round_<n>_probe.py`
- `oracle_round_<n>_observation.json`
- `oracle_round_<n>_rebuilt_test.py`

## 10. 模块 8：Strict Semantic Verification

### 输入

- issue 原文；
- BehaviorTarget；
- ProtocolRecovery；
- 候选测试；
- buggy 执行结果；
- 相关源码上下文。

### 处理

`validation/strict_semantic_verifier.py` 先做本地强规则过滤：

- setup/syntax/collect/timeout；
- buggy pass；
- `assert True`；
- 无条件 skip；
- `pytest.raises(Exception)`；
- broad try/except 吞异常；
- 恒真断言；
- 完整 SQL/repr/长字符串的脆弱断言；
- 私有属性/内部缓存断言；
- expected behavior 与 oracle 极性不一致。

只有非机械错误且需要语义判断时，才调用模型输出结构化结果：

- `decision`
- `failure_class`
- `target_hit`
- `oracle_grounded_in_issue`
- `uses_public_behavior`
- `reason`
- `next_action`

accept 必须同时满足 buggy fail、非环境错误、target hit、oracle 来自 issue 且检查公开行为。

### 输出

- `strict_verifier_round_<n>.json`
- `verifier_round_<n>.json`

## 11. 模块 9：Surrogate Fail-to-Pass Validation

### 输入

- 语义验证接受的候选 BRT；
- buggy 失败日志；
- retrieved source；
- suspected source locations。

### 处理

`patching/patch_utils.py` 生成少量 search/replace surrogate patch，在临时仓库副本中应用，然后运行同一个 BRT。生成阶段不读取真实 patch。

如果 surrogate patch 后测试通过，则该候选获得更高排序分数。当前主循环中 surrogate patch 被记录为 ranking signal，不能代替真实 F2P。

### 输出

`dual_version_result.json` 或 candidate validation 目录中的 surrogate patch 结果。

## 12. 模块 10：Candidate Scoring and Selection

`execution/feedback.py` 中 `_checkpoint_score()` 定义候选分数：

- 300：buggy fail 且 surrogate patched pass，且 strict verifier 接受；
- 200：buggy fail 且 semantic verifier 接受；
- 100：buggy fail，但未被语义接受且非环境类失败；
- 10：buggy pass；
- 0：setup/syntax/collect/timeout 等不可执行候选。

最终选择最高分 checkpoint；同分时保留较早候选。

## 13. 当前方法的设计动机

当前方法相比纯生成式 BRT 更强调：

1. 将自然语言 issue 转换为结构化行为目标；
2. 把 related test 当作可执行路径种子；
3. 用显式 mutation plan 限制模型修改范围；
4. 用 buggy 执行反馈区分 setup、trigger、oracle 问题；
5. 用 observation oracle 纠正断言对象和断言强度；
6. 用 strict verifier 拒绝伪失败；
7. 用 surrogate patch 在无真实 patch 的生成阶段提供近似排序信号。

## 14. 当前不确定点

- 当前代码仍在运行中的最新 run 尚未完成 formal F2P，因此本文档不声称当前方法的最终 F2P。
- 当前代码中 `HostContext.seed_execution` 仍可能保存超长执行日志；mutation plan prompt 已做截断，但更彻底的设计应将完整日志和 prompt context 分层保存。

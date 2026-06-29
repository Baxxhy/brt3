# Method Comparison

| 维度 | 旧方法：F2P≈45% | 新方法：当前版本 |
| --- | --- | --- |
| 方法定位 | 检索增强的执行反馈式 BRT 生成。重点是利用 iCoRe 检索结果、真实 buggy 执行反馈和 surrogate patch 排序。 | 语义约束的计划式种子变异 BRT 生成。重点是把 issue 结构化、显式 mutation plan、observation oracle 和 strict verifier 接入反馈链。 |
| 对应证据 | `/root/Baxxhy/BugReproduce/brt3/results/runs/run_20260624_refactor_deepseek7`；`evaluation/metrics.json` 显示 `125/276`。 | 当前源码：`context/issue_rewriter.py`、`mutation/seed_mutator.py`、`oracle/observation_oracle.py`、`validation/strict_semantic_verifier.py`、`execution/feedback.py`。 |
| issue 理解 | 根据 run 配置启用了 issue rewrite，但历史代码快照不确定；可确认会读取 issue + retrieved code/tests。 | 明确生成 `BehaviorTarget`，包含 trigger、symptom、expected behavior、target APIs、mutation hints、observation points、assertion hints 等字段。 |
| 相关测试使用 | 使用 related tests 恢复测试上下文，并生成同级新测试文件。 | 先对 related tests 评分，选择唯一主 seed；恢复 HostContext 和 ProtocolRecovery，不合并多个 seed 的 setup。 |
| Seed Selection | 从结果配置看使用 seed/context；具体当时评分实现需旧 commit 确认。 | 明确基于推荐文件、推荐测试名、target API 命中和检索顺序打分。 |
| 是否有显式 mutation plan | run manifest 显示 `seed_mutation=true`，但旧代码快照不确定。 | 有。`mutation_round_<n>_plan.json`，包含 issue pattern、selected rules、preserve/do-not-change、oracle strategy 等。 |
| 是否做 seed mutation | 是，至少从配置看启用。具体规则粒度需当时源码确认。 | 是。使用 trigger-only rule catalog 约束模型只改输入、状态、配置、调用链、边界值、operator 等。 |
| oracle 构造方式 | 使用模型生成/修复 oracle，并通过执行反馈和 verifier 纠正。 | observation-oriented oracle rebinding：先插桩观测公开行为，再根据 expected behavior 重写断言。 |
| 是否观测后重建断言 | 配置显示启用 observation oracle，但历史实现细节不确定。 | 明确实现于 `oracle/observation_oracle.py`，输出 probe、observation JSON 和 rebuilt test。 |
| verifier | 配置显示启用 strict semantic verifier。 | 两层 verifier：本地静态安全检查 + 必要时 LLM 语义判断；accept 条件包含 target hit、oracle grounded、public behavior。 |
| 执行反馈分类 | 分类 setup/syntax/collect/pass/assertion/issue-aligned/unrelated/timeout，并按类别修复。 | 同旧方法，并进一步把 repair_setup、repair_trigger、repair_oracle 的修改边界显式化。 |
| 双版本/代理验证 | 生成阶段使用 surrogate patch；真实 patch 只在 formal eval。 | 仍使用 surrogate patch，但在当前主循环中它被用作 ranking signal，不能替代真实 formal F2P。 |
| 候选选择 | 根据 run 配置和结果结构可确认存在 checkpoint/validation 思路；精确分数需旧代码确认。 | 明确打分：300 surrogate F2P + semantic accept；200 semantic accept；100 executable buggy fail；10 buggy pass；0 不可执行。 |
| 主要解决的问题 | 解决 LLM 直接生成测试时不可执行、无法触发、伪失败等问题。 | 进一步解决变异不可控、断言对象错误、oracle 过强、buggy pass 误判、无关失败误收等问题。 |
| 可能引入的新失败 | 若 seed/context 或 oracle 修复方向波动，会导致 fixed fail 或 buggy pass。 | 显式 mutation plan 和 strict verifier 增加复杂度，可能带来 prompt 过长、过度保守拒绝、oracle rebinding 误修复、运行成本增加。 |

## 关键结论

旧方法的 45% 结果可以可靠地定位到 `run_20260624_refactor_deepseek7`，但旧方法对应的完整代码版本未在结果目录中单独保存，因此不能把当前源码所有细节都归因给该 run。当前方法则可以从源码直接确认其新增机制，包括结构化 issue、protocol recovery、mutation rule taxonomy、observation oracle、strict verifier 和 checkpoint scoring。

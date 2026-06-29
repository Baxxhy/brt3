# Method Section Draft

## 1. Problem Formulation

本文研究 Bug Reproduction Test Generation 任务。给定一个缺陷报告、目标仓库的 buggy 版本，以及由检索器返回的相关源码片段和相关测试片段，目标是生成一个可独立执行的测试文件，使该测试在 buggy 版本上失败，并在修复版本上通过。形式化地，生成测试 `t` 需要满足：

```text
Exec(repo_buggy, t) = Fail
Exec(repo_fixed, t) = Pass
```

该性质称为 Fail-to-Pass，简称 F2P。生成阶段不使用真实修复补丁、golden test 或 benchmark 中的 FAIL_TO_PASS/PASS_TO_PASS 信息；真实 patch 仅用于最终独立评测。

## 2. Retrieval-Augmented Execution-Feedback Framework

旧版方法采用检索增强的执行反馈式 BRT 生成框架。系统输入包括 issue 文本、iCoRe 检索到的相关源码、iCoRe 检索到的相关测试、buggy 仓库 worktree 和项目对应的 Conda 测试环境。系统首先从相关测试中恢复测试协议，包括测试文件位置、导入、fixture、class wrapper、setup/teardown 和项目测试 runner。随后，系统生成一个完整的新测试文件，并将其放置在与最相似相关测试同级的测试目录中。

与只依赖静态生成不同，该框架将候选测试放到 buggy 版本上执行，并根据执行结果进行有限轮反馈修复。执行结果被划分为环境错误、语法错误、收集错误、buggy 上通过、断言失败、疑似 issue-aligned failure、无关失败和超时。若测试无法运行，系统修复测试协议和环境依赖；若 buggy 上通过，系统加强触发路径；若测试失败但失败原因不确定，系统通过语义验证器和 oracle 修复进一步判断该失败是否与 issue 对齐。

该方法的核心思想是：检索上下文提供可执行测试结构和目标 API 线索，真实执行反馈排除不可运行测试和无关路径，语义判定与 surrogate patch 验证进一步过滤伪失败。历史实验 `run_20260624_refactor_deepseek7` 在 276 个实例上取得 `125/276` 的 F2P 成功数，约为 45.29%。该结果说明，检索增强和执行反馈能够显著提高生成测试的可执行性和缺陷路径命中率。

TODO：该实验对应的完整代码 commit 未在结果目录中保存，旧方法的部分内部细节仍需结合历史代码确认。

## 3. Current Method Overview

当前方法在上述执行反馈框架上进一步引入计划式种子变异和观测式 oracle 重绑定。整体流程包括八个模块：

```text
Issue-to-Behavior Target
→ Context and Seed Test Recovery
→ Mutation-Plan-Guided Test Generation
→ Execution-Feedback Repair
→ Observation-Oriented Oracle Rebinding
→ Strict Semantic Verification
→ Surrogate Fail-to-Pass Validation
→ Candidate Scoring and Selection
```

该方法的中心假设是：相关测试虽然通常不能直接复现当前 bug，但它们提供了高价值的测试协议、对象构造和调用链。相比从零生成测试，更稳健的方式是选择一个最相关的 seed test，并在 issue 约束下对其进行小范围、可解释的变异。

## 4. Issue-to-Behavior Target

系统首先将自然语言 issue 与检索源码、检索测试对齐，生成结构化行为目标。行为目标包括缺陷摘要、触发条件、错误症状、预期行为、目标 API、疑似源码位置、可复用测试种子、变异线索、观测点、断言线索、setup 线索和不确定项。

该结构化表示有两个作用。第一，它将自然语言描述转化为后续模块可消费的中间语义，例如 target API 和 expected behavior。第二，它在执行反馈阶段为 verifier 和 oracle rebinding 提供判定标准，避免系统将任意 buggy fail 误判为有效 BRT。

## 5. Context and Seed Test Recovery

给定 iCoRe 返回的相关测试，系统选择一个主 seed test，而不是合并多个测试的 setup。选择规则综合考虑：该测试文件是否被 issue rewrite 推荐、测试名是否被推荐、测试代码中是否出现 target API，以及其在原检索列表中的排序。选定 seed 后，系统读取完整测试文件，并恢复 imports、pytestmark、decorators、fixtures、class wrapper、setup/teardown、相邻测试和本地 model/helper 上下文。

同时，系统基于项目和版本恢复测试运行命令。对于不同项目，runner 可能是 pytest、Django runtests、SymPy `bin/test` 或项目自定义命令。该设计避免把所有仓库强行统一为普通 pytest，从而提高测试可收集和可执行的概率。

## 6. Mutation-Plan-Guided Test Generation

当前方法不直接让模型自由生成最终测试，而是先生成显式 mutation plan。Mutation plan 描述本轮变异目标、issue pattern、选用的 mutation rules、保留 seed 的哪些部分、禁止修改的上下文、目标 API、预期行为和 oracle 策略。

系统定义了一组 BRT mutation rules，包括参数替换、边界扩展、operator 翻转、调用链延长、对象状态修改、配置修改、生命周期触发、fixture 数据修改和 oracle rebinding。其中 trigger planning 阶段只允许 trigger 类规则；oracle rebinding 仅在 verifier 明确指出 oracle 问题时触发。这样可以避免模型在尚未触发缺陷时过早修改断言。

基于 mutation plan，生成器输出一个完整的新 Python 测试文件。测试文件只包含一个可收集测试入口，放置在 seed test 同目录。生成 prompt 明确要求保留 seed 的可执行协议，只修改 issue 相关的输入、参数、状态、配置、调用链、边界值或 operator。

## 7. Execution-Feedback Repair

候选测试生成后，系统在 buggy worktree 中执行该测试。执行器根据返回码、stdout/stderr、超时和 issue 行为目标将结果分类。反馈修复分为三类：

- setup repair：修复 imports、fixtures、class wrapper、setup、pytestmark、runner 或项目配置；
- trigger repair：修复输入、参数、对象状态、mock、配置、调用链或生命周期触发；
- oracle repair：修复观测对象和断言，而尽量不改变 setup 和 trigger。

该反馈机制使系统能够逐步消除不可运行测试，并在 buggy pass 时加强缺陷触发路径。

## 8. Observation-Oriented Oracle Rebinding

当候选测试在 buggy 上失败但 verifier 判断 oracle 可能错误或过强时，系统进入观测式 oracle 重绑定。系统先生成 probe test，在目标调用周围插入观测点，并打印固定 JSON 标记。观测内容包括异常、warning、返回值、repr/str、SQL/query、对象状态、cache/config、序列化结果和 before/after state。

随后，系统根据 issue 中的 expected behavior 和 probe 收集到的公开行为重建断言。buggy observation 只用于选择观测对象和理解当前失败，不直接作为修复后期望值。该机制旨在缓解自然语言 expected behavior 到测试断言之间的语义割裂，减少 fixed fail 和过强断言。

## 9. Strict Semantic Verification

当前方法引入严格语义验证器。验证器首先执行本地静态检查，拒绝明显无效或脆弱的测试，例如 `assert True`、无条件 skip、`pytest.raises(Exception)`、宽泛 try/except 吞异常、恒真断言、完整 SQL/repr 长字符串相等、私有字段断言，以及与 expected behavior 极性相反的 oracle。

对于非机械错误，验证器调用模型判断候选失败是否真正与 issue 对齐。一个候选只有在 buggy 上失败、不是环境/语法/收集/超时错误、触达目标 API 或生命周期、失败症状与 issue 对齐、断言来自 expected behavior 且检查公开行为时，才会被接受。

## 10. Surrogate Fail-to-Pass Validation

生成阶段无法访问真实 patch，因此系统使用 surrogate patch 作为候选排序信号。对于 verifier 接受的候选，系统基于检索源码和失败日志生成少量 search/replace patch，在临时仓库副本中应用，并运行同一个 BRT。如果候选满足 buggy fail 且 surrogate patched pass，则说明该测试更可能刻画了可修复的缺陷行为。

需要强调的是，surrogate patch 不是真实 patch，不能用于报告最终 F2P；它只服务于生成阶段的候选排序。最终 F2P 指标仍由独立 formal evaluation 使用真实 benchmark patch 计算。

## 11. Candidate Scoring and Selection

系统在每轮反馈后保存 checkpoint，并为候选打分：

- 300：buggy fail 且 surrogate patched pass，并被 strict verifier 接受；
- 200：buggy fail 且被 semantic verifier 接受；
- 100：buggy fail 且非环境类错误，但未被语义接受；
- 10：buggy pass；
- 0：环境、语法、收集或超时错误。

最终选择最高分 checkpoint，同分时保留较早候选。该策略避免后续修复把已有较好候选覆盖掉。

## 12. Discussion

旧方法已经证明检索上下文和执行反馈对 BRT 生成有效。当前方法进一步将“相关测试复用”细化为计划式种子变异，将“失败即成功”的粗粒度判断替换为严格语义验证，并将断言生成改造成观测式 oracle 重绑定。这些设计针对 BRT 生成中的三个核心困难：测试协议恢复、缺陷路径迁移和 expected behavior 到 oracle 的转换。

当前方法也引入新的工程风险：模块更多、调用链更长、prompt 更复杂，若上下文未压缩可能出现 prompt 过长；若 verifier 过于保守，可能拒绝部分可用候选；若 oracle rebinding 判断错误，可能造成 fixed fail。因此，最终效果需要通过独立 formal F2P 评测验证，不能仅根据 surrogate patch 成功数判断。

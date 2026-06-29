# Retrieval-Augmented Execution-Feedback BRT Generation

中文名称：检索增强的执行反馈式 BRT 生成方法

## 1. 定位与证据

本节描述 F2P 约 45% 的旧版实验方法。对应结果目录为：

```text
/root/Baxxhy/BugReproduce/brt3/results/runs/run_20260624_refactor_deepseek7
```

可核验文件：

- `evaluation/metrics.json`：`total_instances=276`，`f2p_success=125`，即 `125/276=45.29%`。
- `run_config.json`：`model=deepseek-v3`，`temperature=0.1`，`max_workers=7`，`validation_mode=surrogate_patch`。
- `manifest.txt`：记录 generation/evaluation 命令，并显示 `max_env_rounds=3`、`max_brt_rounds=3`、`max_patch_rounds=3`，以及 `protocol_recovery=true`、`seed_mutation=true`、`observation_oracle=true`、`strict_semantic_verifier=true`。

不确定点：该目录保存了实验结果和配置，但没有单独保存当时的完整 Git commit 或源码快照。因此，下面的方法描述基于该 run 的配置、日志、结果结构，以及当前项目中同名模块的实现语义反推。若需要完全精确的历史实现，需要提供当时的 commit 或完整代码备份。

## 2. 问题定义

给定一个 issue、buggy 版本仓库、iCoRe 检索得到的相关源码和相关测试，生成一个 Bug Reproduction Test，要求该测试满足：

```text
buggy version: Fail
patched/fixed version: Pass
```

即 Fail-to-Pass，简称 F2P。

## 3. 输入与输出

### 输入

- 原始 issue 文本；
- iCoRe 检索得到的 source snippets；
- iCoRe 检索得到的 related tests；
- buggy 仓库 worktree；
- 与项目版本对应的 Conda 环境；
- 项目测试运行器信息；
- 生成预算：环境修复、BRT 语义修复、代理 patch 验证均为 3 轮。

### 输出

每个 instance 输出一个完整的新测试文件：

```text
final_test.py
```

该测试被放在与最相似 related test 同级的测试目录中，而不是修改原测试文件。

## 4. 总体流程

旧方法可以概括为：

```text
Issue + retrieved code + retrieved tests
→ 恢复测试上下文
→ 生成候选 BRT
→ buggy 执行
→ 根据执行反馈修复 setup / trigger / oracle
→ 语义验证候选失败是否与 issue 对齐
→ 使用 surrogate patch 作为候选排序信号
→ 输出最终 BRT
→ 独立 formal F2P 评测
```

## 5. 步骤 1：检索上下文读取

### 输入

- issue 数据；
- code retrieval JSON；
- related tests JSON；
- buggy repo base。

### 处理

系统不重新检索，而是复用 iCoRe 的检索结果。源码片段用于提供目标 API、疑似 bug 位置和实现上下文；相关测试用于提供测试目录、测试风格、imports、fixtures、setup 和调用链参考。

### 输出

一个 instance-level context，包括 issue 文本、检索源码、检索测试和仓库元数据。

## 6. 步骤 2：测试上下文恢复

### 输入

- 相关测试；
- buggy worktree；
- issue 行为目标；
- 项目 runner。

### 处理

旧方法恢复与 seed test 相关的测试协议，包括：

- 测试文件路径；
- 测试目录；
- imports；
- pytestmark；
- fixtures；
- class wrapper；
- setup/teardown；
- 相邻测试；
- 项目原生命令。

### 输出

HostContext，用于约束候选 BRT 的文件位置、运行命令和测试风格。

## 7. 步骤 3：候选 BRT 生成

### 输入

- issue；
- 相关源码；
- HostContext；
- seed test 代码；
- 项目源码窗口。

### 处理

模型生成一个完整的新测试文件，而不是返回一个插入片段。生成时要求保留相关测试的可执行结构，并围绕 issue 修改输入、状态、参数、调用链或断言。

### 输出

候选 BRT 文件和对应测试命令。

## 8. 步骤 4：buggy 执行与反馈修复

### 输入

- 候选 BRT；
- buggy worktree；
- Conda 环境；
- 项目测试命令。

### 处理

系统执行候选 BRT，并将结果分类为：

- `SETUP_ERROR`
- `SYNTAX_ERROR`
- `COLLECT_ERROR`
- `PASS`
- `ASSERTION_FAIL`
- `ISSUE_ALIGNED_FAIL`
- `UNRELATED_FAIL`
- `TIMEOUT`

如果是环境类错误，则修复 imports、fixtures、class、setup、runner。若 buggy 上通过，则说明缺陷路径未触发，转向 trigger 修复。若测试失败但不确定是否与 issue 对齐，则进入语义验证或 oracle 修复。

### 输出

修复后的候选测试和每轮执行日志。

## 9. 步骤 5：候选有效性判断

旧方法不是把任意 buggy fail 都当作成功，而是要求失败与 issue 相关。根据结果目录配置，该 run 启用了 strict semantic verifier 和 surrogate patch validation。

候选被接受的核心条件是：

- buggy 上失败；
- 不是 setup/syntax/collect/timeout；
- 失败原因与 issue 描述的症状相关；
- 测试的断言表达 expected behavior；
- 真实 patch 不参与生成阶段。

## 10. 步骤 6：代理 patch 验证

在生成阶段，系统不能访问真实 golden patch。旧方法使用 surrogate patch 作为近似验证：模型基于检索源码和失败日志生成少量 search/replace patch，在临时副本中应用，并运行同一个 BRT。

如果：

```text
buggy fail + surrogate patched pass
```

则候选获得更高排序分数。注意：surrogate patch 只是生成阶段的选择信号，不等同于最终 formal F2P。

## 11. 步骤 7：候选选择

旧方法每个 instance 最终输出一个 BRT。根据运行配置，候选链通过有限轮执行反馈产生多个 checkpoint，并根据执行结果和 surrogate 验证进行选择。可确认的选择思想是：

- 优先选择 surrogate F2P 的候选；
- 其次选择语义验证接受的 buggy fail；
- 避免选择环境/语法/收集失败；
- buggy pass 不能作为成功 BRT。

## 12. 为什么该方法能达到约 45% F2P

该方法的优势来自三点：

1. **检索上下文降低生成空间**：源码检索给出目标 API 和实现位置，相关测试给出可执行测试协议。
2. **执行反馈修复不可运行测试**：通过真实 buggy 执行过滤语法错误、环境错误、收集错误和未触发路径。
3. **语义验证与代理 patch 过滤伪失败**：不是所有 fail 都被接受，候选需要与 issue 行为对齐，并可由 surrogate patch 提供额外排序信号。

## 13. TODO

- 需要补充该 run 对应的源码 commit，才能精确区分当时实现与当前实现的差异。
- 需要进一步抽样 `run_20260624_refactor_deepseek7/generation/*/summary.json`，确认每类成功样例中 seed adaptation、oracle repair、surrogate patch 各自贡献比例。

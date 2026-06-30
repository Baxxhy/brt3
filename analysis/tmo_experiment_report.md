# BRT 测试级变异算子实验报告

## 1. 当前结果 vs 45% baseline

改动前最新完整 formal evaluation 为 113/276，formal F2P 为 40.94%。相对指定的 45% baseline，低 4.06 个百分点。历史结果 `results/runs/run_20260624_refactor_deepseek7/evaluation/metrics.json` 为 125/276（45.29%），可作为本地 45% 参考证据。

本次实验最终为 111/276，formal F2P 为 40.22%，相对 45% baseline 低 4.78 个百分点，相对改动前结果低 0.72 个百分点。若只按已成功生成并进入 formal evaluation 的 261 个实例计算，F2P 为 111/261（42.53%）；正式任务指标仍采用完整 276 实例作为分母。

## 2. 本次代码改动摘要

改动集中在 Mutation Plan 和 seed mutation 链路：扩充规则元数据与 plan schema，新增 operator router 和 mutation effect check，收紧 plan prompt，并在不破坏 checkpoint/resume 的前提下保存候选算子、原始 prompt/response、归一化 plan 和检查结果。另补充 issue rewrite partial 复用、安全 API pool 和实验结果导出。

详细文件级说明见 `analysis/tmo_mutation_changes.md`。

## 3. 测试级变异算子体系落地情况

9 个顶层 rule family 均保留，并升级为 `rule family -> operator_subtype -> concrete mutation instance`。Mutation Plan 已支持 `fault_proxy`，selected rule 已支持 subtype、置信度、依赖、实现模式、AST 可行性、before/after delta、触发效果和可观测差异。

Router 根据 issue pattern、seed/host/protocol 上下文、execution/verifier feedback 和历史先验缩小候选算子范围。Effect check 对 no-op、oracle overfit、Buggy PASS 后未增强 trigger 等风险只记录 warning，不中断兼容流程。本次完整运行中 trigger plan 的 `ORACLE_REBIND` 使用次数为 0，符合阶段隔离要求。

## 4. 5-instance smoke 结果

Smoke 路径：`results/tmo_smoke_20260630_001826`。

- 5/5 实例完成生成流程并落盘 summary。
- 2 个实例产出最终测试，状态为 `SURROGATE_F2P_SUCCESS`。
- 其余状态为 `SETUP_ERROR` 2 个、`ERROR` 1 个。
- Issue rewrite 复用 4 个，补跑成功 0 个，补跑失败 1 个。
- 成功实例的 plan 包含 `fault_proxy`、扩展 selected rules、candidate operators 和 mutation effect check。

## 5. Full generation 结果

完整生成路径：`results/tmo_full_20260630_003228`。运行配置为 276 个 SWE-bench Lite 实例、8 workers、单候选链、最多三轮反馈，并开启 protocol recovery、seed mutation、strict verifier、observation oracle 和 surrogate patch validation。

共生成 261 个最终测试，15 个实例未生成。Issue rewrite 从原 partial 复用 263 个，13 个缺失项补跑失败；合并结果写入 `results/issue_rewrite/issue_rewrite.completed.json`，原 partial 未被覆盖。

## 6. Formal evaluation 结果

正式评测使用项目已有 direct formal evaluation 入口，只在该阶段读取 golden patch。261 个已生成测试全部完成评测，评测进程 return code 为 0：

- `F2P_SUCCESS`: 111
- `FIXED_FAIL`: 117
- `BUGGY_PASS`: 32
- `FLAKY_EVAL`: 1
- 未生成/未评测: 15
- 已评测覆盖内 F2P: 42.53%
- 完整 276 实例 formal F2P: 40.22%

## 7. Operator-level 贡献分析

以下为重叠归因：一个实例最多选择 3 个算子，因此不同 rule 的 formal F2P 数量不能相加。

| Rule | Used | Formal F2P | Buggy PASS | No-op high risk |
| --- | ---: | ---: | ---: | ---: |
| CALL_CHAIN_EXTEND | 132 | 53 | 16 | 2 |
| ARG_BOUNDARY_EXPAND | 96 | 40 | 13 | 4 |
| ARG_VALUE_REPLACE | 71 | 37 | 6 | 0 |
| CONFIG_MUTATION | 42 | 14 | 8 | 5 |
| STATE_MUTATION | 30 | 11 | 5 | 1 |
| LIFECYCLE_TRIGGER | 29 | 7 | 6 | 0 |
| OPERATOR_FLIP | 15 | 6 | 2 | 0 |
| FIXTURE_DATA_MUTATION | 10 | 4 | 0 | 0 |
| ORACLE_REBIND | 0 | 0 | 0 | 0 |

CALL_CHAIN_EXTEND 的覆盖和成功贡献最高；ARG_VALUE_REPLACE 的粗粒度成功占比最高且未出现 high no-op risk。CONFIG_MUTATION 的 no-op high risk 相对偏高，LIFECYCLE_TRIGGER 的 formal 转化偏低。

## 8. 主要失败类型

formal failure 以 `FIXED_FAIL` 为主（117），说明测试在修复版本上仍失败，下一轮应优先削弱脆弱断言、测试环境耦合和非公开实现细节。`BUGGY_PASS` 为 32，说明部分 trigger 仍未命中缺陷，应继续加强调用链物化、边界输入、状态转换和 lifecycle 触发。

另有 15 个未生成实例，其中 13 个与缺失 issue rewrite 重合。该问题直接损失完整任务分母上的 5.43 个百分点，是当前最明确的流程覆盖瓶颈。

## 9. 下一步建议

1. 优先修复 13 个 issue rewrite 补跑失败以及另外 2 个生成失败实例，先把 formal coverage 从 261 提升到 276。
2. 对 `FIXED_FAIL` 样本按 assertion 类型聚类，利用 observation oracle 将私有状态/精确字符串断言改为公开行为与结构性断言。
3. 对 `BUGGY_PASS` 样本加强 router 的反馈调权，要求下一轮在 before/after delta 中显式增加物化、重复调用、保存加载或边界输入。
4. 下调 CONFIG_MUTATION 的默认权重，除非 issue 和 host protocol 有明确配置证据；针对 LIFECYCLE_TRIGGER 增加框架匹配约束。
5. 分别统计单 rule 与 rule 组合的条件 formal F2P，避免重叠归因掩盖真正有效的算子组合。

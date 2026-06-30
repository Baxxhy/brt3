# 测试级变异算子体系改动摘要

## 范围

本次改动聚焦 BRT 主链路中的 Mutation Plan 与 seed mutation 阶段，保持既有流程：

Issue Rewrite -> Seed/HostContext -> Protocol Recovery -> Mutation Plan -> Candidate BRT -> Execution Feedback -> Strict Verifier -> Observation Oracle -> Surrogate Patch Validation -> Formal Evaluation。

## 主要改动

1. `mutation/brt_mutation_rules.py`
   - 保留 9 个顶层 rule family。
   - 为每个 `MutationRule` 增加 `subtypes`、`transformation_template`、`expected_effect`、`oracle_hints`、`implementation_modes`。
   - 将规则体系升级为 `rule family -> operator_subtype -> concrete mutation instance`。
   - 保持 `TRIGGER_RULE_NAMES` 不包含 `ORACLE_REBIND`，使 `ORACLE_REBIND` 只留给 observation oracle / oracle repair 阶段。

2. `mutation/mutation_plan_schema.py` 与 `core/schema.py`
   - `MutationPlan` 增加 `fault_proxy`。
   - `selected_rules` 归一化到包含 `operator_subtype`、`before_pattern`、`after_pattern`、`expected_trigger_effect`、`observable_difference` 等字段的新结构。
   - 兼容旧字段 `mutation -> after_pattern`。
   - 对非法 rule、trigger 阶段的 `ORACLE_REBIND`、非法 subtype、空 before/after/effect、非法 mode 等只记录 warning，不中断流程。

3. `mutation/mutation_operator_router.py`
   - 新增 deterministic router，根据 issue pattern、seed 证据、上一轮 execution/verifier feedback 和 analysis prior 推荐候选 trigger operators。
   - 支持 `query_sql`、`repr_string_format`、`serialization`、`parser_render`、`null_empty`、`dtype_shape`、`configuration`、`warning`、`cache_state`、`io_path`、`exception` 等路由。
   - 对 `Buggy PASS` 提高更强 trigger rule，对 setup/collect/syntax error 降低 setup-sensitive rule。

4. `mutation/mutation_effect_check.py`
   - 新增非阻断式 plan 质量检查。
   - 检查 target_api、具体 mutation action、before/after delta、expected_trigger_effect、observable_difference、oracle-only plan、Buggy PASS 后是否加强 trigger、特定 issue pattern 的 oracle 可观测性。
   - 检查结果写入 `mutation_round_<n>_plan.json` 与独立 `mutation_effect_check_round_<n>.json`。

5. `mutation/seed_mutator.py` 与 prompt
   - Mutation Plan prompt 改为接收 `candidate_operators_json`。
   - LLM 只能从 router 给出的 candidate operators 选择 trigger rules/subtypes。
   - 保存 prompt、response、candidate operators、normalized plan、validation warnings 和 mutation effect check。

6. issue rewrite partial 复用
   - `cli/run.py` 支持 aggregate partial issue rewrite。
   - 已存在 instance 直接复用，缺失 instance 在线补跑 issue rewrite。
   - 不覆盖原始 partial，合并结果写到 `results/issue_rewrite/issue_rewrite.completed.json`。

7. API pool 安全化
   - `llm/api_pool.py` 改为从未跟踪的 `.secrets/api_pool.local.json` 读取 key。
   - `.secrets/` 和 `*.local.json` 均被 git ignore。
   - API metadata 只暴露 masked key。
   - 当前 secrets 配置要求 10 个 API account。

8. 结果导出
   - `scripts/export_run_outputs.py` 新增 run 根目录级输出：
     - `all_generated_tests.json`
     - `operator_level_stats.json`
     - `final_summary.json`
     - `formal_eval_summary.json`
     - smoke run 额外输出 `smoke_summary.json`

## 风险控制

- 未删除旧结果。
- 未覆盖 `results/issue_rewrite/issue_rewrite.partial.json`。
- 未把真实 golden patch/test 放入生成 prompt。
- API key 不写入 tracked 文件、prompt、response 或 summary。

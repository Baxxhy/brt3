"""Dataclasses used by the BRT3 pipeline."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any

from core.utils import safe_json_dump


class JsonMixin:
    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    def save_json(self, path: str) -> None:
        safe_json_dump(self.to_dict(), path)


@dataclass
class RetrievedCode(JsonMixin):
    instance_id: str
    obj_name: str = ""
    node_type: str = ""
    path: str = ""
    code_start_line: str | int = ""
    code_end_line: str | int = ""
    code_content: str = ""
    parent: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class RetrievedTest(JsonMixin):
    instance_id: str
    name: str = ""
    file: str = ""
    code_content: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class InstanceContext(JsonMixin):
    instance_id: str
    issue_text: str
    repo: str = ""
    base_commit: str = ""
    buggy_repo_path: str = ""
    retrieved_code: list[RetrievedCode] = field(default_factory=list)
    retrieved_tests: list[RetrievedTest] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BehaviorTarget(JsonMixin):
    instance_id: str
    issue_summary: str = ""
    trigger_condition: dict[str, Any] = field(default_factory=dict)
    error_symptom: dict[str, Any] = field(default_factory=dict)
    expected_behavior: dict[str, Any] = field(default_factory=dict)
    target_apis: list[dict[str, Any]] = field(default_factory=list)
    suspected_bug_locations: list[dict[str, Any]] = field(default_factory=list)
    related_test_seeds: list[dict[str, Any]] = field(default_factory=list)
    mutation_hints: list[dict[str, Any]] = field(default_factory=list)
    observation_points: list[dict[str, Any]] = field(default_factory=list)
    assertion_hints: list[dict[str, Any]] = field(default_factory=list)
    setup_hints: list[dict[str, Any]] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class HostContext(JsonMixin):
    instance_id: str
    host_file: str = ""
    host_class: str = ""
    seed_test_name: str = ""
    seed_test_code: str = ""
    imports: str = ""
    setup_context: str = ""
    model_context: str = ""
    fixtures: list[str] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    pytestmark: str = ""
    test_command: str = ""
    seed_execution_status: str = "ERROR"
    seed_execution: dict[str, Any] = field(default_factory=dict)
    insert_strategy: str = "same_dir_new_file"
    insert_location_hint: str = ""
    adjacent_tests: list[str] = field(default_factory=list)
    full_test_file_path: str = ""
    warnings: list[str] = field(default_factory=list)


@dataclass
class HostScaffold(JsonMixin):
    instance_id: str
    host_scaffold_mode: str = "fallback_old"
    test_file: str = ""
    test_entry: str = ""
    enclosing_class: str = ""
    framework: str = "unknown"
    cleaned_imports: list[str] = field(default_factory=list)
    module_pytestmark: str = ""
    class_wrapper: str = ""
    setup_methods: list[str] = field(default_factory=list)
    teardown_methods: list[str] = field(default_factory=list)
    fixture_args: list[str] = field(default_factory=list)
    local_helpers: list[dict[str, str]] = field(default_factory=list)
    seed_decorators: list[str] = field(default_factory=list)
    seed_function_signature: str = ""
    seed_function_body: str = ""
    seed_function_code: str = ""
    class_decorators: list[str] = field(default_factory=list)
    class_bases: list[str] = field(default_factory=list)
    class_attributes: list[str] = field(default_factory=list)
    scaffold_code: str = ""
    scaffold_hash: str = ""
    seed_function_hash: str = ""
    fallback_reason: str = ""


@dataclass
class ProtocolRecovery(JsonMixin):
    instance_id: str
    test_file: str = ""
    test_framework: str = "unknown"
    test_command: str = ""
    imports: list[str] = field(default_factory=list)
    fixtures: list[str] = field(default_factory=list)
    pytest_marks: list[str] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    class_context: str = ""
    setup_methods: list[str] = field(default_factory=list)
    teardown_methods: list[str] = field(default_factory=list)
    local_helpers: list[dict[str, str]] = field(default_factory=list)
    local_models: list[dict[str, str]] = field(default_factory=list)
    conftest_context: list[dict[str, Any]] = field(default_factory=list)
    runner_hints: list[str] = field(default_factory=list)
    protocol_risks: list[str] = field(default_factory=list)
    selected_seed_name: str = ""
    placement_dir: str = ""


@dataclass
class MutationPlan(JsonMixin):
    instance_id: str
    round_id: int = 0
    mutation_goal: str = ""
    issue_pattern: str = "unknown"
    fault_proxy: dict[str, str] = field(default_factory=dict)
    selected_rules: list[dict[str, Any]] = field(default_factory=list)
    preserve_from_seed: list[str] = field(default_factory=list)
    do_not_change: list[str] = field(default_factory=list)
    target_api: list[str] = field(default_factory=list)
    target_path: list[str] = field(default_factory=list)
    mutation_ops: list[str] = field(default_factory=list)
    expected_behavior: str = ""
    oracle_strategy: str | dict[str, Any] = ""
    why_this_should_trigger: str = ""
    risk: str = "medium"
    fallback_if_buggy_pass: str = ""
    fallback_if_fixed_fail: str = ""
    anchor_seed_used: str = ""
    reference_seeds_used: list[str] = field(default_factory=list)
    borrowed_elements: list[str] = field(default_factory=list)
    mutated_elements: list[str] = field(default_factory=list)
    issue_alignment: str = ""
    buggy_expected_behavior: str = ""
    fixed_expected_behavior: str = ""
    oracle_plan: str | dict[str, Any] = ""
    mutation_plan_mode: str = "fallback_old"
    selected_operators: list[str] = field(default_factory=list)
    mutation_targets: list[dict[str, Any]] = field(default_factory=list)
    preserve_constraints: list[str] = field(default_factory=list)
    before_pattern_found: bool = False
    before_pattern_unique: bool = False
    sanitizer_status: str = "NOT_RUN"
    sanitizer_warnings: list[str] = field(default_factory=list)
    fallback_reason: str = ""
    scaffold_hash: str = ""
    mutation_ops_truncated: bool = False


@dataclass
class StrictVerifierResult(JsonMixin):
    instance_id: str
    decision: str = "reject"
    failure_class: str = "side_path"
    target_hit: bool = False
    oracle_grounded_in_issue: bool = False
    uses_public_behavior: bool = False
    reason: str = ""
    next_action: str = "reject"


@dataclass
class CandidateTest(JsonMixin):
    instance_id: str
    round_id: int = 0
    code: str = ""
    candidate_file_path: str = ""
    candidate_repo_path: str = ""
    pytest_nodeid: str = ""
    command: str = ""
    prompt_path: str = ""
    response_path: str = ""
    status: str = "CREATED"
    notes: str = ""
    generator_mode: str = "fallback_old"
    fallback_reason: str = ""
    before_pattern_found: bool = False
    before_pattern_unique: bool = False
    final_test_hash: str = ""


@dataclass
class CandidateCheckpoint(JsonMixin):
    instance_id: str
    round_id: int
    code_path: str = ""
    score: int = 0
    reason: str = ""
    execution: dict[str, Any] = field(default_factory=dict)
    verifier: dict[str, Any] = field(default_factory=dict)
    surrogate: dict[str, Any] = field(default_factory=dict)
    selected: bool = False


@dataclass
class ExecutionResult(JsonMixin):
    instance_id: str = ""
    command: str = ""
    cwd: str = ""
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""
    duration: float = 0.0
    timeout: bool = False
    status: str = "PASS"
    error_reason: str = ""


@dataclass
class ObservationReport(JsonMixin):
    instance_id: str
    probe_code: str = ""
    probe_file_path: str = ""
    execution: dict[str, Any] = field(default_factory=dict)
    observations: dict[str, Any] = field(default_factory=dict)
    raw_output: str = ""
    status: str = "UNKNOWN"


@dataclass
class VerifierDecision(JsonMixin):
    instance_id: str
    decision: str = "reject"
    reason: str = ""
    focus: list[str] = field(default_factory=list)
    next_action: str = ""


@dataclass
class DualVersionResult(JsonMixin):
    instance_id: str
    mode: str = "buggy_only"
    buggy_execution: dict[str, Any] = field(default_factory=dict)
    patched_execution: dict[str, Any] = field(default_factory=dict)
    status: str = "NOT_RUN"
    notes: str = ""
    surrogate_patch: dict[str, Any] = field(default_factory=dict)
    attempts: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SurrogatePatchCandidate(JsonMixin):
    instance_id: str
    round_id: int = 0
    patches: list[dict[str, Any]] = field(default_factory=list)
    applied_paths: list[str] = field(default_factory=list)
    diff: str = ""
    status: str = "CREATED"
    reason: str = ""
    prompt_path: str = ""
    response_path: str = ""


@dataclass
class FinalResult(JsonMixin):
    instance_id: str
    status: str = "BEST_EFFORT"
    final_test_path: str = ""
    rounds_used: int = 0
    buggy_execution: dict[str, Any] = field(default_factory=dict)
    dual_version_result: dict[str, Any] = field(default_factory=dict)
    behavior_target: dict[str, Any] = field(default_factory=dict)
    host_context: dict[str, Any] = field(default_factory=dict)
    observation_report: dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    protocol_recovery_enabled: bool = False
    seed_mutation_enabled: bool = False
    observation_oracle_enabled: bool = False
    strict_verifier_enabled: bool = False
    selected_seed_file: str = ""
    selected_seed_name: str = ""
    seed_fallback_used: bool = False
    mutation_ops: list[str] = field(default_factory=list)
    oracle_type: str = ""
    strict_verifier_decision: str = ""
    strict_failure_class: str = ""
    oracle_rebound: bool = False
    final_reason: str = ""
    deterministic: bool = True
    mode: str = "deep"
    llm_cache_hit_count: int = 0
    llm_cache_miss_count: int = 0
    selected_key_index: int = -1
    selected_key_name: str = ""
    api_retry_count: int = 0
    api_error_types: list[str] = field(default_factory=list)
    selected_seed_signature: str = ""
    seed_reused: bool = False
    seed_change_reason: str = ""
    seed_selection_mode: str = ""
    seed_candidates_count: int = 0
    selected_seed_score: float = 0.0
    matched_apis: list[dict[str, Any]] = field(default_factory=list)
    seed_score_breakdown: dict[str, Any] = field(default_factory=dict)
    seed_selection_fallback_reason: str = ""
    primary_seed_test: dict[str, Any] = field(default_factory=dict)
    host_scaffold_mode: str = ""
    scaffold_hash: str = ""
    seed_function_hash: str = ""
    mutation_plan_mode: str = ""
    selected_operators: list[str] = field(default_factory=list)
    before_pattern_found: bool = False
    before_pattern_unique: bool = False
    sanitizer_status: str = ""
    generator_mode: str = ""
    fallback_reason: str = ""
    final_test_hash: str = ""
    mutation_plan: dict[str, Any] = field(default_factory=dict)
    mutation_rules_used: list[str] = field(default_factory=list)
    mutation_risk: str = "medium"
    issue_pattern: str = "unknown"
    oracle_strategy: str = ""
    surrogate_patch_used: bool = False
    surrogate_patch_decision_used_for_ranking_only: bool = True
    observation_oracle_used: bool = False
    strict_verifier_level: str = ""
    analysis_prior_used: bool = False
    regression_guard_triggered: bool = False
    regression_guard_reason: str = ""
    final_selection_reason: str = ""
    seed_mode: str = "single"
    available_retrieved_tests_count: int = 0
    valid_seed_tests_count: int = 0
    used_seed_tests_count: int = 0
    invalid_seed_reasons: list[dict[str, Any]] = field(default_factory=list)
    max_mutation_ops: int = 3
    selected_seed_rank: int = -1
    selected_candidate_priority: str = ""
    selected_priority_reason: str = ""
    seed_candidate_results: list[dict[str, Any]] = field(default_factory=list)

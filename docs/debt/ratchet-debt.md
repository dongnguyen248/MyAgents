# Code-structure ratchet debt

This file is the debt register for `.code-structure-baseline.json`,
the recorded set of code-structure violations that
`scripts/check_code_structure.py` tolerates. Every other violation
fails CI.

## The rule

After the one-time reset recorded below, **every baseline entry may
only go down**. A run fails when a violation is new or a baselined
value grows. Any increase of a baseline value needs Dong's explicit
approval, recorded in this file next to the entry, before it lands.
Shrinking or removing entries is always welcome and needs no
approval: regenerate with `--write-baseline` in the same PR that
pays the debt down.

## One-time reset — 2026-11-09

The baseline had drifted from reality: ordinary feature work grew
units past their recorded values, so the ratchet (and CI with it)
was red on pristine master. On 2026-11-09 the baseline was reset
once to the measured values, approved by Dong, as part of the
ratchet-repair PR. This reset is the recorded exception to the
rule above; it does not set a precedent.

- Entries: 234 → 225 (10 removed, 1 added, 17 raised, 26 lowered,
  181 unchanged).
- The one added entry: `src/asf/tools/local.py` LocalWorkspace
  class-lines = 387 (a real violation that predates the reset; the
  class grew past 300 lines without ever being baselined).
- The 26 lowered entries are pure tightening: the old baseline
  recorded more than the code measures today.

### The 17 raised entries (old baseline value → measured value)

| File | Symbol | Rule | Old | New |
| --- | --- | --- | --- | --- |
| src/asf/api/demo.py | build_demo | function-complexity | 16 | 22 |
| src/asf/api/demo.py | build_demo | function-lines | 158 | 174 |
| src/asf/api/service/__init__.py | (file) | file-lines | 580 | 597 |
| src/asf/api/service/__init__.py | FactoryService | class-fields | 31 | 32 |
| src/asf/api/service/__init__.py | FactoryService | class-lines | 374 | 386 |
| src/asf/api/service/__init__.py | FactoryService.__init__ | function-lines | 64 | 66 |
| src/asf/api/service/__init__.py | FactoryService.__init__ | function-params | 15 | 16 |
| src/asf/api/service/__init__.py | FactoryService._normalize_project | function-lines | 78 | 84 |
| src/asf/api/service/commands.py | (file) | file-lines | 769 | 781 |
| src/asf/api/service/commands.py | CommandsMixin | class-lines | 780 | 783 |
| src/asf/api/service/queries.py | (file) | file-lines | 1203 | 1229 |
| src/asf/api/service/queries.py | QueriesMixin | class-lines | 1217 | 1240 |
| src/asf/api/service/queries.py | QueriesMixin._workflow_view | function-lines | 40 | 41 |
| src/asf/api/service/queries.py | QueriesMixin.list_projects | function-lines | 49 | 51 |
| src/asf/tools/local.py | (file) | file-lines | 702 | 930 |
| src/asf/tools/local.py | LocalWorkspace | class-fields | 8 | 10 |
| src/asf/tools/local.py | LocalWorkspace | class-methods | 18 | 28 |

### The 9 stale entries removed

These violations no longer exist in the code; the baseline entries
were leftovers. (A tenth removal, the `tools/local.py` banner-comment
entry, is not stale debt: the comments were deleted in the same PR,
item 4.)

| File | Symbol | Rule | Old value |
| --- | --- | --- | --- |
| src/asf/api/demo.py | DemoRoutingGateway.complete | function-nesting | 6 |
| src/asf/api/demo.py | run_selftest | function-lines | 34 |
| src/asf/evaluation/service.py | MetricsService._agent_metrics_locked | function-complexity | 22 |
| src/asf/evaluation/service.py | MetricsService._agent_metrics_locked | function-lines | 34 |
| src/asf/evaluation/service.py | MetricsService.record_approval_decision | function-params | 5 |
| src/asf/evaluation/service.py | _health_score | function-params | 5 |
| src/asf/integrations/teams/workflow.py | TeamsWorkflow.send_approval | function-lines | 35 |
| src/asf/orchestrator/engine.py | Orchestrator.tick | function-nesting | 4 |
| src/asf/tools/local.py | LocalSandbox.run | function-lines | 35 |

### Comment-only debt

15 entries (12 banner-comment, 3 numbered-comment) across
15 files, covering 67 individual comments. Cheapest debt in the
register: deleting or rewording the comments removes the entry, with
zero behaviour risk. (Stage 0 estimated “~35”; the precise count is
the 15 entries below — one entry per file and rule, its measured
value being the number of offending comments in that file.)

| File | Rule | Comments |
| --- | --- | --- |
| src/asf/api/app.py | banner-comment | 8 |
| src/asf/api/model_settings.py | banner-comment | 2 |
| src/asf/api/scheduler.py | banner-comment | 3 |
| src/asf/api/service/__init__.py | banner-comment | 10 |
| src/asf/api/service/commands.py | banner-comment | 6 |
| src/asf/api/service/driver.py | banner-comment | 2 |
| src/asf/api/service/queries.py | banner-comment | 10 |
| src/asf/evaluation/service.py | banner-comment | 7 |
| src/asf/integrations/hosting/github.py | banner-comment | 3 |
| src/asf/integrations/hosting/gitlab.py | banner-comment | 2 |
| src/asf/state_machine/graph.py | numbered-comment | 3 |
| src/asf/state_machine/machine.py | numbered-comment | 4 |
| src/asf/storage/mariadb.py | banner-comment | 2 |
| src/asf/tools/worktree.py | banner-comment | 2 |
| src/asf/workflow/definition.py | numbered-comment | 3 |

## Debt by area

### Engine / orchestrator — 29 entries

Owner: Dong (maintainer) — Phase 11a Wave 2 workstream. Roadmap: Wave 2 splits the Orchestrator engine into focused modules; entries shrink as the split lands. No growth tolerated meanwhile.

| File | Symbol | Rule | Measured | Limit |
| --- | --- | --- | --- | --- |
| src/asf/orchestrator/code_loop.py | code_steps | function-complexity | 11 | 10 |
| src/asf/orchestrator/code_loop.py | loop_graph | function-lines | 37 | 30 |
| src/asf/orchestrator/code_loop.py | ordered_task_ids | function-complexity | 11 | 10 |
| src/asf/orchestrator/engine.py | (file) | file-lines | 1237 | 500 |
| src/asf/orchestrator/engine.py | Orchestrator | class-fields | 15 | 7 |
| src/asf/orchestrator/engine.py | Orchestrator | class-lines | 1232 | 300 |
| src/asf/orchestrator/engine.py | Orchestrator | class-methods | 15 | 10 |
| src/asf/orchestrator/engine.py | Orchestrator.__init__ | function-complexity | 15 | 10 |
| src/asf/orchestrator/engine.py | Orchestrator.__init__ | function-lines | 42 | 30 |
| src/asf/orchestrator/engine.py | Orchestrator.__init__ | function-params | 12 | 4 |
| src/asf/orchestrator/engine.py | Orchestrator._apply_result | function-complexity | 42 | 10 |
| src/asf/orchestrator/engine.py | Orchestrator._apply_result | function-lines | 109 | 30 |
| src/asf/orchestrator/engine.py | Orchestrator._apply_result | function-params | 5 | 4 |
| src/asf/orchestrator/engine.py | Orchestrator._deliver_observations | function-complexity | 18 | 10 |
| src/asf/orchestrator/engine.py | Orchestrator._deliver_observations | function-lines | 36 | 30 |
| src/asf/orchestrator/engine.py | Orchestrator._deliver_observations | function-nesting | 4 | 3 |
| src/asf/orchestrator/engine.py | Orchestrator._failed_stage | function-complexity | 11 | 10 |
| src/asf/orchestrator/engine.py | Orchestrator._linked_output | function-complexity | 17 | 10 |
| src/asf/orchestrator/engine.py | Orchestrator._linked_output | function-lines | 44 | 30 |
| src/asf/orchestrator/engine.py | Orchestrator._prepare_dispatch | function-complexity | 35 | 10 |
| src/asf/orchestrator/engine.py | Orchestrator._prepare_dispatch | function-lines | 117 | 30 |
| src/asf/orchestrator/engine.py | Orchestrator._retry | function-complexity | 11 | 10 |
| src/asf/orchestrator/engine.py | Orchestrator.decide | function-params | 5 | 4 |
| src/asf/orchestrator/engine.py | Orchestrator.resume_failed | function-complexity | 14 | 10 |
| src/asf/orchestrator/engine.py | Orchestrator.resume_failed | function-lines | 70 | 30 |
| src/asf/orchestrator/engine.py | Orchestrator.start | function-complexity | 15 | 10 |
| src/asf/orchestrator/engine.py | Orchestrator.start | function-lines | 42 | 30 |
| src/asf/orchestrator/engine.py | Orchestrator.tick | function-complexity | 21 | 10 |
| src/asf/orchestrator/engine.py | Orchestrator.tick | function-lines | 97 | 30 |

### API service — 56 entries

Owner: Dong (maintainer) — Phase 11a Wave 2 workstream. Roadmap: Wave 2 splits FactoryService into routes/services. **queries.py is HIGH priority**: biggest file in the codebase (1,229 lines) and still growing — split its views first.

| File | Symbol | Rule | Measured | Limit |
| --- | --- | --- | --- | --- |
| src/asf/api/service/__init__.py | (file) | banner-comment | 10 | 0 |
| src/asf/api/service/__init__.py | (file) | file-lines | 597 | 500 |
| src/asf/api/service/__init__.py | FactoryService | class-fields | 32 | 7 |
| src/asf/api/service/__init__.py | FactoryService | class-lines | 386 | 300 |
| src/asf/api/service/__init__.py | FactoryService.__init__ | function-lines | 66 | 30 |
| src/asf/api/service/__init__.py | FactoryService.__init__ | function-params | 16 | 4 |
| src/asf/api/service/__init__.py | FactoryService._discover_store_runs | function-nesting | 5 | 3 |
| src/asf/api/service/__init__.py | FactoryService._normalize_project | function-complexity | 44 | 10 |
| src/asf/api/service/__init__.py | FactoryService._normalize_project | function-lines | 84 | 30 |
| src/asf/api/service/__init__.py | FactoryService._normalize_project | function-nesting | 5 | 3 |
| src/asf/api/service/commands.py | (file) | banner-comment | 6 | 0 |
| src/asf/api/service/commands.py | (file) | file-lines | 781 | 500 |
| src/asf/api/service/commands.py | CommandsMixin | class-lines | 783 | 300 |
| src/asf/api/service/commands.py | CommandsMixin | class-methods | 15 | 10 |
| src/asf/api/service/commands.py | CommandsMixin._advance_split_chain | function-complexity | 22 | 10 |
| src/asf/api/service/commands.py | CommandsMixin._advance_split_chain | function-lines | 52 | 30 |
| src/asf/api/service/commands.py | CommandsMixin._start_split_run | function-lines | 53 | 30 |
| src/asf/api/service/commands.py | CommandsMixin._start_split_run | function-params | 5 | 4 |
| src/asf/api/service/commands.py | CommandsMixin._validated_skip_approvals | function-complexity | 11 | 10 |
| src/asf/api/service/commands.py | CommandsMixin.decide_approval | function-complexity | 13 | 10 |
| src/asf/api/service/commands.py | CommandsMixin.decide_approval | function-lines | 55 | 30 |
| src/asf/api/service/driver.py | (file) | banner-comment | 2 | 0 |
| src/asf/api/service/driver.py | DriverMixin | class-lines | 394 | 300 |
| src/asf/api/service/driver.py | DriverMixin._drive | function-complexity | 14 | 10 |
| src/asf/api/service/driver.py | DriverMixin._drive | function-lines | 57 | 30 |
| src/asf/api/service/queries.py | (file) | banner-comment | 10 | 0 |
| src/asf/api/service/queries.py | (file) | file-lines | 1229 | 500 |
| src/asf/api/service/queries.py | QueriesMixin | class-lines | 1240 | 300 |
| src/asf/api/service/queries.py | QueriesMixin | class-methods | 13 | 10 |
| src/asf/api/service/queries.py | QueriesMixin._activity_view | function-complexity | 21 | 10 |
| src/asf/api/service/queries.py | QueriesMixin._activity_view | function-lines | 53 | 30 |
| src/asf/api/service/queries.py | QueriesMixin._agent_view | function-complexity | 17 | 10 |
| src/asf/api/service/queries.py | QueriesMixin._agent_view | function-lines | 38 | 30 |
| src/asf/api/service/queries.py | QueriesMixin._approval_step_state | function-complexity | 13 | 10 |
| src/asf/api/service/queries.py | QueriesMixin._approval_step_state | function-params | 5 | 4 |
| src/asf/api/service/queries.py | QueriesMixin._approval_view | function-complexity | 12 | 10 |
| src/asf/api/service/queries.py | QueriesMixin._approval_view | function-lines | 34 | 30 |
| src/asf/api/service/queries.py | QueriesMixin._group_split_parts | function-complexity | 12 | 10 |
| src/asf/api/service/queries.py | QueriesMixin._split_parent_views | function-complexity | 27 | 10 |
| src/asf/api/service/queries.py | QueriesMixin._split_parent_views | function-lines | 53 | 30 |
| src/asf/api/service/queries.py | QueriesMixin._split_parent_views | function-nesting | 5 | 3 |
| src/asf/api/service/queries.py | QueriesMixin._step_states | function-complexity | 72 | 10 |
| src/asf/api/service/queries.py | QueriesMixin._step_states | function-lines | 151 | 30 |
| src/asf/api/service/queries.py | QueriesMixin._step_states | function-nesting | 7 | 3 |
| src/asf/api/service/queries.py | QueriesMixin._waiting | function-complexity | 16 | 10 |
| src/asf/api/service/queries.py | QueriesMixin._waiting | function-lines | 65 | 30 |
| src/asf/api/service/queries.py | QueriesMixin._workflow_view | function-lines | 41 | 30 |
| src/asf/api/service/queries.py | QueriesMixin.list_activity | function-complexity | 24 | 10 |
| src/asf/api/service/queries.py | QueriesMixin.list_activity | function-lines | 37 | 30 |
| src/asf/api/service/queries.py | QueriesMixin.list_projects | function-complexity | 19 | 10 |
| src/asf/api/service/queries.py | QueriesMixin.list_projects | function-lines | 51 | 30 |
| src/asf/api/service/queries.py | QueriesMixin.list_projects | function-nesting | 5 | 3 |
| src/asf/api/service/queries.py | QueriesMixin.list_tasks | function-complexity | 28 | 10 |
| src/asf/api/service/queries.py | QueriesMixin.list_tasks | function-lines | 34 | 30 |
| src/asf/api/service/queries.py | QueriesMixin.run_diagnostics | function-complexity | 12 | 10 |
| src/asf/api/service/queries.py | QueriesMixin.run_diagnostics | function-lines | 55 | 30 |

### API app shell — 4 entries

Owner: Dong (maintainer). Roadmap: create_app shrinks as routes move out in Wave 2.

| File | Symbol | Rule | Measured | Limit |
| --- | --- | --- | --- | --- |
| src/asf/api/app.py | (file) | banner-comment | 8 | 0 |
| src/asf/api/app.py | create_app | function-complexity | 58 | 10 |
| src/asf/api/app.py | create_app | function-lines | 299 | 30 |
| src/asf/api/app.py | create_app.list_tasks | function-params | 6 | 4 |

### Demo assembly — 17 entries

Owner: Dong (maintainer). Roadmap: build_demo is the composition root; extract gateway/sandbox assembly helpers opportunistically when the demo next changes.

| File | Symbol | Rule | Measured | Limit |
| --- | --- | --- | --- | --- |
| src/asf/api/demo.py | (file) | file-lines | 1011 | 500 |
| src/asf/api/demo.py | DemoFactoryService._default_test_commands | function-complexity | 13 | 10 |
| src/asf/api/demo.py | DemoFactoryService._language_rule_packs | function-complexity | 11 | 10 |
| src/asf/api/demo.py | DemoFactoryService._review_rules | function-complexity | 14 | 10 |
| src/asf/api/demo.py | DemoFactoryService._review_rules | function-lines | 36 | 30 |
| src/asf/api/demo.py | DemoFactoryService.start_run | function-complexity | 11 | 10 |
| src/asf/api/demo.py | DemoFactoryService.start_run | function-lines | 33 | 30 |
| src/asf/api/demo.py | _FallbackMetrics.agent_metrics | function-complexity | 12 | 10 |
| src/asf/api/demo.py | _WorkspaceBindingAgent._commit_after_passing_tests | function-complexity | 16 | 10 |
| src/asf/api/demo.py | _WorkspaceBindingAgent._commit_after_passing_tests | function-lines | 39 | 30 |
| src/asf/api/demo.py | _load_metrics | function-nesting | 4 | 3 |
| src/asf/api/demo.py | _profile_sandbox_settings | function-complexity | 20 | 10 |
| src/asf/api/demo.py | _profile_sandbox_settings | function-lines | 59 | 30 |
| src/asf/api/demo.py | _profile_sandbox_settings | function-nesting | 4 | 3 |
| src/asf/api/demo.py | build_demo | function-complexity | 22 | 10 |
| src/asf/api/demo.py | build_demo | function-lines | 174 | 30 |
| src/asf/api/demo.py | main | function-lines | 53 | 30 |

### Tools — local sandbox & workspace — 19 entries

Owner: Dong (maintainer). Roadmap: **HIGH priority: split LocalWorkspace** out of tools/local.py (387 class lines, 28 public methods, 10 fields) into its own module, separating repository reads from sandbox execution. The file is 930 lines against a 500 limit.

| File | Symbol | Rule | Measured | Limit |
| --- | --- | --- | --- | --- |
| src/asf/tools/edit_blocks.py | _check_path | function-complexity | 13 | 10 |
| src/asf/tools/edit_blocks.py | parse_edit_blocks | function-complexity | 33 | 10 |
| src/asf/tools/edit_blocks.py | parse_edit_blocks | function-lines | 155 | 30 |
| src/asf/tools/edit_blocks.py | parse_edit_blocks | function-nesting | 4 | 3 |
| src/asf/tools/fake.py | InMemorySandbox.run | function-complexity | 13 | 10 |
| src/asf/tools/fake.py | InMemorySandbox.run | function-lines | 47 | 30 |
| src/asf/tools/fake.py | InMemorySandbox.run | function-nesting | 5 | 3 |
| src/asf/tools/local.py | (file) | file-lines | 930 | 500 |
| src/asf/tools/local.py | LocalSandbox._run_one | function-lines | 47 | 30 |
| src/asf/tools/local.py | LocalWorkspace | class-fields | 10 | 7 |
| src/asf/tools/local.py | LocalWorkspace | class-lines | 387 | 300 |
| src/asf/tools/local.py | LocalWorkspace | class-methods | 28 | 10 |
| src/asf/tools/local.py | _terminate_tree | function-lines | 35 | 30 |
| src/asf/tools/local.py | build_sandbox_env | function-complexity | 14 | 10 |
| src/asf/tools/local.py | build_sandbox_env | function-lines | 34 | 30 |
| src/asf/tools/worktree.py | (file) | banner-comment | 2 | 0 |
| src/asf/tools/worktree.py | GitWorktreeWorkspace.ensure | function-lines | 37 | 30 |
| src/asf/tools/worktree.py | GitWorktreeWorkspace.sweep | function-complexity | 13 | 10 |
| src/asf/tools/worktree.py | GitWorktreeWorkspace.sweep | function-lines | 32 | 30 |

### Harness — 4 entries

Owner: Dong (maintainer) — Harness² workstream. Roadmap: Shrinks with the Harness² roadmap; experiment code is offline and human-gated, so this debt is low-risk.

| File | Symbol | Rule | Measured | Limit |
| --- | --- | --- | --- | --- |
| harness/evaluation/runner.py | EvaluationRunner._build_engine | function-lines | 40 | 30 |
| harness/evaluation/runner.py | EvaluationRunner.run_case | function-complexity | 14 | 10 |
| harness/evaluation/runner.py | EvaluationRunner.run_case | function-lines | 48 | 30 |
| harness/optimization/experiments.py | _run_code_loop | function-lines | 92 | 30 |

### Everything else — 96 entries

Owner: Dong (maintainer). Roadmap: Opportunistic: fix when the file is next changed.

| File | Symbol | Rule | Measured | Limit |
| --- | --- | --- | --- | --- |
| src/asf/api/decomposer.py | _parse_plan | function-complexity | 20 | 10 |
| src/asf/api/decomposer.py | _parse_plan | function-lines | 49 | 30 |
| src/asf/api/model_settings.py | (file) | banner-comment | 2 | 0 |
| src/asf/api/model_settings.py | ModelSettings.__init__ | function-nesting | 4 | 3 |
| src/asf/api/model_settings.py | ModelSettings.test | function-complexity | 11 | 10 |
| src/asf/api/model_settings.py | ModelSettings.test | function-lines | 47 | 30 |
| src/asf/api/model_settings.py | ModelSettings.update | function-complexity | 13 | 10 |
| src/asf/api/model_settings.py | ModelSettings.update | function-lines | 39 | 30 |
| src/asf/api/scheduler.py | (file) | banner-comment | 3 | 0 |
| src/asf/api/scheduler.py | RunScheduler | class-fields | 11 | 7 |
| src/asf/api/scheduler.py | RunScheduler._run | function-complexity | 16 | 10 |
| src/asf/api/scheduler.py | RunScheduler._run | function-lines | 40 | 30 |
| src/asf/api/scheduler.py | RunScheduler._run | function-nesting | 4 | 3 |
| src/asf/approval/policy.py | approval_policy_from_project | function-complexity | 20 | 10 |
| src/asf/approval/policy.py | approval_policy_from_project | function-lines | 110 | 30 |
| src/asf/approval/policy.py | approval_policy_from_project | function-nesting | 5 | 3 |
| src/asf/approval/service.py | ApprovalService.decide | function-complexity | 20 | 10 |
| src/asf/approval/service.py | ApprovalService.decide | function-lines | 68 | 30 |
| src/asf/approval/service.py | ApprovalService.request | function-lines | 46 | 30 |
| src/asf/configuration/errors.py | ConfigError.to_platform_errors | function-lines | 34 | 30 |
| src/asf/configuration/loader.py | load_platform_config | function-lines | 34 | 30 |
| src/asf/configuration/yamlio.py | load_yaml_mapping | function-complexity | 11 | 10 |
| src/asf/configuration/yamlio.py | load_yaml_mapping | function-lines | 45 | 30 |
| src/asf/configuration/yamlio.py | load_yaml_mapping | function-nesting | 4 | 3 |
| src/asf/configuration/yamlio.py | scan_secrets | function-complexity | 12 | 10 |
| src/asf/configuration/yamlio.py | scan_secrets | function-nesting | 4 | 3 |
| src/asf/evaluation/service.py | (file) | banner-comment | 7 | 0 |
| src/asf/evaluation/service.py | MetricsService | class-lines | 351 | 300 |
| src/asf/evaluation/service.py | MetricsService | class-methods | 13 | 10 |
| src/asf/evaluation/service.py | MetricsService.overview | function-complexity | 21 | 10 |
| src/asf/evaluation/service.py | MetricsService.overview | function-lines | 73 | 30 |
| src/asf/evaluation/service.py | MetricsService.record | function-lines | 43 | 30 |
| src/asf/evaluation/service.py | MetricsService.record_quality | function-params | 5 | 4 |
| src/asf/evaluation/service.py | _artifact_sample | function-lines | 36 | 30 |
| src/asf/evaluation/service.py | _artifact_sample | function-params | 5 | 4 |
| src/asf/evaluation/service.py | _find_verdict | function-complexity | 16 | 10 |
| src/asf/evaluation/service.py | _find_verdict | function-nesting | 4 | 3 |
| src/asf/integrations/gemini.py | GeminiModelGateway | class-fields | 13 | 7 |
| src/asf/integrations/gemini.py | GeminiModelGateway.__init__ | function-lines | 44 | 30 |
| src/asf/integrations/gemini.py | GeminiModelGateway.__init__ | function-params | 14 | 4 |
| src/asf/integrations/gemini.py | GeminiModelGateway._capture | function-params | 7 | 4 |
| src/asf/integrations/gemini.py | GeminiModelGateway._parse_response | function-lines | 33 | 30 |
| src/asf/integrations/gemini.py | GeminiModelGateway.complete | function-complexity | 17 | 10 |
| src/asf/integrations/gemini.py | GeminiModelGateway.complete | function-lines | 136 | 30 |
| src/asf/integrations/gemini.py | GeminiModelGateway.complete | function-nesting | 4 | 3 |
| src/asf/integrations/gemini.py | HttpTransport.post | function-params | 5 | 4 |
| src/asf/integrations/gemini.py | UrlLibTransport.post | function-params | 5 | 4 |
| src/asf/integrations/gemini.py | _NoRedirectHandler.redirect_request | function-params | 6 | 4 |
| src/asf/integrations/hosting/actions.py | _fail | function-params | 7 | 4 |
| src/asf/integrations/hosting/actions.py | build_hosting_actions | function-complexity | 23 | 10 |
| src/asf/integrations/hosting/actions.py | build_hosting_actions | function-lines | 167 | 30 |
| src/asf/integrations/hosting/actions.py | build_hosting_actions | function-params | 5 | 4 |
| src/asf/integrations/hosting/actions.py | build_hosting_actions.await_merge | function-lines | 57 | 30 |
| src/asf/integrations/hosting/actions.py | build_hosting_actions.run_pipeline | function-complexity | 13 | 10 |
| src/asf/integrations/hosting/actions.py | build_hosting_actions.run_pipeline | function-lines | 89 | 30 |
| src/asf/integrations/hosting/factory.py | build_provider | function-complexity | 19 | 10 |
| src/asf/integrations/hosting/factory.py | build_provider | function-lines | 45 | 30 |
| src/asf/integrations/hosting/github.py | (file) | banner-comment | 3 | 0 |
| src/asf/integrations/hosting/github.py | GitHubProvider.__init__ | function-params | 5 | 4 |
| src/asf/integrations/hosting/github.py | GitHubProvider.pipeline_status | function-complexity | 12 | 10 |
| src/asf/integrations/hosting/github.py | GitHubProvider.pipeline_status | function-lines | 40 | 30 |
| src/asf/integrations/hosting/github.py | GitHubProvider.pipeline_status | function-nesting | 4 | 3 |
| src/asf/integrations/hosting/github.py | GitHubProvider.push_changeset | function-lines | 58 | 30 |
| src/asf/integrations/hosting/gitlab.py | (file) | banner-comment | 2 | 0 |
| src/asf/integrations/hosting/gitlab.py | GitLabProvider.push_changeset | function-lines | 39 | 30 |
| src/asf/integrations/hosting/http.py | _error_message | function-complexity | 12 | 10 |
| src/asf/integrations/openai_compatible.py | OpenAICompatibleGateway | class-fields | 9 | 7 |
| src/asf/integrations/openai_compatible.py | OpenAICompatibleGateway.__init__ | function-params | 9 | 4 |
| src/asf/integrations/openai_compatible.py | OpenAICompatibleGateway._post_with_retries | function-lines | 42 | 30 |
| src/asf/integrations/openai_compatible.py | OpenAICompatibleGateway.complete | function-complexity | 20 | 10 |
| src/asf/integrations/openai_compatible.py | OpenAICompatibleGateway.complete | function-lines | 77 | 30 |
| src/asf/integrations/openai_compatible.py | UrlLibTransport.post | function-lines | 39 | 30 |
| src/asf/integrations/teams/cards.py | approval_card | function-lines | 69 | 30 |
| src/asf/integrations/teams/config.py | TeamsConfig.resolve_workflow_url | function-complexity | 14 | 10 |
| src/asf/integrations/teams/demo.py | demo_engine | function-lines | 52 | 30 |
| src/asf/integrations/teams/demo.py | run_demo | function-complexity | 11 | 10 |
| src/asf/integrations/teams/demo.py | run_demo | function-lines | 53 | 30 |
| src/asf/integrations/teams/workflow.py | create_app | function-complexity | 20 | 10 |
| src/asf/integrations/teams/workflow.py | create_app | function-lines | 95 | 30 |
| src/asf/integrations/teams/workflow.py | create_app.decide | function-lines | 39 | 30 |
| src/asf/state_machine/graph.py | (file) | numbered-comment | 3 | 0 |
| src/asf/state_machine/graph.py | build_graph | function-lines | 64 | 30 |
| src/asf/state_machine/machine.py | (file) | numbered-comment | 4 | 0 |
| src/asf/state_machine/machine.py | apply | function-complexity | 17 | 10 |
| src/asf/state_machine/machine.py | apply | function-lines | 53 | 30 |
| src/asf/storage/mariadb.py | (file) | banner-comment | 2 | 0 |
| src/asf/storage/mariadb.py | (file) | file-lines | 534 | 500 |
| src/asf/storage/mariadb.py | MariaDbExecutionStore | class-lines | 317 | 300 |
| src/asf/storage/mariadb.py | MariaDbExecutionStore.list_execution_summaries | function-lines | 44 | 30 |
| src/asf/storage/mariadb.py | MariaDbExecutionStore.save_execution | function-lines | 34 | 30 |
| src/asf/storage/mariadb.py | MariaDbExecutionStore.save_execution | function-nesting | 4 | 3 |
| src/asf/workflow/definition.py | (file) | numbered-comment | 3 | 0 |
| src/asf/workflow/definition.py | WorkflowDefinition._validate_workflow_definition | function-complexity | 13 | 10 |
| src/asf/workflow/definition.py | WorkflowDefinition._validate_workflow_definition | function-lines | 77 | 30 |
| src/asf/workflow/definition.py | WorkflowStepDef._validate_step | function-complexity | 12 | 10 |
| src/asf/workflow/definition.py | WorkflowStepDef._validate_step | function-lines | 67 | 30 |


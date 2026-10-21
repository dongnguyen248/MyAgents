# Workflow Stages and State Machine

## 1. Generated Stages Rule (W3)

Stages are **generated** from the declarative workflow definition and are never hard-coded in platform code.
- **Global stages**: `NEW`, `COMPLETED`, `FAILED`, `CANCELLED`.
- **Step stages**:
  - For each step with base stage name `S`:
    - If `requiresApproval` is `true`: generates 5 stages:
      - `S_DRAFT` (initial work by the agent)
      - `S_REVIEW` (awaiting human review)
      - `S_REJECTED` (review rejected or changes requested)
      - `S_APPROVED` (approval granted)
      - `S_ESCALATED` (rework limit reached)
    - If `requiresApproval` is `false`: generates exactly 1 stage: `S`.

## 2. Reference Workflow Stages (`software-development`)

The reference workflow (`workflows/software-development.yaml`) contains 8 steps (3 approval steps, 5 plain steps) and generates exactly 24 stages in order:

1. `NEW` (Initial global stage)
2. `SPEC_DRAFT`
3. `SPEC_REVIEW`
4. `SPEC_REJECTED`
5. `SPEC_APPROVED`
6. `SPEC_ESCALATED`
7. `PLAN_DRAFT`
8. `PLAN_REVIEW`
9. `PLAN_REJECTED`
10. `PLAN_APPROVED`
11. `PLAN_ESCALATED`
12. `TASK_DRAFT`
13. `TASK_REVIEW`
14. `TASK_REJECTED`
15. `TASK_APPROVED`
16. `TASK_ESCALATED`
17. `IMPLEMENTING`
18. `CODE_REVIEW`
19. `TESTING`
20. `CI`
21. `READY_TO_MERGE`
22. `COMPLETED` (Terminal success stage)
23. `FAILED` (Terminal failure stage)
24. `CANCELLED` (Terminal cancellation stage)

## 3. Triggers (W4)

Triggers are defined by `Trigger` (`StrEnum`):
- `START`: Starts execution from `NEW` to the entry stage of the first step.
- `COMPLETE`: Step execution finished; moves a draft step to review, or completes a plain step to the next step.
- `APPROVED`: Reviewer approved the artifact; moves from `S_REVIEW` to `S_APPROVED`.
- `REJECTED`: Reviewer rejected the artifact; moves from `S_REVIEW` to `S_REJECTED`.
- `REQUEST_CHANGES`: Reviewer requested modifications; moves from `S_REVIEW` to `S_REJECTED`.
- `ADVANCE`: Advances from `S_APPROVED` to the entry stage of the next step (or `COMPLETED` if last).
- `REVISE`: Requests rework from `S_REJECTED`; moves to `S_DRAFT` if within limit, or escalates to `S_ESCALATED`.
- `RESUME`: Resumes an escalated step from `S_ESCALATED` back to `S_DRAFT` and resets revisions.
- `FAIL`: Fails execution from any non-terminal stage to `FAILED`.
- `CANCEL`: Cancels execution from any non-terminal stage to `CANCELLED`.

> Note: `APPROVED`, `REJECTED`, and `REQUEST_CHANGES` trigger values equal the `ApprovalDecision.decision` schema enum.

## 4. Transitions (W5)

Let `entry(step)` be `S_DRAFT` if the step requires approval, else `S`.
Let `entry(next)` be the entry stage of the next step, or `COMPLETED` for the final step.

| Source Stage | Trigger | Target Stage | Guard |
|---|---|---|---|
| `NEW` | `START` | `entry(first step)` | none |
| `S_DRAFT` | `COMPLETE` | `S_REVIEW` | none |
| `S_REVIEW` | `APPROVED` | `S_APPROVED` | none |
| `S_REVIEW` | `REJECTED` | `S_REJECTED` | none |
| `S_REVIEW` | `REQUEST_CHANGES` | `S_REJECTED` | none |
| `S_REJECTED` | `REVISE` | `S_DRAFT` | `within_limit` |
| `S_REJECTED` | `REVISE` | `S_ESCALATED` | `limit_reached` |
| `S_ESCALATED` | `RESUME` | `S_DRAFT` | none |
| `S_APPROVED` | `ADVANCE` | `entry(next step)` | none |
| `S` (plain step) | `COMPLETE` | `entry(next step)` | none |
| Non-terminal stage | `FAIL` | `FAILED` | none |
| Non-terminal stage | `CANCEL` | `CANCELLED` | none |
| Terminal (`COMPLETED`, `FAILED`, `CANCELLED`) | *none* | *none* | *terminal* |

## 5. Revisions and Rework (W6)

Rework cycles are tracked per step in `RunState.revisions: Mapping[str, int]`:
- When `REVISE` is triggered from `S_REJECTED`:
  - If `revisions[step_id] < step.maxRevisions`: transitions to `S_DRAFT` and `revisions[step_id]` increments by 1 (`within_limit` guard).
  - If `revisions[step_id] >= step.maxRevisions`: transitions to `S_ESCALATED` with the revision count unchanged (`limit_reached` guard).
- When `RESUME` is triggered from `S_ESCALATED`: transitions to `S_DRAFT` and resets `revisions[step_id]` to 0.

## 6. Coarse Status Mapping (W7)

Coarse status is deterministically derived from the stage kind (`StageKind`):

| Stage Kind | Generated Stage Examples | Task.status | WorkflowRun.status |
|---|---|---|---|
| `INITIAL` | `NEW` | `NEW` | `PENDING` |
| `DRAFT` | `SPEC_DRAFT`, `PLAN_DRAFT` | `IN_PROGRESS` | `RUNNING` |
| `REVIEW` | `SPEC_REVIEW`, `PLAN_REVIEW` | `WAITING` | `WAITING` |
| `REJECTED` | `SPEC_REJECTED`, `PLAN_REJECTED` | `IN_PROGRESS` | `RUNNING` |
| `APPROVED` | `SPEC_APPROVED`, `PLAN_APPROVED` | `IN_PROGRESS` | `RUNNING` |
| `ESCALATED` | `SPEC_ESCALATED`, `PLAN_ESCALATED` | `WAITING` | `WAITING` |
| `STEP` | `IMPLEMENTING`, `TESTING` | `IN_PROGRESS` | `RUNNING` |
| `COMPLETED` | `COMPLETED` | `COMPLETED` | `COMPLETED` |
| `FAILED` | `FAILED` | `FAILED` | `FAILED` |
| `CANCELLED` | `CANCELLED` | `CANCELLED` | `CANCELLED` |

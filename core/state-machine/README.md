# core/state-machine/
**Responsibility:** workflow states and allowed transitions.

```text
NEW -> SPEC_DRAFT -> SPEC_REVIEW -> (SPEC_REJECTED -> SPEC_DRAFT | SPEC_APPROVED)
    -> PLAN_DRAFT -> PLAN_REVIEW -> (PLAN_REJECTED -> PLAN_DRAFT | PLAN_APPROVED)
    -> TASK_DRAFT -> TASK_REVIEW -> TASK_APPROVED
    -> IMPLEMENTING -> CODE_REVIEW -> TESTING -> CI -> READY_TO_MERGE -> COMPLETED
(any) -> FAILED
```
See `states.md`. Structure only.

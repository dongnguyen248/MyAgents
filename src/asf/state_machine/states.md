# Workflow states (draft)

NEW, SPEC_DRAFT, SPEC_REVIEW, SPEC_REJECTED, SPEC_APPROVED,
PLAN_DRAFT, PLAN_REVIEW, PLAN_REJECTED, PLAN_APPROVED,
TASK_DRAFT, TASK_REVIEW, TASK_APPROVED,
IMPLEMENTING, CODE_REVIEW, TESTING, CI, READY_TO_MERGE, COMPLETED, FAILED

Open question for the next step: should the state set be fixed, or generated per workflow
(`<STAGE>_DRAFT/REVIEW/REJECTED/APPROVED`)? Generated stages reduce duplication.

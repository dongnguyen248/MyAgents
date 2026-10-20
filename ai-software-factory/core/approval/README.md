# core/approval/
**Responsibility:** generic human approval, reusable for Spec, Plan, Task, Code Review, production deployment.

Decisions: `APPROVE`, `REJECT`, `FEEDBACK`.
Depends only on an abstract channel interface (see `integrations/notifications/`); never on Teams directly.

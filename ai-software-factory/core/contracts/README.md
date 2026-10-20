# core/contracts/
**Responsibility:** the stable interfaces the platform is built around.

Planned contracts: Agent (input/output), Artifact, ApprovalRequest/Decision, WorkflowEvent, Skill, LLMProvider, GitProvider, NotificationChannel, CIProvider.
Agents and integrations depend on contracts, never on each other.
*(Added beyond the original structure; see docs/architecture.)*

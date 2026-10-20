# src/asf/agents/

Reusable agents. Each is structured identically:

```text
<agent>/
├── README.md        purpose, input/output contract, boundaries
├── __init__.py      package marker
├── prompts/         prompt templates (provider-neutral)
├── instructions/    behavioural rules and policies
├── tools/           tool declarations the agent may use (via contracts)
├── skills/          skill selection/overrides for this agent
└── tests/           agent-level tests / evaluation cases
```

Rules:
1. No project-specific content.
2. No direct calls to other agents; the orchestrator mediates via artifacts + approvals.
3. No direct dependency on GitLab/Teams/LLM vendors.
4. Approval is handled by the platform.
5. Agents never perform direct side effects; they act only through ports in `contracts/ports.md`.

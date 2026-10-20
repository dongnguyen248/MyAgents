# agents/
Reusable agents. Each is structured identically:

```text
<agent>/
├── README.md        purpose, input/output contract, boundaries
├── prompts/         prompt templates (provider-neutral)
├── instructions/    behavioural rules and policies
├── tools/           tool declarations the agent may use (via contracts)
├── skills/          skill selection/overrides for this agent
└── tests/           agent-level tests / evaluation cases
```
Rules: no project-specific content; no direct calls to other agents; no direct dependency on GitLab/Teams/LLM vendors; approval is handled by the platform.

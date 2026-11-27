import type { AgentType } from '../types/agent';

export interface AgentMeta {
  label: string;
  description: string;
}

/**
 * Presentational copy for the agent catalogue: what each platform agent is
 * responsible for. Runtime state (status, metrics, current task) comes from the
 * API; this file only answers "what does this agent do", which no contract
 * field carries today.
 */
const META: Record<AgentType, AgentMeta> = {
  spec: {
    label: 'Spec',
    description:
      'Turns a requirement into a SPEC.md: goal, scope, constraints and the open questions a human must answer.',
  },
  plan: {
    label: 'Plan',
    description:
      'Turns an approved SPEC into a PLAN.md: approach, impacted components, risks and milestones.',
  },
  task: {
    label: 'Task',
    description:
      'Breaks an approved PLAN into small, independently implementable TASK items with a definition of done.',
  },
  implement: {
    label: 'Implement',
    description:
      'Implements exactly one approved TASK, following the project’s enabled skills and staying inside the task scope.',
  },
  review: {
    label: 'Code Review',
    description:
      'Reviews the change set against the TASK, the SPEC and the project rules, and writes a CODE_REVIEW.md.',
  },
  test: {
    label: 'Test',
    description:
      'Runs the project’s configured test commands in the sandbox and records the verdict in a TEST_REPORT.md.',
  },
  fix: {
    label: 'Fix',
    description:
      'Resolves review findings, failing tests and CI failures with the smallest change that clears them.',
  },
  'artifact-review': {
    label: 'Artifact Review',
    description:
      'Independently reviews SPEC, PLAN and TASK artifacts and returns findings; the verdict itself is computed in code.',
  },
};

export const AGENT_TYPES: AgentType[] = [
  'spec',
  'plan',
  'task',
  'implement',
  'review',
  'test',
  'fix',
  'artifact-review',
];

const FALLBACK: AgentMeta = {
  label: 'Agent',
  description: 'No description is registered for this agent type.',
};

export function agentMeta(type: AgentType): AgentMeta {
  return META[type] ?? FALLBACK;
}

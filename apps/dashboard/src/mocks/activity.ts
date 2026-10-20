import type { ActivityEvent, ActivityLevel, ActivitySourceKind } from '../types/activity';
import { agents } from './agents';
import { secondsAgo } from './time';

const SYSTEM: Record<string, [ActivitySourceKind, string]> = {
  orchestrator: ['orchestrator', 'Orchestrator'],
  approval: ['approval', 'Approval Engine'],
  gitlab: ['integration', 'GitLab'],
  ci: ['integration', 'CI Pipeline'],
};

let counter = 0;
export function makeEvent(secAgo: number, source: string, taskId: string | undefined, level: ActivityLevel, message: string): ActivityEvent {
  const agent = agents.find((a) => a.id === source);
  const [sourceKind, sourceLabel] = agent ? (['agent', agent.name] as [ActivitySourceKind, string]) : SYSTEM[source];
  return {
    id: `evt-${++counter}`,
    timestamp: secondsAgo(secAgo),
    sourceKind, sourceId: source, sourceLabel,
    taskId,
    projectId: taskId?.split('-')[0].toLowerCase(),
    level, message,
  };
}

type Row = [number, string, string | undefined, ActivityLevel, string];
const rows: Row[] = [
  [1112, 'implement-agent', 'VHPC-1023', 'info', 'Started VHPC-1023'],
  [1096, 'implement-agent', 'VHPC-1023', 'info', 'Read SPEC.md and TASK-004'],
  [1020, 'implement-agent', 'VHPC-1023', 'info', 'Generated implementation plan'],
  [870, 'implement-agent', 'VHPC-1023', 'success', 'Modified SalesPlanService.java'],
  [790, 'implement-agent', 'VHPC-1023', 'success', 'Created SalesPlanController.java'],
  [610, 'implement-agent', 'VHPC-1023', 'info', 'Running unit tests'],
  [420, 'implement-agent', 'VHPC-1023', 'warn', '2 unit tests failing; applying fix'],
  [300, 'implement-agent', 'VHPC-1023', 'info', 'Modified SalesPlanMapper.java'],
  [95, 'gitlab', 'VHPC-1023', 'info', 'Branch feature/vhpc-1023 pushed'],
  [1700, 'spec-agent', 'VHPC-1024', 'info', 'Started SPEC for VHPC-1024'],
  [1500, 'spec-agent', 'VHPC-1024', 'success', 'SPEC.md draft generated'],
  [300, 'approval', 'VHPC-1024', 'info', 'Spec approval requested via Teams'],
  [2400, 'plan-agent', 'VNPC-2041', 'success', 'PLAN.md draft generated'],
  [720, 'approval', 'VNPC-2041', 'info', 'Plan approval requested via Teams'],
  [3300, 'plan-agent', 'VNPC-2040', 'info', 'Started PLAN draft'],
  [1900, 'task-agent', 'ERP-3321', 'success', 'Generated 6 tasks from approved plan'],
  [120, 'approval', 'ERP-3321', 'info', 'Task approval requested via Teams'],
  [2600, 'task-agent', 'ERP-3319', 'warn', 'Task breakdown rejected: missing acceptance criteria'],
  [2580, 'approval', 'ERP-3319', 'warn', 'Reviewer requested changes'],
  [500, 'task-agent', 'VNPC-2042', 'info', 'Decomposing approved plan into tasks'],
  [640, 'test-agent', 'VHPC-1025', 'info', 'Started unit tests'],
  [560, 'test-agent', 'VHPC-1025', 'success', 'Unit tests passed (84/84)'],
  [330, 'test-agent', 'VHPC-1025', 'info', 'Started integration tests'],
  [200, 'test-agent', 'ERP-3320', 'error', 'Integration test runner crashed: timeout after 600s'],
  [190, 'orchestrator', 'ERP-3320', 'error', 'Test Agent reported ERROR; step marked failed'],
  [1500, 'review-agent', 'VNPC-2038', 'success', 'Review completed: 3 comments'],
  [1400, 'approval', 'VNPC-2038', 'info', 'Code review approval requested'],
  [900, 'gitlab', 'VNPC-2039', 'info', 'Merge request !214 opened'],
  [780, 'ci', 'VNPC-2039', 'info', 'Pipeline #8812 started'],
  [60, 'orchestrator', 'VNPC-2039', 'info', 'Waiting for CI'],
  [3000, 'ci', 'VNPC-2043', 'success', 'Pipeline #8790 passed'],
  [2400, 'orchestrator', 'VNPC-2043', 'info', 'Quality gate passed; ready to merge'],
  [2700, 'implement-agent', 'VHPC-1022', 'error', 'Implementation failed after 3 revisions'],
  [2690, 'orchestrator', 'VHPC-1022', 'error', 'Workflow marked FAILED'],
  [40, 'review-agent', 'VNPC-2038', 'info', 'Re-checking migration rollback path'],
  [15, 'orchestrator', undefined, 'info', 'Heartbeat: 5 agents active, 1 in error'],
];

export const activity: ActivityEvent[] = rows
  .map(([s, src, t, l, m]) => makeEvent(s, src, t, l, m))
  .sort((a, b) => b.timestamp.localeCompare(a.timestamp));

/** Pool used by the mock live stream to emit new events over time. */
type LiveRow = [string, string | undefined, ActivityLevel, string];
export const livePool: LiveRow[] = [
  ['implement-agent', 'VHPC-1023', 'info', 'Modified SalesPlanRepository.java'],
  ['implement-agent', 'VHPC-1023', 'info', 'Running unit tests'],
  ['plan-agent', 'VNPC-2040', 'info', 'Drafting milestones section'],
  ['review-agent', 'VNPC-2038', 'success', 'Review comment resolved'],
  ['ci', 'VNPC-2039', 'info', 'Pipeline #8812: stage "test" running'],
  ['orchestrator', 'VNPC-2039', 'info', 'Waiting for CI'],
  ['test-agent', 'VHPC-1025', 'success', 'Integration tests passed (21/21)'],
  ['task-agent', 'VNPC-2042', 'info', 'Wrote TASK-003.md'],
];

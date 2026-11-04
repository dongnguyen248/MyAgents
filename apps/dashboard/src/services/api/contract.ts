import type { ActivityEvent, ActivityFilter } from '../../types/activity';
import type { Agent, AgentConfig, AgentRun } from '../../types/agent';
import type { Approval, ApprovalDecisionInput } from '../../types/approval';
import type { MetricsOverview } from '../../types/metrics';
import type { Project, ProjectProfileInput } from '../../types/project';
import type { Task, TaskFilter } from '../../types/task';
import type { Workflow } from '../../types/workflow';

export type Unsubscribe = () => void;

/**
 * The single seam between the dashboard and the AI Software Factory backend.
 * Implementations: mockApi (in-browser) and httpApi (REST). Nothing above this
 * layer knows which one is active.
 */
export interface FactoryApi {
  listAgents(): Promise<Agent[]>;
  getAgent(id: string): Promise<Agent | undefined>;
  getAgentConfig(id: string): Promise<AgentConfig | undefined>;
  getAgentRuns(id: string): Promise<AgentRun[]>;

  listTasks(filter?: TaskFilter): Promise<Task[]>;
  getTask(id: string): Promise<Task | undefined>;

  listWorkflows(): Promise<Workflow[]>;
  getWorkflow(id: string): Promise<Workflow | undefined>;

  listProjects(): Promise<Project[]>;
  createProject(input: ProjectProfileInput): Promise<Project>;

  listApprovals(): Promise<Approval[]>;
  decideApproval(id: string, input: ApprovalDecisionInput): Promise<Approval>;

  listActivity(filter?: ActivityFilter): Promise<ActivityEvent[]>;
  /** Push channel. Mock: timer. Later: WebSocket or Server-Sent Events. */
  subscribeActivity(onEvent: (e: ActivityEvent) => void): Unsubscribe;

  getMetricsOverview(): Promise<MetricsOverview>;
}

import type { ActivityEvent, ActivityFilter } from '../../types/activity';
import type { Agent, AgentConfig, AgentInput, AgentRun } from '../../types/agent';
import type { AgentModelInput, ModelSettings } from '../../types/agentSetup';
import type { Approval, ApprovalDecisionInput } from '../../types/approval';
import type { MapEvent, MapSnapshot } from '../../types/map';
import type { MetricsOverview } from '../../types/metrics';
import type { Project, ProjectProfileInput } from '../../types/project';
import type { LlmModelRequest, LlmProfile, LlmProfileInput, LlmTestResult } from '../../types/llm';
import type { Skill } from '../../types/skill';
import type { StartRunInput, Task, TaskFilter } from '../../types/task';
import type { RunDiagnostics, RunReviews, Workflow } from '../../types/workflow';

export type Unsubscribe = () => void;

/**
 * The single seam between the dashboard and the AI Software Agents backend.
 * Implementations: mockApi (in-browser) and httpApi (REST). Nothing above this
 * layer knows which one is active.
 */
export interface FactoryApi {
  listAgents(): Promise<Agent[]>;
  getAgent(id: string): Promise<Agent | undefined>;
  getAgentConfig(id: string): Promise<AgentConfig | undefined>;
  getAgentRuns(id: string): Promise<AgentRun[]>;
  /** Creates a custom agent. Backends that do not implement POST /agents answer 404/405. */
  createAgent(input: AgentInput): Promise<Agent>;
  /** The skill catalogue (skills/<id>/SKILL.md); [] when the backend has none. */
  listSkills(): Promise<Skill[]>;
  getAgentSkills(id: string): Promise<string[]>;
  saveAgentSkills(id: string, skills: string[]): Promise<string[]>;
  getModelSettings(): Promise<ModelSettings>;
  saveAgentModel(input: AgentModelInput): Promise<ModelSettings>;
  readSkillFile(id: string, path: string): Promise<string>;
  saveSkillFile(id: string, path: string, content: string): Promise<void>;

  /** Named model profiles; the agents point at one of these. */
  listLlmProfiles(): Promise<LlmProfile[]>;
  saveLlmProfile(input: LlmProfileInput): Promise<LlmProfile>;
  deleteLlmProfile(id: string): Promise<void>;
  /** Model ids the endpoint offers, for the model select. */
  loadLlmModels(request: LlmModelRequest): Promise<string[]>;
  testLlmProfile(id: string): Promise<LlmTestResult>;
  /** Points one agent at a profile; null clears the assignment. */
  assignAgentProfile(agentId: string, profileId: string | null): Promise<Agent>;

  listTasks(filter?: TaskFilter): Promise<Task[]>;
  getTask(id: string): Promise<Task | undefined>;
  /** Start a workflow run for a new task; resolves to its workflow view. */
  startRun(input: StartRunInput): Promise<Workflow>;

  listWorkflows(): Promise<Workflow[]>;
  getWorkflow(id: string): Promise<Workflow | undefined>;
  getRunDiagnostics(runId: string): Promise<RunDiagnostics | undefined>;
  getRunReviews(runId: string): Promise<RunReviews | undefined>;
  /** Advance a run by one engine step; resolves to its workflow view. */
  tickRun(runId: string): Promise<Workflow>;
  /** Start a fresh run of a finished run's task with its original inputs. */
  retryRun(runId: string): Promise<Workflow>;
  /** Continue a failed run from its failed step, keeping its artifacts and approvals. */
  resumeRun(runId: string): Promise<Workflow>;
  /** Cancel an active run; a run mid-step stops once that step returns. */
  cancelRun(runId: string): Promise<Workflow>;
  /** Grant an escalated run a fresh fix budget and drive it on (reason required; guidance reaches the producer as feedback). */
  resumeEscalation(runId: string, reason: string, guidance?: string): Promise<Workflow>;
  /** Approve an escalated gate's artifact anyway (reason required, recorded as the decision comment). */
  approveEscalation(runId: string, reason: string): Promise<Workflow>;
  /** Skip a no-tests run's test step (reason required); scope 'run' also covers later items that collect no tests. */
  skipTests(runId: string, reason: string, scope?: 'item' | 'run'): Promise<Workflow>;
  /** Replace a no-tests run's test commands (run-scoped override) and retest. */
  replaceTestCommands(runId: string, commands: string[][], reason?: string): Promise<Workflow>;
  /** Recover a run whose step was interrupted; replay it or fail the run. */
  recoverRun(runId: string, reason: string, retryInterrupted: boolean): Promise<Workflow>;
  /** (Re)start the run's background driver; idempotent. */
  driveRun(runId: string): Promise<Workflow>;
  /** Fail an escalated or stalled run under operator control (reason required). */
  failRun(runId: string, reason: string): Promise<Workflow>;
  /** Pause a run at the next step boundary. */
  pauseRun(runId: string): Promise<Workflow>;
  /** Continue a paused run. */
  continueRun(runId: string): Promise<Workflow>;

  listProjects(): Promise<Project[]>;
  createProject(input: ProjectProfileInput): Promise<Project>;
  updateProject(id: string, input: ProjectProfileInput): Promise<Project>;
  deleteProject(id: string): Promise<void>;

  listApprovals(): Promise<Approval[]>;
  decideApproval(id: string, input: ApprovalDecisionInput): Promise<Approval>;

  listActivity(filter?: ActivityFilter): Promise<ActivityEvent[]>;
  /** Push channel. Mock: timer. Later: WebSocket or Server-Sent Events. */
  subscribeActivity(onEvent: (e: ActivityEvent) => void): Unsubscribe;

  /** Live map snapshot for one run; undefined when the run or map is absent. */
  getMapSnapshot(runId: string): Promise<MapSnapshot | undefined>;
  /** Live map pulse stream for one run (SSE on the real backend). */
  subscribeMapEvents(runId: string, onEvent: (e: MapEvent) => void): Unsubscribe;

  getMetricsOverview(): Promise<MetricsOverview>;
}

import type { ProjectMetrics } from './metrics';
import type { CiStatus } from './task';

export interface Project {
  id: string;
  name: string;
  repositoryProvider: string;
  /** Repository link for the hosting/CI integration (profile `repository.url`); '' = none. */
  repositoryUrl: string;
  /** Local folder the agents work in (profile `repository.path`); '' = none. */
  repositoryPath: string;
  /** How runs use the local folder (profile `repository.workspaceMode`): direct | worktree | auto. */
  workspaceMode: string;
  /** Direct mode only: keep a failed/cancelled run's files instead of reverting them. */
  keepChangesOnFailure: boolean;
  /** Whether a hosting (GitLab/GitHub) access token is available for this project. */
  hostingTokenConfigured?: boolean;
  /** Last-4 hint of the dashboard-stored token; null when it comes from the backend env. */
  hostingTokenHint?: string | null;
  /** Configured test commands as argv lists (profile `configuration.testCommands`). */
  testCommands: string[][];
  technologies: string[];
  description: string;
  workflow: string;
  enabledSkills: string[];
  technologyGroups: Record<string, string[]>;
  approvalChannel: string;
  /** Profile `configuration.approval.mode`: '' = workflow default. */
  approvalMode: string;
  /** Profile `configuration.approval.maxRevisions`; null = default. */
  approvalMaxRevisions: number | null;
  /** Profile `configuration.approval.onExhausted`: '' = default (escalate). */
  approvalOnExhausted: string;
  agentIds: string[];
  ci: CiStatus;
  ciFailures24h: number;
  metrics: ProjectMetrics;
}

/** Creation payload: the project-profile shape of `projects/<id>.yaml`. */
export interface ProjectProfileInput {
  id: string;
  name: string;
  description?: string;
  repository: {
    provider: string;
    path?: string;
    url?: string;
    workspaceMode?: string;
    keepChangesOnFailure?: boolean;
  };
  technology: { backend: string[]; frontend: string[] };
  workflow: string;
  enabledSkills: string[];
  configuration: {
    approval?: { channel: string; mode?: string; maxRevisions?: number; onExhausted?: string };
    testCommands?: string[][];
  };
  /** Write-only: a new hosting token to store on the backend for this project. */
  hostingToken?: string;
  /** Write-only: remove the stored hosting token on save. */
  clearHostingToken?: boolean;
  /** Read-only status carried into the edit form (never sent back as a change). */
  hostingTokenConfigured?: boolean;
  hostingTokenHint?: string | null;
}

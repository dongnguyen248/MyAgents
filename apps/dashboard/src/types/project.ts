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
  repository: { provider: string; path?: string; url?: string };
  technology: { backend: string[]; frontend: string[] };
  workflow: string;
  enabledSkills: string[];
  configuration: { approval?: { channel: string }; testCommands?: string[][] };
  /** Write-only: a new hosting token to store on the backend for this project. */
  hostingToken?: string;
  /** Write-only: remove the stored hosting token on save. */
  clearHostingToken?: boolean;
  /** Read-only status carried into the edit form (never sent back as a change). */
  hostingTokenConfigured?: boolean;
  hostingTokenHint?: string | null;
}

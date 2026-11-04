import type { ProjectMetrics } from './metrics';
import type { CiStatus } from './task';

export interface Project {
  id: string;
  name: string;
  repositoryProvider: string;
  /** Local folder the agents work in (profile `repository.path`); '' = none. */
  repositoryPath: string;
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
  repository: { provider: string; path?: string };
  technology: { backend: string[]; frontend: string[] };
  workflow: string;
  enabledSkills: string[];
  configuration: { approval?: { channel: string }; testCommands?: string[][] };
}

import type { ProjectMetrics } from './metrics';
import type { CiStatus } from './task';

export interface Project {
  id: string;
  name: string;
  repositoryProvider: string;
  technologies: string[];
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
  repository: { provider: string };
  technology: { backend: string[]; frontend: string[] };
  workflow: string;
  enabledSkills: string[];
  configuration: { approval?: { channel: string } };
}

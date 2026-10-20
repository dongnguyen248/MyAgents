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

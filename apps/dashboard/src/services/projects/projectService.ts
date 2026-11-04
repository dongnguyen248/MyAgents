import type { ProjectProfileInput } from '../../types/project';
import { api } from '../api';

export const listProjects = () => api.listProjects();

export const createProject = (input: ProjectProfileInput) => api.createProject(input);

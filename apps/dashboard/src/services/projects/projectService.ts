import type { ProjectProfileInput } from '../../types/project';
import { api } from '../api';

export const listProjects = () => api.listProjects();

export const createProject = (input: ProjectProfileInput) => api.createProject(input);

export const updateProject = (id: string, input: ProjectProfileInput) => api.updateProject(id, input);

export const deleteProject = (id: string) => api.deleteProject(id);

import { useAsync } from '../../hooks/useAsync';
import * as svc from '../../services/projects/projectService';

export const useProjects = () => useAsync(svc.listProjects);

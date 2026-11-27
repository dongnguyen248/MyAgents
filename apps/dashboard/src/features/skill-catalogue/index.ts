import { useAsync } from '../../hooks/useAsync';
import * as svc from '../../services/skills/skillService';

export const useSkills = () => useAsync(svc.listSkills);

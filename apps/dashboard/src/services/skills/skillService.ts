import type { Skill } from '../../types/skill';
import { api } from '../api';

export const listSkills = (): Promise<Skill[]> => api.listSkills();

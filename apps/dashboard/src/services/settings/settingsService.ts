import type { ModelSettingsInput } from '../../types/settings';
import { api } from '../api';

export const getModelSettings = () => api.getModelSettings();

export const updateModelSettings = (input: ModelSettingsInput) => api.updateModelSettings(input);

export const testModelSettings = () => api.testModelSettings();

import { useAsync } from '../../hooks/useAsync';
import * as svc from '../../services/settings/settingsService';

export const useModelSettings = () => useAsync(svc.getModelSettings);

export const updateModelSettings = svc.updateModelSettings;

export const testModelSettings = svc.testModelSettings;

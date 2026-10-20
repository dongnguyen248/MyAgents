import { useAsync } from '../../hooks/useAsync';
import * as svc from '../../services/metrics/metricsService';

export const useMetricsOverview = () => useAsync(svc.getMetricsOverview);
export const useFactorySummary = () => useAsync(svc.getFactorySummary);

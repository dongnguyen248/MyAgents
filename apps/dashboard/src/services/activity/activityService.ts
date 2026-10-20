import type { ActivityFilter } from '../../types/activity';
import { api } from '../api';

export const listActivity = (filter?: ActivityFilter) => api.listActivity(filter);
export const subscribeActivity = api.subscribeActivity.bind(api);

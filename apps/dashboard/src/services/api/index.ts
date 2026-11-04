import type { FactoryApi } from './contract';
import { createHttpApi } from './httpApi';
import { mockApi } from './mockApi';

const baseUrl = import.meta.env.VITE_API_BASE_URL as string | undefined;

/** The one place that decides mock vs real backend. */
export const api: FactoryApi = baseUrl ? createHttpApi(baseUrl) : mockApi;

/** The configured backend base URL, or undefined when running on mock data. */
export const backendBaseUrl = baseUrl;
export type { FactoryApi, Unsubscribe } from './contract';

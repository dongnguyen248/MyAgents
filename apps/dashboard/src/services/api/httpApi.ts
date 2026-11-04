import type { Project } from '../../types/project';
import type { FactoryApi } from './contract';

/**
 * REST implementation of FactoryApi. Endpoint paths are a proposal for the future
 * backend contract (see docs/architecture). Enabled by setting VITE_API_BASE_URL.
 */
export function createHttpApi(baseUrl: string): FactoryApi {
  const qs = (o: object = {}) => {
    const p = new URLSearchParams();
    Object.entries(o).forEach(([k, v]) => v !== undefined && v !== '' && p.set(k, String(v)));
    const s = p.toString();
    return s ? `?${s}` : '';
  };
  const request = async (path: string, init?: RequestInit): Promise<Response> => {
    const res = await fetch(baseUrl + path, { headers: { 'Content-Type': 'application/json' }, ...init });
    if (!res.ok && res.status !== 404) throw new Error(`${init?.method ?? 'GET'} ${path} -> ${res.status}`);
    return res;
  };
  const send = async <T>(path: string, method: string, body?: unknown): Promise<T> => {
    const res = await fetch(baseUrl + path, {
      method,
      headers: { 'Content-Type': 'application/json' },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    });
    if (!res.ok) {
      const data = (await res.json().catch(() => null)) as { detail?: string } | null;
      throw new Error(data?.detail ?? `${method} ${path} -> ${res.status}`);
    }
    return (res.status === 204 ? undefined : await res.json()) as T;
  };
  const get = async <T>(path: string): Promise<T> => (await request(path)).json() as Promise<T>;
  const getOpt = async <T>(path: string): Promise<T | undefined> => {
    const res = await request(path);
    return res.status === 404 ? undefined : ((await res.json()) as T);
  };

  return {
    listAgents: () => get('/agents'),
    getAgent: (id) => getOpt(`/agents/${id}`),
    getAgentConfig: (id) => getOpt(`/agents/${id}/config`),
    getAgentRuns: (id) => get(`/agents/${id}/runs`),

    listTasks: (f) => get(`/tasks${qs(f)}`),
    getTask: (id) => getOpt(`/tasks/${id}`),

    listWorkflows: () => get('/workflows'),
    getWorkflow: (id) => getOpt(`/workflows/${id}`),

    listProjects: () => get('/projects'),
    createProject: (input) => send<Project>('/projects', 'POST', input),
    updateProject: (id, input) => send<Project>(`/projects/${id}`, 'PUT', input),
    deleteProject: (id) => send<void>(`/projects/${id}`, 'DELETE'),

    listApprovals: () => get('/approvals'),
    decideApproval: async (id, input) =>
      (await request(`/approvals/${id}/decision`, { method: 'POST', body: JSON.stringify(input) })).json(),

    listActivity: (f) => get(`/activity${qs(f)}`),
    subscribeActivity: (onEvent) => {
      // Server-Sent Events from the backend's GET /events stream. Errors are
      // swallowed: EventSource reconnects on its own and a dead stream must
      // never break the dashboard.
      const source = new EventSource(`${baseUrl}/events`);
      source.onmessage = (msg) => {
        try {
          onEvent(JSON.parse(msg.data));
        } catch {
          // Ignore malformed frames rather than tearing down the stream.
        }
      };
      source.onerror = () => undefined;
      return () => source.close();
    },

    getMetricsOverview: () => get('/metrics/overview'),
  };
}

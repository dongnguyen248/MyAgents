# AI Software Agents – Dashboard (Control Tower)

Generic web UI to observe and manage AI agents, tasks, workflows, approvals and projects.
**UI-first:** runs entirely on mock data. No backend, auth, LLM, GitLab, Teams or WebSocket code exists here.

## Run

```bash
cd apps/dashboard
npm install
npm run dev        # http://localhost:5173
npm run build      # typecheck + production build
```

## Stack
React 18 · TypeScript (strict) · Vite · react-router-dom. No chart or UI library (SVG charts are in `components/metrics/Chart.tsx`).

## Layering

```text
pages/ -> features/ (hooks) -> services/<domain> -> services/api (FactoryApi) -> mockApi | httpApi
```
- `types/` – API contracts (plain data shapes, no behaviour).
- `services/api/contract.ts` – `FactoryApi`, the only seam to the backend.
- `services/api/mockApi.ts` + `mocks/` – temporary in-browser backend. **Components never import `mocks/`.**
- `services/api/httpApi.ts` – REST implementation, enabled with `VITE_API_BASE_URL`.
- `features/` – hooks that expose data/actions to pages (`useAgents`, `useActivityFeed`, ...).
- `components/` – presentational, reusable; `pages/` – route screens; `layouts/` – app shell.

## Connecting a real backend
1. Copy `.env.example` to `.env.local`, set `VITE_API_BASE_URL=http://host/api/v1`.
2. Implement the endpoints listed in `httpApi.ts` (`/agents`, `/agents/:id/runs`, `/tasks`, `/workflows`, `/projects`, `/approvals`, `/activity`, `/metrics/overview`, ...) returning the shapes in `src/types/`.
3. Delete `mocks/` and `mockApi.ts` when no longer needed. No page or component changes are required.

## Adding real-time (WebSocket / SSE)
Live events flow through `FactoryApi.subscribeActivity(onEvent)`. Today it is a timer in `mockApi.ts`.
Implement it in `httpApi.ts` with `EventSource` or `WebSocket` that calls `onEvent(JSON.parse(msg.data))` and returns an unsubscribe function. `useActivityFeed` and the Activity page stay unchanged. The same pattern can be added for agent status and approval events.

## Notes
- Agent statuses are the union of both requested lists: ONLINE, BUSY, IDLE, WAITING, ERROR, DISABLED, OFFLINE. Each has a distinct glyph and text label.
- Agent **Health Score** (`utils/health.ts`) = success 30% + human approval 20% + CI pass 20% + test pass 15% + low revisions 15%.
- Approval actions and agent settings are mock-only and not persisted.
- Dependencies were not installed or built in the authoring environment (no network); run `npm install && npm run typecheck` first.

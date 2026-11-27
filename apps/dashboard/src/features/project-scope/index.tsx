import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';

const SCOPE_KEY = 'asf-project-scope';

interface ScopeValue {
  /** null = "All projects" (the default). */
  projectId: string | null;
  setProjectId: (id: string | null) => void;
}

const ScopeContext = createContext<ScopeValue>({
  projectId: null,
  setProjectId: () => undefined,
});

function readStoredScope(): string | null {
  try {
    return localStorage.getItem(SCOPE_KEY) ?? null;
  } catch {
    /* storage is optional: a blocked localStorage must not break the shell */
    return null;
  }
}

/** The sidebar's project scope, shared by every list page that filters by project. */
export function ProjectScopeProvider({ children }: { children: ReactNode }) {
  const [projectId, setScope] = useState<string | null>(readStoredScope);
  const setProjectId = useCallback((id: string | null) => {
    setScope(id);
    try {
      if (id) {
        localStorage.setItem(SCOPE_KEY, id);
      } else {
        localStorage.removeItem(SCOPE_KEY);
      }
    } catch {
      /* see readStoredScope */
    }
  }, []);
  const value = useMemo(() => ({ projectId, setProjectId }), [projectId, setProjectId]);
  return <ScopeContext.Provider value={value}>{children}</ScopeContext.Provider>;
}

export function useProjectScope(): ScopeValue {
  return useContext(ScopeContext);
}

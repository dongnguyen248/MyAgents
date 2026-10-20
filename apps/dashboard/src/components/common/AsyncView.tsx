import type { ReactNode } from 'react';

interface Props<T> {
  data?: T;
  loading: boolean;
  error?: Error;
  children: (data: T) => ReactNode;
}

export function AsyncView<T>({ data, loading, error, children }: Props<T>) {
  if (error) return <p className="alert" role="alert">Failed to load: {error.message}</p>;
  if (data === undefined) return loading ? <p className="muted" role="status">Loading…</p> : <p className="muted">Not found.</p>;
  return <>{children(data)}</>;
}

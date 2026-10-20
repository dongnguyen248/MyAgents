export const pct = (v: number, digits = 1) => `${(v * 100).toFixed(digits)}%`;

export function duration(sec: number): string {
  const s = Math.max(0, Math.round(sec));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  if (h) return `${h}h ${m}m`;
  if (m) return `${m}m ${String(r).padStart(2, '0')}s`;
  return `${r}s`;
}

export const clock = (iso: string, seconds = false) =>
  new Date(iso).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: seconds ? '2-digit' : undefined,
    hour12: false,
  });

export const dateTime = (iso: string) =>
  new Date(iso).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });

export function ago(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.floor(s)}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export const elapsed = (iso: string) => duration((Date.now() - new Date(iso).getTime()) / 1000);

export const shortDate = (iso: string) =>
  new Date(iso).toLocaleDateString([], { month: 'short', day: 'numeric' });

export const titleCase = (s: string) =>
  s.toLowerCase().replace(/[_-]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());

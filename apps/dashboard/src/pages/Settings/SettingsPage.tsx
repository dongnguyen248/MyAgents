import { Card, PageHeader, Stat } from '../../components/common/Layout';
import { ThemeToggle } from '../../components/common/ThemeToggle';

export function SettingsPage() {
  const base = import.meta.env.VITE_API_BASE_URL as string | undefined;
  return (
    <>
      <PageHeader title="Settings" subtitle="Dashboard preferences. No authentication or persistence yet." />
      <Card title="Appearance"><ThemeToggle /></Card>
      <Card title="Data source">
        <dl className="stats stats-2">
          <Stat label="Mode" value={base ? 'REST backend' : 'Mock API (in-browser)'} />
          <Stat label="API base URL" value={base || '— (set VITE_API_BASE_URL)'} />
          <Stat label="Real-time" value="Simulated timer (SSE/WebSocket not implemented)" />
        </dl>
      </Card>
    </>
  );
}

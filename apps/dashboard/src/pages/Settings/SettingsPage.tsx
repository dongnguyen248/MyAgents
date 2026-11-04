import { Card, PageHeader, Stat } from '../../components/common/Layout';
import { ThemeToggle } from '../../components/common/ThemeToggle';
import { ModelProviderForm } from '../../components/settings/ModelProviderForm';
import { useModelSettings } from '../../features/settings';
import { backendBaseUrl } from '../../services/api';

export function SettingsPage() {
  const settings = useModelSettings();
  return (
    <>
      <PageHeader title="Settings" subtitle="Dashboard preferences and the agents' model provider." />
      <Card title="Model provider">
        {settings.loading && <p className="muted">Loading model settings…</p>}
        {settings.error && <p className="error-text">{settings.error.message}</p>}
        {settings.data && (
          <ModelProviderForm
            key={`${settings.data.provider}|${settings.data.model}|${settings.data.baseUrl}|${settings.data.keyHint}`}
            initial={settings.data}
          />
        )}
      </Card>
      <Card title="Appearance"><ThemeToggle /></Card>
      <Card title="Data source">
        <dl className="stats stats-2">
          <Stat label="Mode" value={backendBaseUrl ? 'REST backend' : 'Mock API (in-browser)'} />
          <Stat label="API base URL" value={backendBaseUrl || '— (set VITE_API_BASE_URL)'} />
          <Stat label="Real-time" value={backendBaseUrl ? 'SSE (/events)' : 'Simulated timer'} />
        </dl>
      </Card>
    </>
  );
}

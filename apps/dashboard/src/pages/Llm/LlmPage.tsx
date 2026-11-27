import { AsyncView } from '../../components/common/AsyncView';
import { Card, PageHeader } from '../../components/common/Layout';
import { LlmSettingsForm } from '../../components/llm/LlmSettingsForm';
import { useModelSettings } from '../../features/settings';

/** Formerly "Settings": the one place that configures the model every agent calls. */
export function LlmPage() {
  const settings = useModelSettings();
  const summary = settings.data
    ? `${settings.data.provider} · ${settings.data.model || 'no model'}`
    : undefined;
  return (
    <>
      <PageHeader
        title="LLM"
        subtitle="Provider, shared model and per-agent overrides — stored on this machine by the backend."
      />
      <Card title="Endpoints & models" subtitle={summary}>
        <AsyncView {...settings}>
          {(data) => (
            <LlmSettingsForm
              key={`${data.provider}|${data.model}|${data.baseUrl}|${data.keyHint}`}
              initial={data}
            />
          )}
        </AsyncView>
      </Card>
    </>
  );
}

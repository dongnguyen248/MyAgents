import { agentMeta } from '../../lib/agentCatalog';
import type { Agent, AgentConfig } from '../../types/agent';
import { Icon } from '../common/Icon';
import { AgentProfilePicker } from './AgentProfilePicker';

const RETRY_LABEL: Record<AgentConfig['retryPolicy']['backoff'], string> = {
  none: 'no retry',
  linear: 'linear backoff',
  exponential: 'exponential backoff',
};

function PromptSection({ prompt }: { prompt: string }) {
  return (
    <section>
      <h3 className="section-title">System prompt</h3>
      <textarea
        className="artifact-content"
        readOnly
        aria-label="System prompt (read-only)"
        value={prompt}
      />
      <p className="note">
        Prompts ship with the backend package; editing them from the dashboard is not wired to the
        API yet, so this is read-only.
      </p>
    </section>
  );
}

function ExecutionSection({ agent, config }: { agent: Agent; config: AgentConfig }) {
  const retry = config.retryPolicy;
  const projects = config.allowedProjectIds.length ? config.allowedProjectIds.join(', ') : 'All';
  return (
    <section>
      <h3 className="section-title">Execution</h3>
      <dl className="kv">
        <dt>Kind</dt>
        <dd>{agentMeta(agent.type).label} agent</dd>
        <dt>Version</dt>
        <dd>{agent.version}</dd>
        <dt>Concurrency</dt>
        <dd>{config.maxConcurrentTasks} task(s) at a time</dd>
        <dt>Timeout</dt>
        <dd>{config.timeoutSeconds}s per step</dd>
        <dt>Retries</dt>
        <dd>
          {retry.maxRetries} attempt(s), {RETRY_LABEL[retry.backoff]}
        </dd>
        <dt>Projects</dt>
        <dd>{projects}</dd>
      </dl>
    </section>
  );
}

/** Config tab of the agent setup drawer: LLM profile, prompt and limits. */
export function AgentSetupConfig({ agent, config }: { agent: Agent; config: AgentConfig }) {
  return (
    <>
      <section>
        <h3 className="section-title">LLM settings</h3>
        <AgentProfilePicker agent={agent} />
      </section>
      <PromptSection prompt={config.systemPrompt} />
      <ExecutionSection agent={agent} config={config} />
      <p className="note">
        <Icon name="info" className="icon-sm" /> Runtime limits and project allow-lists come from
        the platform configuration; this drawer shows what the backend reports.
      </p>
    </>
  );
}

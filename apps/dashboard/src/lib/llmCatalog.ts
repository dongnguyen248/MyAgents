/** Static copy for the LLM settings page: providers, base URLs and the agents that call a model. */

export interface ProviderOption {
  value: string;
  label: string;
  /** Placeholder for the model input. */
  model?: string;
  /** Default endpoint, shown as placeholder and used for the "required" check. */
  baseUrl?: string;
}

export const PROVIDERS: ProviderOption[] = [
  { value: 'scripted', label: 'Scripted demo replies (no API key)' },
  { value: 'gemini', label: 'Google Gemini', model: 'gemini-2.0-flash' },
  { value: 'openai', label: 'OpenAI', model: 'gpt-4o', baseUrl: 'https://api.openai.com/v1' },
  {
    value: 'github-models',
    label: 'GitHub Models (GitHub token)',
    model: 'openai/gpt-4o',
    baseUrl: 'https://models.github.ai/inference',
  },
  {
    value: 'meta',
    label: 'Meta Model API (Muse Spark)',
    model: 'muse-spark-1.3',
    baseUrl: 'https://api.meta.ai/v1',
  },
  {
    value: 'custom',
    label: 'Custom OpenAI-compatible endpoint',
    model: 'model id at your endpoint',
  },
];

export function providerOption(value: string): ProviderOption | undefined {
  return PROVIDERS.find((provider) => provider.value === value);
}

export interface AgentModelField {
  key: string;
  label: string;
}

/**
 * Agents that call a model, so they can carry their own model and connection.
 * The Test agent is absent by design: it runs commands, not prompts.
 */
export const AGENT_MODEL_FIELDS: AgentModelField[] = [
  { key: 'spec', label: 'Spec agent' },
  { key: 'plan', label: 'Plan agent' },
  { key: 'task', label: 'Task agent' },
  { key: 'implement', label: 'Implement agent' },
  { key: 'review', label: 'Review agent' },
  { key: 'fix', label: 'Fix agent' },
  { key: 'artifact-review', label: 'Artifact review agent' },
];

export const AGENT_KEYS = AGENT_MODEL_FIELDS.map((field) => field.key);

export function agentLabel(key: string): string {
  return AGENT_MODEL_FIELDS.find((field) => field.key === key)?.label ?? key;
}

import type { LlmProfile } from '../types/llm';

/**
 * Seed profiles: two real endpoints and the keyless scripted demo. The mock keeps
 * them in memory, so adding or editing one survives until the page reloads.
 */
export const llmProfiles: LlmProfile[] = [
  {
    id: 'openai-primary',
    name: 'OpenAI · GPT-4o',
    provider: 'openai',
    baseUrl: 'https://api.openai.com/v1',
    model: 'gpt-4o',
    models: ['gpt-4o', 'gpt-4o-mini', 'o3-mini'],
    keyConfigured: true,
    keyHint: '…a1b2',
  },
  {
    id: 'local-proxy',
    name: 'Local proxy',
    provider: 'custom',
    baseUrl: 'http://127.0.0.1:18610/v1',
    model: 'muse-chat',
    models: ['muse-chat', 'qwen-coder', 'deepseek-v3'],
    keyConfigured: false,
    keyHint: '',
  },
  {
    id: 'scripted-demo',
    name: 'Scripted demo',
    provider: 'scripted',
    baseUrl: '',
    model: 'demo',
    models: ['demo'],
    keyConfigured: false,
    keyHint: '',
  },
];

/** Which profile each platform agent starts on (agent id -> profile id). */
export const agentProfileSeed: Record<string, string> = {
  'spec-agent': 'openai-primary',
  'plan-agent': 'openai-primary',
  'task-agent': 'openai-primary',
  'implement-agent': 'local-proxy',
  'review-agent': 'local-proxy',
  'fix-agent': 'local-proxy',
};

/** Model ids the mock "loads" per provider when the endpoint is reachable. */
export const MODELS_BY_PROVIDER: Record<string, string[]> = {
  openai: ['gpt-4o', 'gpt-4o-mini', 'o3-mini', 'o4-mini'],
  gemini: ['gemini-2.5-pro', 'gemini-2.0-flash', 'gemini-2.0-flash-lite'],
  'github-models': ['openai/gpt-4o', 'meta/llama-3.3-70b', 'mistral/mistral-large'],
  meta: ['muse-spark-1.3', 'muse-chat'],
  custom: ['muse-chat', 'qwen-coder', 'deepseek-v3', 'llama-3.3-70b'],
  scripted: ['demo'],
};

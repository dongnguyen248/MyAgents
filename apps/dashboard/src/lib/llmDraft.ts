import {
  buildConnectionsPayload,
  connStatesFromViews,
  type ConnFormState,
} from './agentConnections';
import { AGENT_KEYS } from './llmCatalog';
import type { ModelSettings, ModelSettingsInput } from '../types/settings';

/** Everything the LLM form can edit, held as one object so a save can reset it atomically. */
export interface LlmDraftState {
  provider: string;
  model: string;
  baseUrl: string;
  apiKey: string;
  clearKey: boolean;
  agentModels: Record<string, string>;
  connections: Record<string, ConnFormState>;
}

export function draftFromSettings(settings: ModelSettings): LlmDraftState {
  return {
    provider: settings.provider,
    model: settings.model,
    baseUrl: settings.baseUrl,
    apiKey: '',
    clearKey: false,
    agentModels: { ...(settings.agentModels ?? {}) },
    connections: connStatesFromViews(AGENT_KEYS, settings.agentConnections ?? {}),
  };
}

/** The save payload: only model overrides that carry a value, only connections that changed. */
export function payloadOf(state: LlmDraftState, saved: ModelSettings): ModelSettingsInput {
  const agentModels = Object.fromEntries(
    Object.entries(state.agentModels)
      .map(([key, value]) => [key, value.trim()] as const)
      .filter(([, value]) => value),
  );
  const agentConnections = buildConnectionsPayload(state.connections, saved.agentConnections ?? {});
  return {
    provider: state.provider,
    model: state.model.trim(),
    baseUrl: state.baseUrl.trim(),
    agentModels,
    ...(agentConnections ? { agentConnections } : {}),
    ...(state.apiKey ? { apiKey: state.apiKey } : {}),
    ...(state.clearKey ? { clearKey: true } : {}),
  };
}

export function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

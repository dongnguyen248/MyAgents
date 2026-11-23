import type { AgentConnectionInput, AgentConnectionView } from '../types/settings.ts';

/** Editable form state for one agent's connection profile. */
export interface ConnFormState {
  provider: string;
  baseUrl: string;
  /** Write-only: '' keeps the stored profile key. */
  apiKey: string;
  clearKey: boolean;
  /** '' = system default timeout. */
  timeoutText: string;
  /** One "Name: value" per line; sent only when headersDirty. */
  headersText: string;
  headersDirty: boolean;
  /** True when a stored profile exists and the user asked to drop it. */
  remove: boolean;
}

export function emptyConnState(): ConnFormState {
  return {
    provider: '',
    baseUrl: '',
    apiKey: '',
    clearKey: false,
    timeoutText: '',
    headersText: '',
    headersDirty: false,
    remove: false,
  };
}

export function connStateFromView(view?: AgentConnectionView): ConnFormState {
  if (!view) {
    return emptyConnState();
  }
  return {
    provider: view.provider,
    baseUrl: view.baseUrl,
    apiKey: '',
    clearKey: false,
    timeoutText: view.timeoutSeconds === null ? '' : String(view.timeoutSeconds),
    headersText: Object.keys(view.headers)
      .map((name) => `${name}: ****`)
      .join('\n'),
    headersDirty: false,
    remove: false,
  };
}

export function connStatesFromViews(
  agentKeys: string[],
  views: Record<string, AgentConnectionView>,
): Record<string, ConnFormState> {
  return Object.fromEntries(agentKeys.map((key) => [key, connStateFromView(views[key])]));
}

/** Parses the headers textarea; throws on a line without "Name: value". */
export function parseHeadersText(text: string): Record<string, string> {
  const headers: Record<string, string> = {};
  for (const line of text.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed) {
      continue;
    }
    const colon = trimmed.indexOf(':');
    if (colon <= 0) {
      throw new Error(`Header line "${trimmed}" must look like "Name: value"`);
    }
    headers[trimmed.slice(0, colon).trim()] = trimmed.slice(colon + 1).trim();
  }
  return headers;
}

function timeoutInput(
  state: ConnFormState,
  saved?: AgentConnectionView,
): number | null | undefined {
  const savedValue = saved?.timeoutSeconds ?? null;
  const text = state.timeoutText.trim();
  if (!text) {
    return savedValue === null ? undefined : null;
  }
  const parsed = Number(text);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    throw new Error('Timeout must be a whole number of seconds');
  }
  return parsed === savedValue ? undefined : parsed;
}

function changedTextInputs(
  state: ConnFormState,
  saved?: AgentConnectionView,
): AgentConnectionInput {
  const input: AgentConnectionInput = {};
  if (state.provider !== (saved?.provider ?? '')) {
    input.provider = state.provider;
  }
  if (state.baseUrl.trim() !== (saved?.baseUrl ?? '')) {
    input.baseUrl = state.baseUrl.trim();
  }
  return input;
}

function changedSecretInputs(state: ConnFormState): AgentConnectionInput {
  const input: AgentConnectionInput = {};
  if (state.apiKey) {
    input.apiKey = state.apiKey;
  }
  if (state.clearKey) {
    input.clearKey = true;
  }
  if (state.headersDirty) {
    input.headers = parseHeadersText(state.headersText);
  }
  return input;
}

/**
 * The save payload for one agent: null when nothing changed, {} when
 * the profile should be removed, else only the changed fields (the
 * backend keeps stored values for fields that are absent).
 */
export function buildConnectionInput(
  state: ConnFormState,
  saved?: AgentConnectionView,
): AgentConnectionInput | null {
  if (state.remove) {
    return {};
  }
  const input: AgentConnectionInput = {
    ...changedTextInputs(state, saved),
    ...changedSecretInputs(state),
  };
  const timeout = timeoutInput(state, saved);
  if (timeout !== undefined) {
    input.timeoutSeconds = timeout;
  }
  return Object.keys(input).length > 0 ? input : null;
}

/** Payload for every agent at once; undefined when nothing changed. */
export function buildConnectionsPayload(
  states: Record<string, ConnFormState>,
  saved: Record<string, AgentConnectionView>,
): Record<string, AgentConnectionInput> | undefined {
  const payload: Record<string, AgentConnectionInput> = {};
  for (const [key, state] of Object.entries(states)) {
    const input = buildConnectionInput(state, saved[key]);
    if (input !== null) {
      payload[key] = input;
    }
  }
  return Object.keys(payload).length > 0 ? payload : undefined;
}

/** Model provider settings, managed in Settings and stored by the backend. */

/** One agent's own connection, as the backend reports it (masked). */
export interface AgentConnectionView {
  /** '' = inherit the shared provider. */
  provider: string;
  /** '' = inherit the shared base URL. */
  baseUrl: string;
  /** The profile's own key is never returned; only whether one is stored. */
  keyConfigured: boolean;
  /** Last-4 hint for the profile's key, e.g. "…ab12"; '' when unknown. */
  keyHint: string;
  /** Header names with every value masked ("****"); values are write-only. */
  headers: Record<string, string>;
  /** Per-attempt timeout in seconds; null = the system default. */
  timeoutSeconds: number | null;
  /** True when the profile's base URL is plain http (soft warning). */
  insecureHttp: boolean;
}

/** One agent's connection as sent on save; unset fields keep stored values. */
export interface AgentConnectionInput {
  provider?: string;
  baseUrl?: string;
  /** Omit to keep the stored profile key; set to replace it. */
  apiKey?: string;
  clearKey?: boolean;
  /** When present, replaces the profile's whole header set. */
  headers?: Record<string, string>;
  timeoutSeconds?: number | null;
}

export interface ModelSettings {
  /** scripted | gemini | openai | github-models | custom */
  provider: string;
  model: string;
  baseUrl: string;
  /** Per-agent model overrides (agent type -> model); absent = shared model. */
  agentModels: Record<string, string>;
  /** Per-agent connection profiles (agent type -> masked view). */
  agentConnections: Record<string, AgentConnectionView>;
  /** The API key itself is never returned; only whether one is stored. */
  keyConfigured: boolean;
  /** Last-4 hint for the stored key, e.g. "…ab12"; '' when unknown. */
  keyHint: string;
}

export interface ModelSettingsInput {
  provider: string;
  model: string;
  baseUrl: string;
  /** Full per-agent override map; replaces the stored one when present. */
  agentModels?: Record<string, string>;
  /** Only the agents listed are touched; {} removes that agent's profile. */
  agentConnections?: Record<string, AgentConnectionInput>;
  /** Omit/empty to keep the stored key; set to replace it. */
  apiKey?: string;
  clearKey?: boolean;
}

export interface ModelTestResult {
  ok: boolean;
  message: string;
}

/** Model provider settings, managed in Settings and stored by the backend. */

export interface ModelSettings {
  /** scripted | gemini | openai | github-models | custom */
  provider: string;
  model: string;
  baseUrl: string;
  /** The API key itself is never returned; only whether one is stored. */
  keyConfigured: boolean;
  /** Last-4 hint for the stored key, e.g. "…ab12"; '' when unknown. */
  keyHint: string;
}

export interface ModelSettingsInput {
  provider: string;
  model: string;
  baseUrl: string;
  /** Omit/empty to keep the stored key; set to replace it. */
  apiKey?: string;
  clearKey?: boolean;
}

export interface ModelTestResult {
  ok: boolean;
  message: string;
}

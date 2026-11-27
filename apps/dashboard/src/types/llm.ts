/** A named model endpoint: what an agent points at when it needs a model. */
export interface LlmProfile {
  id: string;
  /** Operator-facing name, e.g. "OpenAI · GPT-4o" or "Local proxy". */
  name: string;
  /** scripted | gemini | openai | github-models | meta | custom */
  provider: string;
  baseUrl: string;
  model: string;
  /** Models the last "load models" call returned, when the backend caches them. */
  models?: string[];
  /** The key itself is never returned; only whether one is stored. */
  keyConfigured: boolean;
  /** Last-4 hint, e.g. "…ab12"; '' when unknown. */
  keyHint: string;
}

/** Save payload for one profile. Omit `apiKey` to keep the stored key. */
export interface LlmProfileInput {
  id: string;
  name: string;
  provider: string;
  baseUrl: string;
  model: string;
  /** Cache of the model ids the dashboard last loaded for this endpoint. */
  models?: string[];
  apiKey?: string;
  clearKey?: boolean;
}

/** What "load models" needs to ask the endpoint for its model ids. */
export interface LlmModelRequest {
  provider: string;
  baseUrl: string;
  /** Omit to use the key already stored for the profile. */
  apiKey?: string;
  profileId?: string;
}

/** Result of the "test" probe on one profile. */
export interface LlmTestResult {
  ok: boolean;
  message: string;
}

/** One line of test output the LLM page shows, tagged with the profile it came from. */
export interface LlmTestLine {
  profileName: string;
  result: LlmTestResult;
}

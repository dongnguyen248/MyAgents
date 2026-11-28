export interface AgentConnection {
  provider?: string;
  baseUrl?: string;
  keyConfigured?: boolean;
  keyHint?: string;
}

export interface ModelSettings {
  provider: string;
  model: string;
  baseUrl: string;
  keyConfigured: boolean;
  agentModels: Record<string, string>;
  agentConnections: Record<string, AgentConnection>;
}

export interface AgentModelInput {
  agent: string;
  provider: string;
  baseUrl: string;
  model: string;
  apiKey?: string;
  clearKey?: boolean;
}

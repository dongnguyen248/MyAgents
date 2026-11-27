import type { Agent } from '../../types/agent';
import type { LlmModelRequest, LlmProfile, LlmProfileInput, LlmTestResult } from '../../types/llm';
import { api } from '../api';

export const listLlmProfiles = (): Promise<LlmProfile[]> => api.listLlmProfiles();

export const saveLlmProfile = (input: LlmProfileInput): Promise<LlmProfile> =>
  api.saveLlmProfile(input);

export const deleteLlmProfile = (id: string): Promise<void> => api.deleteLlmProfile(id);

export const loadLlmModels = (request: LlmModelRequest): Promise<string[]> =>
  api.loadLlmModels(request);

export const testLlmProfile = (id: string): Promise<LlmTestResult> => api.testLlmProfile(id);

/** Point one agent at a profile (null clears it); returns the updated agent. */
export const assignAgentProfile = (agentId: string, profileId: string | null): Promise<Agent> =>
  api.assignAgentProfile(agentId, profileId);

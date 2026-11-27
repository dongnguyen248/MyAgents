import { useAsync } from '../../hooks/useAsync';
import { listLlmProfiles } from '../../services/llm/llmProfileService';

/** The configured LLM profiles, reloadable after a save or a delete. */
export const useLlmProfiles = () => useAsync(listLlmProfiles);

/** Profile id -> name, for lists that only need to show the label. */
export function useProfileNames(): Record<string, string> {
  const profiles = useLlmProfiles();
  return Object.fromEntries((profiles.data ?? []).map((profile) => [profile.id, profile.name]));
}

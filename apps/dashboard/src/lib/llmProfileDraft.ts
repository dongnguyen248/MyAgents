import type { LlmProfile, LlmProfileInput } from '../types/llm';

/**
 * The editable state of one LLM profile. `apiKey` is write-only: it starts
 * empty on every edit so a blank field keeps whatever the backend stores.
 */
export interface ProfileDraft {
  name: string;
  provider: string;
  baseUrl: string;
  apiKey: string;
  /** One of the ids `loadModels` returned, never free text. */
  model: string;
  clearKey: boolean;
}

export const DEFAULT_PROVIDER = 'openai';

export function emptyDraft(provider = DEFAULT_PROVIDER): ProfileDraft {
  return { name: '', provider, baseUrl: '', apiKey: '', model: '', clearKey: false };
}

export function draftFromProfile(profile: LlmProfile): ProfileDraft {
  return {
    name: profile.name,
    provider: profile.provider,
    baseUrl: profile.baseUrl,
    apiKey: '',
    model: profile.model,
    clearKey: false,
  };
}

const SLUG = /[^a-z0-9]+/g;

/** Slug the name into a stable id, numbered when it collides with an existing profile. */
export function profileIdFor(name: string, taken: string[]): string {
  const slug =
    name
      .toLowerCase()
      .replace(SLUG, '-')
      .replace(/^-+|-+$/g, '') || 'profile';
  const base = /^[a-z]/.test(slug) ? slug : `p-${slug}`;
  let id = base;
  for (let n = 2; taken.includes(id); n += 1) {
    id = `${base}-${n}`;
  }
  return id;
}

/** What stops this draft from being saved, or undefined when it is ready. */
export function draftProblem(draft: ProfileDraft): string | undefined {
  if (!draft.name.trim()) {
    return 'Give the profile a name — it is what the agent picker lists.';
  }
  if (draft.provider === 'custom' && !/^https?:\/\//.test(draft.baseUrl.trim())) {
    return 'The custom provider needs a base URL (http or https).';
  }
  if (draft.provider !== 'scripted' && !draft.model.trim()) {
    return 'Load the models from the endpoint and pick one from the list.';
  }
  return undefined;
}

/** Save payload: trimmed, with a blank key left out so the stored one survives. */
export function profileInputOf(
  id: string,
  draft: ProfileDraft,
  models: string[] = [],
): LlmProfileInput {
  const apiKey = draft.apiKey.trim();
  return {
    id,
    name: draft.name.trim(),
    provider: draft.provider,
    baseUrl: draft.baseUrl.trim(),
    model: draft.model.trim(),
    ...(models.length ? { models } : {}),
    ...(apiKey ? { apiKey } : {}),
    ...(draft.clearKey ? { clearKey: true } : {}),
  };
}

/** Key status line for one profile, shared by the list and the dialog. */
export function keyStatusText(profile?: Pick<LlmProfile, 'keyConfigured' | 'keyHint'>): string {
  if (profile?.keyConfigured) {
    return `Key stored (${profile.keyHint || '…'})`;
  }
  return 'No key stored yet';
}

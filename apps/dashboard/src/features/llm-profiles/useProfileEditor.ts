import { useCallback, useState } from 'react';
import {
  draftFromProfile,
  draftProblem,
  emptyDraft,
  profileIdFor,
  profileInputOf,
  type ProfileDraft,
} from '../../lib/llmProfileDraft';
import { messageOf } from '../../lib/message';
import { loadLlmModels, saveLlmProfile } from '../../services/llm/llmProfileService';
import type { LlmProfile } from '../../types/llm';

export interface EditorStatus {
  busy: boolean;
  loading: boolean;
  message?: string;
  failed?: boolean;
}

export interface ProfileEditor {
  draft: ProfileDraft;
  /** Model ids the last "load models" call returned for this endpoint. */
  models: string[];
  status: EditorStatus;
  patch: (next: Partial<ProfileDraft>) => void;
  /** Switching provider clears the model and the loaded list. */
  changeProvider: (provider: string) => void;
  loadModels: () => void;
  save: () => void;
}

type SetStatus = (status: EditorStatus) => void;

const IDLE: EditorStatus = { busy: false, loading: false };

interface Loaded {
  models: string[];
  status: EditorStatus;
}

async function fetchModels(draft: ProfileDraft, profileId?: string): Promise<Loaded> {
  const apiKey = draft.apiKey.trim();
  try {
    const models = await loadLlmModels({
      provider: draft.provider,
      baseUrl: draft.baseUrl.trim(),
      ...(apiKey ? { apiKey } : {}),
      ...(profileId ? { profileId } : {}),
    });
    const message = models.length
      ? `${models.length} model(s) loaded — pick one below.`
      : 'The endpoint returned no models.';
    return { models, status: { ...IDLE, message, failed: !models.length } };
  } catch (error) {
    return { models: [], status: { ...IDLE, message: messageOf(error), failed: true } };
  }
}

function pickFirst(draft: ProfileDraft, models: string[]): ProfileDraft {
  return draft.model || !models.length ? draft : { ...draft, model: models[0] };
}

/** The edited values, seeded from the profile (or from nothing when creating). */
function useDraftState(profile: LlmProfile | null) {
  const [draft, setDraft] = useState<ProfileDraft>(() =>
    profile ? draftFromProfile(profile) : emptyDraft(),
  );
  const patch = useCallback(
    (next: Partial<ProfileDraft>) => setDraft((previous) => ({ ...previous, ...next })),
    [],
  );
  return { draft, setDraft, patch };
}

/** What the endpoint offered last, plus the dialog's status line. */
function useModelList(profile: LlmProfile | null) {
  const [models, setModels] = useState<string[]>(profile?.models ?? []);
  const [status, setStatus] = useState<EditorStatus>(IDLE);
  return { models, setModels, status, setStatus };
}

/** Draft, model list and the "load models" round-trip of one dialog. */
function useDraftModels(profile: LlmProfile | null) {
  const { draft, setDraft, patch } = useDraftState(profile);
  const { models, setModels, status, setStatus } = useModelList(profile);

  const loadModels = async () => {
    setStatus({ busy: false, loading: true });
    const loaded = await fetchModels(draft, profile?.id);
    setModels(loaded.models);
    setDraft((previous) => pickFirst(previous, loaded.models));
    setStatus(loaded.status);
  };

  const changeProvider = (provider: string) => {
    patch({ provider, model: '' });
    setModels([]);
    setStatus(IDLE);
  };

  return {
    draft,
    models,
    status,
    patch,
    changeProvider,
    setStatus,
    loadModels: () => void loadModels(),
  };
}

interface SaveFlow {
  profile: LlmProfile | null;
  taken: string[];
  models: string[];
  setStatus: SetStatus;
  onSaved: () => void;
  onClose: () => void;
}

/** Validate-then-save, reported through the dialog's status line. */
function useSaveFlow({ profile, taken, models, setStatus, onSaved, onClose }: SaveFlow) {
  return async (draft: ProfileDraft) => {
    const problem = draftProblem(draft);
    if (problem) {
      setStatus({ ...IDLE, message: problem, failed: true });
      return;
    }
    setStatus({ busy: true, loading: false });
    const id = profile?.id ?? profileIdFor(draft.name, taken);
    try {
      await saveLlmProfile(profileInputOf(id, draft, models));
      onSaved();
      onClose();
    } catch (error) {
      setStatus({ ...IDLE, message: messageOf(error), failed: true });
    }
  };
}

/** Draft, loaded model list and the save flow for one create/edit dialog. */
export function useProfileEditor(
  profile: LlmProfile | null,
  taken: string[],
  onSaved: () => void,
  onClose: () => void,
): ProfileEditor {
  const state = useDraftModels(profile);
  const save = useSaveFlow({
    profile,
    taken,
    models: state.models,
    setStatus: state.setStatus,
    onSaved,
    onClose,
  });
  return { ...state, save: () => void save(state.draft) };
}

import { useState } from 'react';
import { useLlmProfiles } from './useProfiles';
import { messageOf } from '../../lib/message';
import { deleteLlmProfile, testLlmProfile } from '../../services/llm/llmProfileService';
import type { LlmProfile, LlmTestLine } from '../../types/llm';

export interface Editing {
  open: boolean;
  /** null while creating a new profile. */
  profile: LlmProfile | null;
}

interface EditorState {
  editing: Editing;
  pendingDelete: LlmProfile | null;
  openNew: () => void;
  openEdit: (profile: LlmProfile) => void;
  closeEditor: () => void;
  askDelete: (profile: LlmProfile | null) => void;
}

const CLOSED: Editing = { open: false, profile: null };

/** Which dialog is open: the create/edit form or the delete confirmation. */
function useEditorState(): EditorState {
  const [editing, setEditing] = useState<Editing>(CLOSED);
  const [pendingDelete, setPendingDelete] = useState<LlmProfile | null>(null);
  return {
    editing,
    pendingDelete,
    openNew: () => setEditing({ open: true, profile: null }),
    openEdit: (profile) => setEditing({ open: true, profile }),
    closeEditor: () => setEditing(CLOSED),
    askDelete: setPendingDelete,
  };
}

async function probeProfile(profile: LlmProfile): Promise<LlmTestLine> {
  try {
    return { profileName: profile.name, result: await testLlmProfile(profile.id) };
  } catch (error) {
    return { profileName: profile.name, result: { ok: false, message: messageOf(error) } };
  }
}

async function removeProfile(profile: LlmProfile): Promise<LlmTestLine | null> {
  try {
    await deleteLlmProfile(profile.id);
    return null;
  } catch (error) {
    return { profileName: profile.name, result: { ok: false, message: messageOf(error) } };
  }
}

interface Actions {
  test: LlmTestLine | null;
  busyId: string;
  runTest: (profile: LlmProfile) => void;
  confirmDelete: (profile: LlmProfile | null) => void;
}

/** The test probe and the delete round-trip, each reported on one status line. */
function useActions(reload: () => void): Actions {
  const [test, setTest] = useState<LlmTestLine | null>(null);
  const [busyId, setBusyId] = useState('');

  const runTest = async (profile: LlmProfile) => {
    setBusyId(profile.id);
    setTest(await probeProfile(profile));
    setBusyId('');
  };

  const confirmDelete = async (profile: LlmProfile | null) => {
    if (profile) {
      setTest(await removeProfile(profile));
      reload();
    }
  };

  return {
    test,
    busyId,
    runTest: (profile) => void runTest(profile),
    confirmDelete: (profile) => void confirmDelete(profile),
  };
}

export interface ProfilePage extends EditorState, Actions {
  profiles: ReturnType<typeof useLlmProfiles>;
}

/** Everything the LLM page drives: the profile list, the dialogs and one status line. */
export function useProfilePage(): ProfilePage {
  const profiles = useLlmProfiles();
  const editor = useEditorState();
  const actions = useActions(profiles.reload);
  return { profiles, ...editor, ...actions };
}

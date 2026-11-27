import { useProfileEditor, type ProfileEditor } from '../../features/llm-profiles';
import type { LlmProfile } from '../../types/llm';
import { Modal } from '../common/Modal';
import { BaseUrlField, KeyField, ModelField, NameField, ProviderField } from './ProfileFields';

function ProfileBody({ editor, profile }: { editor: ProfileEditor; profile: LlmProfile | null }) {
  const fields = { draft: editor.draft, patch: editor.patch };
  return (
    <>
      <NameField {...fields} />
      <ProviderField draft={editor.draft} onProvider={editor.changeProvider} />
      <BaseUrlField {...fields} />
      {editor.draft.provider !== 'scripted' && <KeyField {...fields} profile={profile} />}
      <ModelField
        {...fields}
        models={editor.models}
        loading={editor.status.loading}
        onLoad={editor.loadModels}
      />
      {editor.status.message && (
        <p className={editor.status.failed ? 'error-text' : 'note'} role="status">
          {editor.status.message}
        </p>
      )}
    </>
  );
}

function DialogFooter({ editor, onClose }: { editor: ProfileEditor; onClose: () => void }) {
  return (
    <>
      <button type="button" className="btn btn-ghost" onClick={onClose}>
        Cancel
      </button>
      <span className="spacer" />
      <button type="submit" className="btn btn-primary" disabled={editor.status.busy}>
        {editor.status.busy ? 'Saving…' : 'Save profile'}
      </button>
    </>
  );
}

/** Create or edit one named LLM profile. */
export function ProfileDialog({
  profile,
  taken,
  onClose,
  onSaved,
}: {
  profile: LlmProfile | null;
  taken: string[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const editor = useProfileEditor(profile, taken, onSaved, onClose);
  return (
    <Modal
      label={profile ? `Edit ${profile.name}` : 'New LLM profile'}
      title={profile ? 'Edit LLM profile' : 'New LLM profile'}
      description="Name the endpoint, store its key, then load the models it offers and pick one."
      onClose={onClose}
      onSubmit={editor.save}
      footer={<DialogFooter editor={editor} onClose={onClose} />}
    >
      <ProfileBody editor={editor} profile={profile} />
    </Modal>
  );
}

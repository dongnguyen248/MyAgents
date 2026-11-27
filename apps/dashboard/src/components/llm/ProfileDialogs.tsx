import type { ProfilePage } from '../../features/llm-profiles';
import type { LlmProfile, LlmTestLine } from '../../types/llm';
import { AsyncView } from '../common/AsyncView';
import { Modal } from '../common/Modal';
import { Card } from '../common/Layout';
import { ProfileDialog } from './ProfileDialog';
import { ProfileList } from './ProfileList';

/** The profile list card: "{n} total" plus one row per endpoint. */
export function ProfilesCard({ page }: { page: ProfilePage }) {
  const total = page.profiles.data?.length;
  return (
    <Card title="Profiles" subtitle={total === undefined ? undefined : `${total} total`}>
      <AsyncView {...page.profiles}>
        {(list) => (
          <ProfileList
            profiles={list}
            busyId={page.busyId}
            onTest={page.runTest}
            onEdit={page.openEdit}
            onDelete={page.askDelete}
          />
        )}
      </AsyncView>
    </Card>
  );
}

export function TestLine({ test }: { test: LlmTestLine | null }) {
  if (!test) {
    return null;
  }
  return (
    <p className={test.result.ok ? 'note' : 'error-text'} role="status">
      {test.result.ok ? '✓ ' : '✗ '}
      {test.profileName}: {test.result.message}
    </p>
  );
}

function DeleteFooter({ onCancel, onConfirm }: { onCancel: () => void; onConfirm: () => void }) {
  return (
    <>
      <button type="button" className="btn btn-ghost" onClick={onCancel}>
        Cancel
      </button>
      <span className="spacer" />
      <button type="button" className="btn btn-primary" onClick={onConfirm}>
        Delete profile
      </button>
    </>
  );
}

function DeleteDialog({ profile, page }: { profile: LlmProfile; page: ProfilePage }) {
  return (
    <Modal
      label={`Delete ${profile.name}`}
      title={`Delete “${profile.name}”?`}
      description="Agents pointing at this profile fall back to the backend default."
      onClose={() => page.askDelete(null)}
      onSubmit={() => page.confirmDelete(profile)}
      footer={
        <DeleteFooter
          onCancel={() => page.askDelete(null)}
          onConfirm={() => page.confirmDelete(profile)}
        />
      }
    >
      <p className="note">
        {profile.provider} · {profile.model || 'no model'} · {profile.baseUrl || 'default endpoint'}
      </p>
    </Modal>
  );
}

/** The create/edit dialog, the delete confirmation and the one test/status line. */
export function ProfileDialogs({ page }: { page: ProfilePage }) {
  const { editing, pendingDelete } = page;
  const taken = (page.profiles.data ?? [])
    .map((profile) => profile.id)
    .filter((id) => id !== editing.profile?.id);
  return (
    <>
      <TestLine test={page.test} />
      {editing.open && (
        <ProfileDialog
          profile={editing.profile}
          taken={taken}
          onClose={page.closeEditor}
          onSaved={page.profiles.reload}
        />
      )}
      {pendingDelete && <DeleteDialog profile={pendingDelete} page={page} />}
    </>
  );
}

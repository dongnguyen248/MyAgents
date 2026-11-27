import { keyStatusText } from '../../lib/llmProfileDraft';
import type { LlmProfile } from '../../types/llm';
import { Badge } from '../common/Badge';

function ProfileText({ profile }: { profile: LlmProfile }) {
  return (
    <div className="profile-main">
      <span className="profile-name">
        {profile.name}
        {profile.provider !== 'scripted' && !profile.keyConfigured && (
          <Badge tone="warn" icon="!" small>
            No key
          </Badge>
        )}
      </span>
      <span className="profile-meta">
        <span className="chip">{profile.provider}</span>
        <span className="mono">{profile.model || 'no model'}</span>
        <span className="profile-endpoint">{profile.baseUrl || 'provider default endpoint'}</span>
      </span>
      <span className="profile-endpoint">{keyStatusText(profile)}</span>
    </div>
  );
}

interface RowActions {
  profile: LlmProfile;
  busy: boolean;
  onTest: (profile: LlmProfile) => void;
  onEdit: (profile: LlmProfile) => void;
  onDelete: (profile: LlmProfile) => void;
}

function ProfileActions({ profile, busy, onTest, onEdit, onDelete }: RowActions) {
  return (
    <div className="profile-actions">
      <button type="button" className="btn" disabled={busy} onClick={() => onTest(profile)}>
        {busy ? 'Testing…' : 'Test'}
      </button>
      <button type="button" className="btn" onClick={() => onEdit(profile)}>
        Edit
      </button>
      <button type="button" className="btn btn-ghost" onClick={() => onDelete(profile)}>
        Delete
      </button>
    </div>
  );
}

interface ListProps {
  profiles: LlmProfile[];
  busyId: string;
  onTest: (profile: LlmProfile) => void;
  onEdit: (profile: LlmProfile) => void;
  onDelete: (profile: LlmProfile) => void;
}

/** One row per configured endpoint, with its test, edit and delete actions. */
export function ProfileList({ profiles, busyId, onTest, onEdit, onDelete }: ListProps) {
  if (!profiles.length) {
    return (
      <p className="empty muted">
        No LLM profile yet — add one so agents have an endpoint and model to call.
      </p>
    );
  }
  return (
    <ul className="profile-list">
      {profiles.map((profile) => (
        <li className="profile-row" key={profile.id}>
          <ProfileText profile={profile} />
          <ProfileActions
            profile={profile}
            busy={busyId === profile.id}
            onTest={onTest}
            onEdit={onEdit}
            onDelete={onDelete}
          />
        </li>
      ))}
    </ul>
  );
}

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useLlmProfiles } from '../../features/llm-profiles';
import { messageOf } from '../../lib/message';
import { assignAgentProfile } from '../../services/llm/llmProfileService';
import type { Agent } from '../../types/agent';
import type { LlmProfile } from '../../types/llm';

interface Status {
  busy: boolean;
  message?: string;
  failed?: boolean;
}

function summaryOf(profile?: LlmProfile): string {
  if (!profile) {
    return 'The backend default endpoint applies.';
  }
  return `${profile.provider} · ${profile.model || 'no model picked'}`;
}

/** Save state for one agent's profile choice, kept out of the form component. */
function useAssign(agentId: string) {
  const [status, setStatus] = useState<Status>({ busy: false });
  const save = async (profileId: string) => {
    setStatus({ busy: true });
    try {
      const agent = await assignAgentProfile(agentId, profileId || null);
      const message = agent.llmProfileId
        ? 'Saved — the next run of this agent uses that profile.'
        : 'Cleared — the backend default applies.';
      setStatus({ busy: false, message });
    } catch (error) {
      setStatus({ busy: false, message: messageOf(error), failed: true });
    }
  };
  return { status, save };
}

function ProfileSelect({
  profiles,
  value,
  onChange,
}: {
  profiles: LlmProfile[];
  value: string;
  onChange: (id: string) => void;
}) {
  return (
    <label className="field">
      <span>LLM profile</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">Backend default</option>
        {profiles.map((profile) => (
          <option key={profile.id} value={profile.id}>
            {profile.name}
          </option>
        ))}
      </select>
    </label>
  );
}

function PickerFooter({ status }: { status: Status }) {
  return (
    <div className="hint-row">
      <p className={status.failed ? 'alert' : 'note'} role="status">
        {status.message ?? 'Agents can each run on a different named LLM.'}
      </p>
      <button type="submit" className="btn" disabled={status.busy}>
        {status.busy ? 'Saving…' : 'Save'}
      </button>
    </div>
  );
}

function PickerForm({ agent, profiles }: { agent: Agent; profiles: LlmProfile[] }) {
  const [draft, setDraft] = useState<string>();
  const { status, save } = useAssign(agent.id);
  const value = draft ?? agent.llmProfileId ?? '';
  const chosen = profiles.find((profile) => profile.id === value);
  return (
    <form
      className="stack-sm"
      onSubmit={(event) => {
        event.preventDefault();
        void save(value);
      }}
    >
      <ProfileSelect profiles={profiles} value={value} onChange={setDraft} />
      <p className="note">{summaryOf(chosen)}</p>
      <PickerFooter status={status} />
      <p className="note">
        Profiles are configured on the <Link to="/llm">LLM page</Link>. The assignment endpoint is
        not in this backend yet, so the mock keeps the choice for this session.
      </p>
    </form>
  );
}

/** Which configured LLM this agent runs on. */
export function AgentProfilePicker({ agent }: { agent: Agent }) {
  const profiles = useLlmProfiles();
  if (agent.type === 'test') {
    return (
      <p className="note">
        The Test agent never calls a model: it runs the project’s configured test commands in the
        sandbox.
      </p>
    );
  }
  if (profiles.error) {
    return <p className="note">LLM profiles are unavailable for this backend.</p>;
  }
  if (!profiles.data) {
    return <p className="note">Loading the configured profiles…</p>;
  }
  if (!profiles.data.length) {
    return (
      <p className="note">
        No LLM profile yet — create one on the <Link to="/llm">LLM page</Link> and it shows up here.
      </p>
    );
  }
  return <PickerForm agent={agent} profiles={profiles.data} />;
}

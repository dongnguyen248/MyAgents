import { PageHeader } from '../../components/common/Layout';
import { Icon } from '../../components/common/Icon';
import { ProfileDialogs, ProfilesCard } from '../../components/llm/ProfileDialogs';
import { useProfilePage } from '../../features/llm-profiles';

function NewProfileButton({ onClick }: { onClick: () => void }) {
  return (
    <button type="button" className="btn btn-primary" onClick={onClick}>
      <Icon name="plus" className="icon-sm" />
      New profile
    </button>
  );
}

/** Named LLM profiles: provider, endpoint, key and the model an agent runs on. */
export function LlmPage() {
  const page = useProfilePage();
  return (
    <>
      <PageHeader
        title="LLM"
        subtitle="Named endpoints an agent can run on: provider, base URL, key and the model picked from what the endpoint offers."
        actions={<NewProfileButton onClick={page.openNew} />}
      />
      <ProfilesCard page={page} />
      <ProfileDialogs page={page} />
    </>
  );
}

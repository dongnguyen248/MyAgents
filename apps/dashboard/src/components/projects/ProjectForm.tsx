import { useState, type FormEvent } from 'react';
import { parseMaxRevisions, validateApprovalSettings } from '../../lib/approvalSettings';
import type { ProjectProfileInput } from '../../types/project';
import { Card } from '../common/Layout';
import { secretInputAttrs, textInputAttrs } from '../forms/inputAttrs';

const list = (value: string): string[] =>
  value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);

const slugify = (value: string): string =>
  value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');

interface Props {
  onCreate: (input: ProjectProfileInput) => Promise<void>;
  onCancel: () => void;
  /** When set, the form edits this profile: the id is locked and every field is prefilled. */
  initial?: ProjectProfileInput;
  title?: string;
  submitLabel?: string;
}

function useProjectIdentity(initial: ProjectProfileInput | undefined) {
  const [name, setName] = useState(initial?.name ?? '');
  const [id, setId] = useState(initial?.id ?? '');
  const [idTouched, setIdTouched] = useState(initial !== undefined);
  const [description, setDescription] = useState(initial?.description ?? '');
  return { name, setName, id, setId, idTouched, setIdTouched, description, setDescription };
}

function useProjectTech(initial: ProjectProfileInput | undefined) {
  const [provider, setProvider] = useState(initial?.repository.provider ?? 'gitlab');
  const [backend, setBackend] = useState((initial?.technology.backend ?? []).join(', '));
  const [frontend, setFrontend] = useState((initial?.technology.frontend ?? []).join(', '));
  return { provider, setProvider, backend, setBackend, frontend, setFrontend };
}

function useProjectWorkflow(initial: ProjectProfileInput | undefined) {
  const [workflow, setWorkflow] = useState(initial?.workflow ?? 'software-development');
  const [skills, setSkills] = useState((initial?.enabledSkills ?? []).join(', '));
  return { workflow, setWorkflow, skills, setSkills };
}

function useRepositoryLink(initial: ProjectProfileInput | undefined) {
  const [repoUrl, setRepoUrl] = useState(initial?.repository.url ?? '');
  const [hostingToken, setHostingToken] = useState('');
  const [clearToken, setClearToken] = useState(false);
  return { repoUrl, setRepoUrl, hostingToken, setHostingToken, clearToken, setClearToken };
}

function useWorkspaceState(initial: ProjectProfileInput | undefined) {
  const [workspacePath, setWorkspacePath] = useState(initial?.repository.path ?? '');
  const [workspaceMode, setWorkspaceMode] = useState(initial?.repository.workspaceMode ?? 'direct');
  const [keepChanges, setKeepChanges] = useState(initial?.repository.keepChangesOnFailure ?? false);
  return { workspacePath, setWorkspacePath, workspaceMode, setWorkspaceMode, keepChanges, setKeepChanges };
}

function useTestCommand(initial: ProjectProfileInput | undefined) {
  const [testCommand, setTestCommand] = useState(
    (initial?.configuration.testCommands?.[0] ?? []).join(' '),
  );
  return { testCommand, setTestCommand };
}

function useApprovalChannel(initial: ProjectProfileInput | undefined) {
  const [channel, setChannel] = useState(
    initial ? (initial.configuration.approval?.channel ?? 'none') || 'none' : 'teams',
  );
  const [approvalMode, setApprovalMode] = useState(initial?.configuration.approval?.mode ?? '');
  return { channel, setChannel, approvalMode, setApprovalMode };
}

function useApprovalLimits(initial: ProjectProfileInput | undefined) {
  const [maxRevisions, setMaxRevisions] = useState(
    initial?.configuration.approval?.maxRevisions?.toString() ?? '',
  );
  const [onExhausted, setOnExhausted] = useState(initial?.configuration.approval?.onExhausted ?? '');
  return { maxRevisions, setMaxRevisions, onExhausted, setOnExhausted };
}

function useFormStatus() {
  const [error, setError] = useState<string | undefined>();
  const [submitting, setSubmitting] = useState(false);
  return { error, setError, submitting, setSubmitting };
}

function useProjectFormState(initial: ProjectProfileInput | undefined) {
  const identity = useProjectIdentity(initial);
  const tech = useProjectTech(initial);
  const workflow = useProjectWorkflow(initial);
  const repoLink = useRepositoryLink(initial);
  const workspace = useWorkspaceState(initial);
  const testCommand = useTestCommand(initial);
  const approvalChannel = useApprovalChannel(initial);
  const approvalLimits = useApprovalLimits(initial);
  const formStatus = useFormStatus();
  return {
    identity,
    tech,
    workflow,
    repoLink,
    workspace,
    testCommand,
    approvalChannel,
    approvalLimits,
    formStatus,
    editing: initial !== undefined,
  };
}

type IdentityState = ReturnType<typeof useProjectIdentity>;
type TechState = ReturnType<typeof useProjectTech>;
type WorkflowState = ReturnType<typeof useProjectWorkflow>;
type RepoLinkState = ReturnType<typeof useRepositoryLink>;
type WorkspaceState = ReturnType<typeof useWorkspaceState>;
type TestCommandState = ReturnType<typeof useTestCommand>;
type ApprovalChannelState = ReturnType<typeof useApprovalChannel>;
type ApprovalLimitsState = ReturnType<typeof useApprovalLimits>;
type FormStatusState = ReturnType<typeof useFormStatus>;
type FormState = ReturnType<typeof useProjectFormState>;

function approvalSettingsOf(state: FormState) {
  const { approvalChannel, approvalLimits, editing } = state;
  const maxRevisionsValue = parseMaxRevisions(approvalLimits.maxRevisions);
  const result: { channel: string; mode?: string; maxRevisions?: number; onExhausted?: string } = {
    channel: approvalChannel.channel === 'none' ? '' : approvalChannel.channel,
  };
  if (approvalChannel.approvalMode) {
    result.mode = approvalChannel.approvalMode;
  }
  if (maxRevisionsValue !== undefined) {
    result.maxRevisions = maxRevisionsValue;
  }
  if (approvalLimits.onExhausted) {
    result.onExhausted = approvalLimits.onExhausted;
  }
  const sendApproval =
    approvalChannel.channel !== 'none' ||
    approvalChannel.approvalMode !== '' ||
    maxRevisionsValue !== undefined ||
    approvalLimits.onExhausted !== '' ||
    editing;
  return sendApproval ? result : undefined;
}

function hostingTokenFieldsOf(link: RepoLinkState) {
  // Write-only: a typed token replaces the stored one; the clear
  // checkbox removes it. Blank + unchecked leaves it untouched.
  if (link.hostingToken.trim()) {
    return { hostingToken: link.hostingToken.trim() };
  }
  if (link.clearToken) {
    return { clearHostingToken: true };
  }
  return {};
}

function buildProjectInput(state: FormState): ProjectProfileInput {
  const { identity, tech, workflow, repoLink, workspace, editing } = state;
  const testCommands = state.testCommand.testCommand.trim()
    ? [state.testCommand.testCommand.trim().split(/\s+/)]
    : [];
  const approvalSettings = approvalSettingsOf(state);
  return {
    id: identity.id.trim(),
    name: identity.name.trim(),
    // In edit mode always send the description so clearing it works.
    ...(identity.description.trim() || editing ? { description: identity.description.trim() } : {}),
    repository: {
      provider: tech.provider,
      path: workspace.workspacePath.trim(),
      url: repoLink.repoUrl.trim(),
      workspaceMode: workspace.workspaceMode,
      keepChangesOnFailure: workspace.keepChanges,
    },
    technology: { backend: list(tech.backend), frontend: list(tech.frontend) },
    workflow: workflow.workflow.trim() || 'software-development',
    enabledSkills: list(workflow.skills),
    // In edit mode an explicit empty channel clears a stored one on merge.
    configuration: {
      ...(approvalSettings ? { approval: approvalSettings } : {}),
      // In edit mode an empty test command clears the stored one.
      ...(testCommands.length || editing ? { testCommands } : {}),
    },
    ...hostingTokenFieldsOf(repoLink),
  };
}

function createSubmitHandler(state: FormState, onCreate: Props['onCreate']) {
  const { approvalChannel, approvalLimits, formStatus } = state;
  return async (e: FormEvent) => {
    e.preventDefault();
    formStatus.setError(undefined);
    // Same bounds the server enforces on configuration.approval.
    const settingsErrors = validateApprovalSettings({
      mode: approvalChannel.approvalMode,
      maxRevisions: approvalLimits.maxRevisions,
      onExhausted: approvalLimits.onExhausted,
    });
    if (settingsErrors.length) {
      formStatus.setError(settingsErrors.join(' '));
      return;
    }
    formStatus.setSubmitting(true);
    const input = buildProjectInput(state);
    try {
      await onCreate(input);
    } catch (err) {
      formStatus.setError(err instanceof Error ? err.message : 'Failed to create project');
      formStatus.setSubmitting(false);
    }
  };
}

function ProjectNameField({ identity, onNameChange }: { identity: IdentityState; onNameChange: (value: string) => void }) {
  return (
    <label className="field">
      <span>Project name</span>
      <input value={identity.name} onChange={(e) => onNameChange(e.target.value)} required placeholder="My Project" />
    </label>
  );
}

function ProjectIdField({ identity, editing }: { identity: IdentityState; editing: boolean }) {
  return (
    <label className="field">
      <span>Project ID (slug)</span>
      <input
        value={identity.id}
        onChange={(e) => {
          identity.setId(e.target.value);
          identity.setIdTouched(true);
        }}
        required
        readOnly={editing}
        placeholder="my-project"
      />
    </label>
  );
}

function IdentityFields({ identity, editing }: { identity: IdentityState; editing: boolean }) {
  const changeName = (value: string) => {
    identity.setName(value);
    if (!identity.idTouched) {
      identity.setId(slugify(value));
    }
  };
  return (
    <div className="form-grid">
      <ProjectNameField identity={identity} onNameChange={changeName} />
      <ProjectIdField identity={identity} editing={editing} />
    </div>
  );
}

function DescriptionField({ identity }: { identity: IdentityState }) {
  return (
    <label className="field block">
      <span>Description (optional)</span>
      <input value={identity.description} onChange={(e) => identity.setDescription(e.target.value)} />
    </label>
  );
}

function ApprovalChannelField({ approvalChannel }: { approvalChannel: ApprovalChannelState }) {
  return (
    <label className="field">
      <span>Approval channel</span>
      <select value={approvalChannel.channel} onChange={(e) => approvalChannel.setChannel(e.target.value)}>
        <option value="teams">Microsoft Teams</option>
        <option value="slack">Slack</option>
        <option value="none">None</option>
      </select>
    </label>
  );
}

function ProviderWorkflowFields({ tech, workflow, approvalChannel }: { tech: TechState; workflow: WorkflowState; approvalChannel: ApprovalChannelState }) {
  return (
    <div className="form-grid">
      <label className="field">
        <span>Repository provider</span>
        <select value={tech.provider} onChange={(e) => tech.setProvider(e.target.value)}>
          <option value="gitlab">GitLab</option>
          <option value="github">GitHub</option>
          <option value="git">Git</option>
        </select>
      </label>
      <label className="field">
        <span>Workflow</span>
        <input value={workflow.workflow} onChange={(e) => workflow.setWorkflow(e.target.value)} />
      </label>
      <ApprovalChannelField approvalChannel={approvalChannel} />
    </div>
  );
}

function OnExhaustedField({ approvalLimits }: { approvalLimits: ApprovalLimitsState }) {
  return (
    <label className="field">
      <span>When revisions run out</span>
      <select value={approvalLimits.onExhausted} onChange={(e) => approvalLimits.setOnExhausted(e.target.value)}>
        <option value="">Default (escalate to a human)</option>
        <option value="escalate">Escalate to a human</option>
        <option value="accept_with_warnings">Accept with warnings</option>
      </select>
    </label>
  );
}

function ApprovalGateFields({ approvalChannel, approvalLimits }: { approvalChannel: ApprovalChannelState; approvalLimits: ApprovalLimitsState }) {
  return (
    <div className="form-grid">
      <label className="field">
        <span>Approval mode (SPEC / PLAN / TASK gates)</span>
        <select value={approvalChannel.approvalMode} onChange={(e) => approvalChannel.setApprovalMode(e.target.value)}>
          <option value="">Workflow default</option>
          <option value="ai">AI review</option>
          <option value="human">Human approval</option>
          <option value="none">No approval</option>
        </select>
      </label>
      <label className="field">
        <span>Max revisions (1-10, blank = default)</span>
        <input
          value={approvalLimits.maxRevisions}
          onChange={(e) => approvalLimits.setMaxRevisions(e.target.value)}
          inputMode="numeric"
          placeholder="4"
        />
      </label>
      <OnExhaustedField approvalLimits={approvalLimits} />
    </div>
  );
}

function ApprovalExplainer() {
  return (
    <p className="muted small">
      Approval mode decides who clears the SPEC, PLAN and TASK gates: the AI reviewer
      (artifact-review agent), a human on the Approvals page, or nobody. Max revisions bounds
      the AI review loop before it escalates; the server enforces the same 1-10 range.
    </p>
  );
}

function TechnologyFields({ tech, workflow }: { tech: TechState; workflow: WorkflowState }) {
  return (
    <>
      <div className="form-grid">
        <label className="field">
          <span>Backend technologies (comma separated)</span>
          <input value={tech.backend} onChange={(e) => tech.setBackend(e.target.value)} placeholder="java, spring" />
        </label>
        <label className="field">
          <span>Frontend technologies (comma separated)</span>
          <input value={tech.frontend} onChange={(e) => tech.setFrontend(e.target.value)} placeholder="react" />
        </label>
      </div>
      <label className="field block">
        <span>Enabled skills (comma separated)</span>
        <input value={workflow.skills} onChange={(e) => workflow.setSkills(e.target.value)} placeholder="git, testing, security" />
      </label>
    </>
  );
}

function RepositoryFields({ repoLink, onProviderChange }: { repoLink: RepoLinkState; onProviderChange: (value: string) => void }) {
  const changeRepoUrl = (value: string) => {
    repoLink.setRepoUrl(value);
    // Paste a GitHub or GitLab link and the provider follows it.
    try {
      const host = new URL(value.trim()).hostname;
      if (host === 'github.com') {
        onProviderChange('github');
      } else if (host.includes('gitlab')) {
        onProviderChange('gitlab');
      }
    } catch {
      // Not a URL yet; leave the provider as chosen.
    }
  };
  return (
    <label className="field block">
      <span>Repository URL (optional, for GitLab/GitHub CI)</span>
      <input
        value={repoLink.repoUrl}
        onChange={(e) => changeRepoUrl(e.target.value)}
        placeholder="https://github.com/owner/repo or https://gitlab.com/group/project"
        {...textInputAttrs('asf-repo-url')}
      />
    </label>
  );
}

function HostingTokenFields({ repoLink, initial }: { repoLink: RepoLinkState; initial?: ProjectProfileInput }) {
  return (
    <label className="field block">
      <span>
        Access token (optional, for the repository above)
        {initial?.hostingTokenConfigured && (
          <> — stored{initial.hostingTokenHint ? ` (${initial.hostingTokenHint})` : ' via the backend environment'}; leave blank to keep it</>
        )}
      </span>
      <input
        type="password"
        value={repoLink.hostingToken}
        onChange={(e) => repoLink.setHostingToken(e.target.value)}
        placeholder={initial?.hostingTokenConfigured ? 'Paste a new token to replace the stored one' : 'Paste this project’s GitLab/GitHub token'}
        {...secretInputAttrs('asf-hosting-token')}
      />
    </label>
  );
}

function ClearTokenField({ repoLink }: { repoLink: RepoLinkState }) {
  return (
    <label className="field block">
      <span>
        <input
          type="checkbox"
          checked={repoLink.clearToken}
          onChange={(e) => repoLink.setClearToken(e.target.checked)}
          disabled={Boolean(repoLink.hostingToken.trim())}
        />{' '}
        Remove the stored token on save
      </span>
    </label>
  );
}

function LocalFolderFields({ workspace, testCommand }: { workspace: WorkspaceState; testCommand: TestCommandState }) {
  return (
    <div className="form-grid">
      <label className="field">
        <span>Local folder path (optional)</span>
        <input
          value={workspace.workspacePath}
          onChange={(e) => workspace.setWorkspacePath(e.target.value)}
          placeholder="E:\projects\my-app"
        />
      </label>
      <label className="field">
        <span>Test command (optional)</span>
        <input
          value={testCommand.testCommand}
          onChange={(e) => testCommand.setTestCommand(e.target.value)}
          placeholder="python -m pytest -q"
        />
      </label>
    </div>
  );
}

function WorkspaceModeFields({ workspace }: { workspace: WorkspaceState }) {
  return (
    <div className="form-grid">
      <label className="field">
        <span>Workspace mode (for the local folder)</span>
        <select value={workspace.workspaceMode} onChange={(e) => workspace.setWorkspaceMode(e.target.value)}>
          <option value="direct">Direct — edit the folder, with an undo journal</option>
          <option value="worktree">Worktree — a separate git worktree per run</option>
          <option value="auto">Auto — worktree for git folders, direct otherwise</option>
        </select>
      </label>
      <label className="field">
        <span>
          <input
            type="checkbox"
            checked={workspace.keepChanges}
            onChange={(e) => workspace.setKeepChanges(e.target.checked)}
            disabled={workspace.workspaceMode !== 'direct'}
          />{' '}
          Keep changes when a run fails (direct mode)
        </span>
      </label>
    </div>
  );
}

function WorkspaceExplainer() {
  return (
    <p className="muted small">
      With a local folder set, agents read the project's real files, generated code is written into
      that folder, and the test command runs there for real. Without it, runs use the in-memory demo
      workspace. In direct mode the run edits the folder itself: an undo journal records every file
      before the run first writes it, a failed or cancelled run is reverted (unless you keep its
      changes), and nothing is ever auto-committed. In worktree mode each run works in its own git
      worktree and the folder stays untouched. With a repository URL set, the CI step pushes the generated code to a branch on
      GitLab/GitHub, opens a merge/pull request, and the run waits for it to merge. The access token
      is per project: paste it here and it is stored on the backend only — never in the project file
      and never shown again (only its last 4 characters). Without one, the backend falls back to its
      ASF_GITLAB_TOKEN / ASF_GITHUB_TOKEN environment variable.
    </p>
  );
}

function FormActions({ formStatus, identity, onCancel, submitLabel }: { formStatus: FormStatusState; identity: IdentityState; onCancel: () => void; submitLabel: string }) {
  return (
    <>
      {formStatus.error && (
        <p className="alert" role="alert">
          {formStatus.error}
        </p>
      )}
      <div className="filters">
        <button type="submit" className="btn btn-primary" disabled={formStatus.submitting || !identity.name.trim() || !identity.id.trim()}>
          {formStatus.submitting ? 'Saving…' : submitLabel}
        </button>
        <button type="button" className="btn" onClick={onCancel} disabled={formStatus.submitting}>
          Cancel
        </button>
      </div>
    </>
  );
}

/**
 * Creates or edits a project profile (the `projects/<id>.yaml` shape). With
 * a real backend the profile is validated server-side and persisted; in
 * mock mode it is kept in memory until reload.
 */
export function ProjectForm({ onCreate, onCancel, initial, title = 'New project', submitLabel = 'Create project' }: Props) {
  const state = useProjectFormState(initial);
  const submit = createSubmitHandler(state, onCreate);
  return (
    <Card title={title}>
      <form className="form" onSubmit={submit}>
        <IdentityFields identity={state.identity} editing={state.editing} />
        <DescriptionField identity={state.identity} />
        <ProviderWorkflowFields tech={state.tech} workflow={state.workflow} approvalChannel={state.approvalChannel} />
        <ApprovalGateFields approvalChannel={state.approvalChannel} approvalLimits={state.approvalLimits} />
        <ApprovalExplainer />
        <TechnologyFields tech={state.tech} workflow={state.workflow} />
        <RepositoryFields repoLink={state.repoLink} onProviderChange={state.tech.setProvider} />
        <HostingTokenFields repoLink={state.repoLink} initial={initial} />
        {initial?.hostingTokenConfigured && initial.hostingTokenHint && (
          <ClearTokenField repoLink={state.repoLink} />
        )}
        <LocalFolderFields workspace={state.workspace} testCommand={state.testCommand} />
        <WorkspaceModeFields workspace={state.workspace} />
        <WorkspaceExplainer />
        <FormActions formStatus={state.formStatus} identity={state.identity} onCancel={onCancel} submitLabel={submitLabel} />
      </form>
    </Card>
  );
}

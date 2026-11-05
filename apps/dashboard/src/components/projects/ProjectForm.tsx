import { useState, type FormEvent } from 'react';
import type { ProjectProfileInput } from '../../types/project';
import { Card } from '../common/Layout';

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

/**
 * Creates or edits a project profile (the `projects/<id>.yaml` shape). With
 * a real backend the profile is validated server-side and persisted; in
 * mock mode it is kept in memory until reload.
 */
export function ProjectForm({ onCreate, onCancel, initial, title = 'New project', submitLabel = 'Create project' }: Props) {
  const editing = initial !== undefined;
  const [name, setName] = useState(initial?.name ?? '');
  const [id, setId] = useState(initial?.id ?? '');
  const [idTouched, setIdTouched] = useState(editing);
  const [description, setDescription] = useState(initial?.description ?? '');
  const [provider, setProvider] = useState(initial?.repository.provider ?? 'gitlab');
  const [backend, setBackend] = useState((initial?.technology.backend ?? []).join(', '));
  const [frontend, setFrontend] = useState((initial?.technology.frontend ?? []).join(', '));
  const [workflow, setWorkflow] = useState(initial?.workflow ?? 'software-development');
  const [skills, setSkills] = useState((initial?.enabledSkills ?? []).join(', '));
  const [repoUrl, setRepoUrl] = useState(initial?.repository.url ?? '');
  const [hostingToken, setHostingToken] = useState('');
  const [clearToken, setClearToken] = useState(false);
  const [workspacePath, setWorkspacePath] = useState(initial?.repository.path ?? '');
  const [testCommand, setTestCommand] = useState(
    (initial?.configuration.testCommands?.[0] ?? []).join(' '),
  );
  const [channel, setChannel] = useState(
    initial ? (initial.configuration.approval?.channel ?? 'none') || 'none' : 'teams',
  );
  const [error, setError] = useState<string | undefined>();
  const [submitting, setSubmitting] = useState(false);

  const changeName = (value: string) => {
    setName(value);
    if (!idTouched) setId(slugify(value));
  };

  const changeRepoUrl = (value: string) => {
    setRepoUrl(value);
    // Paste a GitHub or GitLab link and the provider follows it.
    try {
      const host = new URL(value.trim()).hostname;
      if (host === 'github.com') setProvider('github');
      else if (host.includes('gitlab')) setProvider('gitlab');
    } catch {
      // Not a URL yet; leave the provider as chosen.
    }
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(undefined);
    setSubmitting(true);
    const testCommands = testCommand.trim() ? [testCommand.trim().split(/\s+/)] : [];
    try {
      await onCreate({
        id: id.trim(),
        name: name.trim(),
        // In edit mode always send the description so clearing it works.
        ...(description.trim() || editing ? { description: description.trim() } : {}),
        repository: { provider, path: workspacePath.trim(), url: repoUrl.trim() },
        technology: { backend: list(backend), frontend: list(frontend) },
        workflow: workflow.trim() || 'software-development',
        enabledSkills: list(skills),
        // In edit mode an explicit empty channel clears a stored one on merge.
        configuration: {
          ...(channel === 'none'
            ? editing
              ? { approval: { channel: '' } }
              : {}
            : { approval: { channel } }),
          // In edit mode an empty test command clears the stored one.
          ...(testCommands.length || editing ? { testCommands } : {}),
        },
        // Write-only: a typed token replaces the stored one; the clear
        // checkbox removes it. Blank + unchecked leaves it untouched.
        ...(hostingToken.trim() ? { hostingToken: hostingToken.trim() } : {}),
        ...(clearToken && !hostingToken.trim() ? { clearHostingToken: true } : {}),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create project');
      setSubmitting(false);
    }
  };

  return (
    <Card title={title}>
      <form className="form" onSubmit={submit}>
        <div className="form-grid">
          <label className="field">
            <span>Project name</span>
            <input value={name} onChange={(e) => changeName(e.target.value)} required placeholder="My Project" />
          </label>
          <label className="field">
            <span>Project ID (slug)</span>
            <input
              value={id}
              onChange={(e) => {
                setId(e.target.value);
                setIdTouched(true);
              }}
              required
              readOnly={editing}
              placeholder="my-project"
            />
          </label>
        </div>
        <label className="field block">
          <span>Description (optional)</span>
          <input value={description} onChange={(e) => setDescription(e.target.value)} />
        </label>
        <div className="form-grid">
          <label className="field">
            <span>Repository provider</span>
            <select value={provider} onChange={(e) => setProvider(e.target.value)}>
              <option value="gitlab">GitLab</option>
              <option value="github">GitHub</option>
              <option value="git">Git</option>
            </select>
          </label>
          <label className="field">
            <span>Workflow</span>
            <input value={workflow} onChange={(e) => setWorkflow(e.target.value)} />
          </label>
          <label className="field">
            <span>Approval channel</span>
            <select value={channel} onChange={(e) => setChannel(e.target.value)}>
              <option value="teams">Microsoft Teams</option>
              <option value="slack">Slack</option>
              <option value="none">None</option>
            </select>
          </label>
        </div>
        <div className="form-grid">
          <label className="field">
            <span>Backend technologies (comma separated)</span>
            <input value={backend} onChange={(e) => setBackend(e.target.value)} placeholder="java, spring" />
          </label>
          <label className="field">
            <span>Frontend technologies (comma separated)</span>
            <input value={frontend} onChange={(e) => setFrontend(e.target.value)} placeholder="react" />
          </label>
        </div>
        <label className="field block">
          <span>Enabled skills (comma separated)</span>
          <input value={skills} onChange={(e) => setSkills(e.target.value)} placeholder="git, testing, security" />
        </label>
        <label className="field block">
          <span>Repository URL (optional, for GitLab/GitHub CI)</span>
          <input
            value={repoUrl}
            onChange={(e) => changeRepoUrl(e.target.value)}
            placeholder="https://github.com/owner/repo or https://gitlab.com/group/project"
          />
        </label>
        <label className="field block">
          <span>
            Access token (optional, for the repository above)
            {initial?.hostingTokenConfigured && (
              <> — stored{initial.hostingTokenHint ? ` (${initial.hostingTokenHint})` : ' via the backend environment'}; leave blank to keep it</>
            )}
          </span>
          <input
            type="password"
            value={hostingToken}
            onChange={(e) => setHostingToken(e.target.value)}
            placeholder={initial?.hostingTokenConfigured ? 'Paste a new token to replace the stored one' : 'Paste this project’s GitLab/GitHub token'}
            autoComplete="off"
          />
        </label>
        {initial?.hostingTokenConfigured && initial.hostingTokenHint && (
          <label className="field block">
            <span>
              <input
                type="checkbox"
                checked={clearToken}
                onChange={(e) => setClearToken(e.target.checked)}
                disabled={Boolean(hostingToken.trim())}
              />{' '}
              Remove the stored token on save
            </span>
          </label>
        )}
        <div className="form-grid">
          <label className="field">
            <span>Local folder path (optional)</span>
            <input
              value={workspacePath}
              onChange={(e) => setWorkspacePath(e.target.value)}
              placeholder="E:\projects\my-app"
            />
          </label>
          <label className="field">
            <span>Test command (optional)</span>
            <input
              value={testCommand}
              onChange={(e) => setTestCommand(e.target.value)}
              placeholder="python -m pytest -q"
            />
          </label>
        </div>
        <p className="muted small">
          With a local folder set, agents read the project's real files, generated code is written into
          that folder, and the test command runs there for real. Without it, runs use the in-memory demo
          workspace. With a repository URL set, the CI step pushes the generated code to a branch on
          GitLab/GitHub, opens a merge/pull request, and the run waits for it to merge. The access token
          is per project: paste it here and it is stored on the backend only — never in the project file
          and never shown again (only its last 4 characters). Without one, the backend falls back to its
          ASF_GITLAB_TOKEN / ASF_GITHUB_TOKEN environment variable.
        </p>
        {error && (
          <p className="alert" role="alert">
            {error}
          </p>
        )}
        <div className="filters">
          <button type="submit" className="btn btn-primary" disabled={submitting || !name.trim() || !id.trim()}>
            {submitting ? 'Saving…' : submitLabel}
          </button>
          <button type="button" className="btn" onClick={onCancel} disabled={submitting}>
            Cancel
          </button>
        </div>
      </form>
    </Card>
  );
}

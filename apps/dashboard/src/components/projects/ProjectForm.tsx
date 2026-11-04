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
        repository: { provider, path: workspacePath.trim() },
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
          workspace.
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

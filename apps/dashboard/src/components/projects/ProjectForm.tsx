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
}

/**
 * Creates a project profile (the `projects/<id>.yaml` shape). With a real
 * backend the profile is validated server-side and persisted; in mock mode
 * it is kept in memory until reload.
 */
export function ProjectForm({ onCreate, onCancel }: Props) {
  const [name, setName] = useState('');
  const [id, setId] = useState('');
  const [idTouched, setIdTouched] = useState(false);
  const [description, setDescription] = useState('');
  const [provider, setProvider] = useState('gitlab');
  const [backend, setBackend] = useState('');
  const [frontend, setFrontend] = useState('');
  const [workflow, setWorkflow] = useState('software-development');
  const [skills, setSkills] = useState('');
  const [channel, setChannel] = useState('teams');
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
    try {
      await onCreate({
        id: id.trim(),
        name: name.trim(),
        ...(description.trim() ? { description: description.trim() } : {}),
        repository: { provider },
        technology: { backend: list(backend), frontend: list(frontend) },
        workflow: workflow.trim() || 'software-development',
        enabledSkills: list(skills),
        configuration: channel === 'none' ? {} : { approval: { channel } },
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create project');
      setSubmitting(false);
    }
  };

  return (
    <Card title="New project">
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
        {error && (
          <p className="alert" role="alert">
            {error}
          </p>
        )}
        <div className="filters">
          <button type="submit" className="btn btn-primary" disabled={submitting || !name.trim() || !id.trim()}>
            {submitting ? 'Creating…' : 'Create project'}
          </button>
          <button type="button" className="btn" onClick={onCancel} disabled={submitting}>
            Cancel
          </button>
        </div>
      </form>
    </Card>
  );
}

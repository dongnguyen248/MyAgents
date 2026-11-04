import { useState, type FormEvent } from 'react';
import type { Project } from '../../types/project';
import type { StartRunInput, TaskPriority, WorkflowType } from '../../types/task';
import { Card } from '../common/Layout';

const slugify = (value: string): string =>
  value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');

interface Props {
  projects: Project[];
  onCreate: (input: StartRunInput) => Promise<void>;
  onCancel: () => void;
}

/**
 * Starts a task: creates a workflow run on the chosen project with the
 * given requirement. The run then advances step by step (Workflows page)
 * and pauses for approval on the Approvals page.
 */
export function TaskForm({ projects, onCreate, onCancel }: Props) {
  const [projectId, setProjectId] = useState(projects[0]?.id ?? '');
  const [title, setTitle] = useState('');
  const [taskId, setTaskId] = useState('');
  const [idTouched, setIdTouched] = useState(false);
  const [requirement, setRequirement] = useState('');
  const [priority, setPriority] = useState<TaskPriority>('MEDIUM');
  const [workflowType, setWorkflowType] = useState<WorkflowType>('feature-development');
  const [error, setError] = useState<string | undefined>();
  const [submitting, setSubmitting] = useState(false);

  const changeTitle = (value: string) => {
    setTitle(value);
    if (!idTouched) setTaskId(slugify(value));
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(undefined);
    setSubmitting(true);
    try {
      await onCreate({
        taskId: taskId.trim(),
        projectId,
        title: title.trim() || undefined,
        requirement: requirement.trim(),
        priority,
        workflowType,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create task');
      setSubmitting(false);
    }
  };

  return (
    <Card title="New task">
      <form className="form" onSubmit={submit}>
        <div className="form-grid">
          <label className="field">
            <span>Project</span>
            <select value={projectId} onChange={(e) => setProjectId(e.target.value)} required>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} ({p.id})
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Priority</span>
            <select value={priority} onChange={(e) => setPriority(e.target.value as TaskPriority)}>
              <option value="LOW">Low</option>
              <option value="MEDIUM">Medium</option>
              <option value="HIGH">High</option>
              <option value="CRITICAL">Critical</option>
            </select>
          </label>
          <label className="field">
            <span>Workflow type</span>
            <select value={workflowType} onChange={(e) => setWorkflowType(e.target.value as WorkflowType)}>
              <option value="feature-development">Feature development</option>
              <option value="bug-fix">Bug fix</option>
              <option value="refactoring">Refactoring</option>
            </select>
          </label>
        </div>
        <div className="form-grid">
          <label className="field">
            <span>Title</span>
            <input value={title} onChange={(e) => changeTitle(e.target.value)} placeholder="Build a small calculator module" />
          </label>
          <label className="field">
            <span>Task ID (slug)</span>
            <input
              value={taskId}
              onChange={(e) => {
                setTaskId(e.target.value);
                setIdTouched(true);
              }}
              required
              placeholder="calculator-module"
            />
          </label>
        </div>
        <label className="field block">
          <span>Requirement — what should the agents build?</span>
          <textarea
            value={requirement}
            onChange={(e) => setRequirement(e.target.value)}
            required
            rows={4}
            placeholder="Build a small calculator module with add and subtract, plus unit tests."
          />
        </label>
        {error && (
          <p className="alert" role="alert">
            {error}
          </p>
        )}
        <div className="filters">
          <button
            type="submit"
            className="btn btn-primary"
            disabled={submitting || !projectId || !taskId.trim() || !requirement.trim()}
          >
            {submitting ? 'Creating…' : 'Create task'}
          </button>
          <button type="button" className="btn" onClick={onCancel} disabled={submitting}>
            Cancel
          </button>
        </div>
      </form>
    </Card>
  );
}

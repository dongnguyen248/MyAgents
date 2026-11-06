import { useState } from 'react';
import type { Project } from '../../types/project';
import { pct } from '../../utils/format';
import { CiBadge } from '../common/Badge';
import { Card, Stat } from '../common/Layout';

interface Props {
  project: Project;
  onEdit?: (project: Project) => void;
  onDelete?: (project: Project) => Promise<void>;
}

export function ProjectCard({ project: p, onEdit, onDelete }: Props) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | undefined>();

  const remove = async () => {
    if (!onDelete) {return;}
    setBusy(true);
    setError(undefined);
    try {
      await onDelete(p);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete project');
      setBusy(false);
      setConfirming(false);
    }
  };

  return (
    <Card title={p.name} actions={<CiBadge status={p.ci} />}>
      <p className="muted small">{p.repositoryProvider} · {p.technologies.join(', ')}</p>
      <dl className="stats stats-2">
        <Stat label="Active agents" value={p.metrics.activeAgents} />
        <Stat label="Running tasks" value={p.metrics.running} />
        <Stat label="Completed" value={p.metrics.completed} />
        <Stat label="Failed" value={p.metrics.failed} />
        <Stat label="Success rate" value={pct(p.metrics.successRate, 0)} />
        <Stat label="Pending approvals" value={p.metrics.pendingApprovals} />
        <Stat label="CI failures (24h)" value={p.ciFailures24h} />
      </dl>
      {(onEdit || onDelete) && (
        <div className="toolbar" style={{ marginTop: 12 }}>
          {onEdit && (
            <button type="button" className="btn" onClick={() => onEdit(p)}>
              Edit
            </button>
          )}
          {onDelete && !confirming && (
            <button type="button" className="btn btn-danger" onClick={() => setConfirming(true)}>
              Delete
            </button>
          )}
          {onDelete && confirming && (
            <>
              <span className="small">Delete this project?</span>
              <button type="button" className="btn btn-danger" disabled={busy} onClick={remove}>
                {busy ? 'Deleting…' : 'Confirm delete'}
              </button>
              <button type="button" className="btn" disabled={busy} onClick={() => setConfirming(false)}>
                Cancel
              </button>
            </>
          )}
        </div>
      )}
      {error && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}
    </Card>
  );
}

import type { Workflow } from '../../types/workflow';
import { Card } from '../common/Layout';

const MODE_LABELS: Record<string, string> = {
  direct: 'Direct (folder edited in place)',
  worktree: 'Per-run git worktree',
};

const JOURNAL_LABELS: Record<string, string> = {
  active: 'Journal active — changes can still be reverted',
  reverted: 'Changes reverted at run end',
  kept: 'Changes kept in the folder',
  conflict: 'Revert skipped file(s) the user edited',
};

/**
 * The run's local-workspace block: which folder the agents worked in,
 * in which mode, what they wrote, and what happened to the undo
 * journal. Renders nothing for projects without a local folder.
 */
export function WorkspaceInfo({ workflow }: { workflow: Workflow }) {
  const workspace = workflow.workspace;
  if (!workspace) {
    return null;
  }
  const journalLabel = workspace.journalState ? JOURNAL_LABELS[workspace.journalState] : null;
  return (
    <Card title="Workspace">
      <p className="small">
        <strong>{MODE_LABELS[workspace.mode] ?? workspace.mode}</strong>
        {workspace.configuredMode !== workspace.mode && (
          <span className="muted"> (project setting: {workspace.configuredMode})</span>
        )}
      </p>
      <p className="small muted">Folder: {workspace.folderPath}</p>
      {journalLabel && <p className="small">{journalLabel}</p>}
      {workspace.filesWritten.length > 0 && (
        <p className="small muted">
          Files written ({workspace.filesWritten.length}): {workspace.filesWritten.join(', ')}
        </p>
      )}
      {workspace.conflicts && workspace.conflicts.length > 0 && (
        <p className="alert" role="alert">
          Not reverted — edited by you after the run wrote them: {workspace.conflicts.join(', ')}
        </p>
      )}
    </Card>
  );
}

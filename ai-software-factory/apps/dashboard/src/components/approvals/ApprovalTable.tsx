import type { Approval } from '../../types/approval';
import { ago, titleCase } from '../../utils/format';
import { Badge, type Tone } from '../common/Badge';
import { EmptyState } from '../common/Layout';

const STATUS: Record<Approval['status'], [Tone, string]> = {
  PENDING: ['warn', '◔'],
  APPROVED: ['ok', '✓'],
  REJECTED: ['danger', '✕'],
  CHANGES_REQUESTED: ['info', '✎'],
};

export const ApprovalStatusBadge = ({ status }: { status: Approval['status'] }) => (
  <Badge tone={STATUS[status][0]} icon={STATUS[status][1]}>{titleCase(status)}</Badge>
);

interface Props {
  approvals: Approval[];
  selectedId?: string;
  onSelect?: (id: string) => void;
}

export function ApprovalTable({ approvals, selectedId, onSelect }: Props) {
  if (!approvals.length) return <EmptyState>No approvals.</EmptyState>;
  return (
    <div className="table-wrap">
      <table className="table">
        <caption className="sr-only">Approvals</caption>
        <thead>
          <tr>
            <th scope="col">Project</th>
            <th scope="col">Type</th>
            <th scope="col">Task</th>
            <th scope="col">Status</th>
            <th scope="col">Waiting since</th>
          </tr>
        </thead>
        <tbody>
          {approvals.map((a) => (
            <tr key={a.id} className={a.id === selectedId ? 'selected' : undefined}>
              <td>{a.projectId.toUpperCase()}</td>
              <td>{titleCase(a.type)}</td>
              <th scope="row">
                {onSelect ? (
                  <button type="button" className="link" onClick={() => onSelect(a.id)} aria-pressed={a.id === selectedId}>{a.taskId}</button>
                ) : (
                  a.taskId
                )}
              </th>
              <td><ApprovalStatusBadge status={a.status} /></td>
              <td>{ago(a.requestedAt)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

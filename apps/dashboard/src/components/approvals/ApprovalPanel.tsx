import { useState } from 'react';
import { Link } from 'react-router-dom';
import type { Approval, ApprovalDecisionKind } from '../../types/approval';
import { ago, clock, titleCase } from '../../utils/format';
import { Card } from '../common/Layout';
import { ApprovalStatusBadge } from './ApprovalTable';

interface Props {
  approval: Approval;
  busy: boolean;
  message?: string;
  onDecide: (decision: ApprovalDecisionKind, comment?: string) => void;
}

export function ApprovalPanel({ approval: a, busy, message, onDecide }: Props) {
  const [comment, setComment] = useState('');
  const act = (d: ApprovalDecisionKind) => {
    onDecide(d, comment.trim() || undefined);
    setComment('');
  };
  const pending = a.status === 'PENDING';
  return (
    <Card title={`${titleCase(a.type)} approval · ${a.taskId}`}>
      <p><ApprovalStatusBadge status={a.status} /> <span className="muted">requested {ago(a.requestedAt)} by {a.requestedByAgentId}</span></p>
      <p>{a.summary}</p>
      <p className="muted small">Artifact: {a.artifact} · <Link to={`/tasks/${a.taskId}`}>Open task</Link></p>
      {a.comments.length > 0 && (
        <ul className="comments">
          {a.comments.map((c, i) => (
            <li key={i}><strong>{c.author}</strong> <span className="muted small">{clock(c.at)}</span><div>{c.text}</div></li>
          ))}
        </ul>
      )}
      <label className="field block">
        <span>Comment</span>
        <textarea rows={3} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Add feedback for the agent…" />
      </label>
      <div className="toolbar">
        <button type="button" className="btn btn-primary" disabled={busy || !pending} onClick={() => act('APPROVE')}>Approve</button>
        <button type="button" className="btn" disabled={busy || !pending} onClick={() => act('REQUEST_CHANGES')}>Request changes</button>
        <button type="button" className="btn btn-danger" disabled={busy || !pending} onClick={() => act('REJECT')}>Reject</button>
        <button type="button" className="btn" disabled={busy || !comment.trim()} onClick={() => act('COMMENT')}>Comment</button>
      </div>
      {message && <p className="muted small" role="status">{message}</p>}
    </Card>
  );
}

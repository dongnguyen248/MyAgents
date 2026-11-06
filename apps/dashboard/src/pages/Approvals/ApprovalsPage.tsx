import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ApprovalPanel } from '../../components/approvals/ApprovalPanel';
import { ApprovalTable } from '../../components/approvals/ApprovalTable';
import { AsyncView } from '../../components/common/AsyncView';
import { Card, PageHeader } from '../../components/common/Layout';
import { ReviewTimeline } from '../../components/workflows/ReviewTimeline';
import { groupApprovals, type ApprovalGroups } from '../../lib/approvalGroups';
import type { Approval, ApprovalDecisionKind } from '../../types/approval';
import type { Workflow } from '../../types/workflow';
import { useAiReviewHistory, useApprovalDecision, useApprovals } from '../../features/approval-management';
import { useWorkflows } from '../../features/workflow-monitoring';
import { titleCase } from '../../utils/format';

interface DecisionProps {
  busy: boolean;
  message?: string;
  onDecide: (approval: Approval, decision: ApprovalDecisionKind, comment: string | undefined) => void;
}

function EscalatedRunList({ workflows }: { workflows: Workflow[] }) {
  if (workflows.length === 0) {
    return null;
  }
  return (
    <ul>
      {workflows.map((w) => (
        <li key={w.id}>
          <Link to={`/workflows/${w.id}`}>{w.taskId}</Link>{' '}
          <span className="muted small">
            {w.projectId.toUpperCase()} · escalated — resume or approve on the run page
          </span>
        </li>
      ))}
    </ul>
  );
}

function NeedsHumanCard(props: {
  groups: ApprovalGroups;
  selected?: Approval;
  onSelect: (id: string) => void;
  decision: DecisionProps;
}) {
  const { groups, selected, onSelect, decision } = props;
  return (
    <div className="grid two-col">
      <Card title="Needs human" flush>
        <ApprovalTable approvals={groups.needsHuman} selectedId={selected?.id} onSelect={onSelect} />
        <EscalatedRunList workflows={groups.escalated} />
      </Card>
      {selected && (
        <ApprovalPanel
          key={selected.id}
          approval={selected}
          busy={decision.busy}
          message={decision.message}
          onDecide={(d, c) => decision.onDecide(selected, d, c)}
        />
      )}
    </div>
  );
}

function ReviewHistoryList({ reviewingCount }: { reviewingCount: number }) {
  const history = useAiReviewHistory();
  return (
    <AsyncView {...history}>
      {(entries) =>
        entries.length === 0 && reviewingCount === 0 ? (
          <p className="muted">No AI review rounds yet.</p>
        ) : (
          <div>
            {entries.map((entry) => (
              <div key={entry.runId}>
                <p>
                  <Link to={`/workflows/${entry.runId}`}>{entry.taskId}</Link>{' '}
                  <span className="muted small">
                    {entry.projectId.toUpperCase()} · {titleCase(entry.status)}
                  </span>
                </p>
                <ReviewTimeline reviews={{ runId: entry.runId, stages: entry.stages }} />
              </div>
            ))}
          </div>
        )
      }
    </AsyncView>
  );
}

function AiReviewedCard({ groups }: { groups: ApprovalGroups }) {
  return (
    <Card title="AI reviewed">
      {groups.aiReviewing.length > 0 && (
        <ul>
          {groups.aiReviewing.map((a) => (
            <li key={a.id}>
              {a.workflowId ? <Link to={`/workflows/${a.workflowId}`}>{a.taskId}</Link> : a.taskId}{' '}
              <span className="muted small">
                {titleCase(a.type)} · AI review in progress — a human decision overrides it
              </span>
            </li>
          ))}
        </ul>
      )}
      <ReviewHistoryList reviewingCount={groups.aiReviewing.length} />
    </Card>
  );
}

interface SectionsProps {
  list: Approval[];
  workflows: Workflow[];
  selectedId?: string;
  onSelect: (id: string) => void;
  decision: DecisionProps;
}

function ApprovalsSections(props: SectionsProps) {
  const groups = groupApprovals(props.list, props.workflows);
  const selected =
    groups.needsHuman.find((a) => a.id === props.selectedId) ??
    groups.needsHuman.find((a) => a.status === 'PENDING');
  return (
    <>
      <NeedsHumanCard
        groups={groups}
        selected={selected}
        onSelect={props.onSelect}
        decision={props.decision}
      />
      <AiReviewedCard groups={groups} />
    </>
  );
}

/**
 * Two worlds (Phase 12): "Needs human" holds the gates a person
 * must decide plus the escalated runs (decided on the run page);
 * "AI reviewed" is the read-only record of the AI review loop —
 * gates it is deciding right now and the rounds it already ran.
 */
export function ApprovalsPage() {
  const approvals = useApprovals();
  const workflows = useWorkflows();
  const [selectedId, setSelectedId] = useState<string>();
  const { submit, busy, message } = useApprovalDecision(approvals.reload);
  const decision: DecisionProps = {
    busy,
    message,
    onDecide: (approval, d, c) => submit(approval.id, { decision: d, comment: c }),
  };

  return (
    <>
      <PageHeader
        title="Approvals"
        subtitle="Human decisions the factory is waiting for, and the AI review history."
      />
      <AsyncView {...approvals}>
        {(list) => (
          <ApprovalsSections
            list={list}
            workflows={workflows.data ?? []}
            selectedId={selectedId}
            onSelect={setSelectedId}
            decision={decision}
          />
        )}
      </AsyncView>
    </>
  );
}

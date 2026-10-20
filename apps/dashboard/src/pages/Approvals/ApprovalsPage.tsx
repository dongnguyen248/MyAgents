import { useState } from 'react';
import { ApprovalPanel } from '../../components/approvals/ApprovalPanel';
import { ApprovalTable } from '../../components/approvals/ApprovalTable';
import { AsyncView } from '../../components/common/AsyncView';
import { Card, PageHeader } from '../../components/common/Layout';
import { useApprovalDecision, useApprovals } from '../../features/approval-management';

export function ApprovalsPage() {
  const approvals = useApprovals();
  const [selectedId, setSelectedId] = useState<string>();
  const { submit, busy, message } = useApprovalDecision(approvals.reload);

  return (
    <>
      <PageHeader title="Approvals" subtitle="Human decisions the factory is waiting for. Actions are mocked." />
      <AsyncView {...approvals}>
        {(list) => {
          const selected = list.find((a) => a.id === selectedId) ?? list.find((a) => a.status === 'PENDING');
          return (
            <div className="grid two-col">
              <Card title="Approvals" flush>
                <ApprovalTable approvals={[...list].sort((a, b) => Number(b.status === 'PENDING') - Number(a.status === 'PENDING'))} selectedId={selected?.id} onSelect={setSelectedId} />
              </Card>
              {selected && <ApprovalPanel key={selected.id} approval={selected} busy={busy} message={message} onDecide={(d, c) => submit(selected.id, { decision: d, comment: c })} />}
            </div>
          );
        }}
      </AsyncView>
    </>
  );
}

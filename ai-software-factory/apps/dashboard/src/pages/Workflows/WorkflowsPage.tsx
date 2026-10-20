import { useState } from 'react';
import { Link } from 'react-router-dom';
import { AsyncView } from '../../components/common/AsyncView';
import { Card, PageHeader } from '../../components/common/Layout';
import { WorkflowStatusBadge } from '../../components/workflows/WorkflowStatusBadge';
import { WorkflowStepper } from '../../components/workflows/WorkflowStepper';
import { useWorkflows } from '../../features/workflow-monitoring';
import { ago, titleCase } from '../../utils/format';

export function WorkflowsPage() {
  const workflows = useWorkflows();
  const [activeOnly, setActiveOnly] = useState(true);
  return (
    <>
      <PageHeader
        title="Workflows"
        subtitle="Progress of each work item through the factory pipeline."
        actions={<label className="check"><input type="checkbox" checked={activeOnly} onChange={(e) => setActiveOnly(e.target.checked)} /> Running only</label>}
      />
      <AsyncView {...workflows}>
        {(list) => {
          const shown = list.filter((w) => !activeOnly || ['RUNNING', 'WAITING_APPROVAL'].includes(w.status));
          return (
            <div className="grid grid-cards">
              {shown.map((w) => (
                <Card key={w.id} title={w.taskId} actions={<WorkflowStatusBadge status={w.status} />}>
                  <p><Link to={`/workflows/${w.id}`}>{w.title}</Link></p>
                  <p className="muted small">{w.projectId.toUpperCase()} · {titleCase(w.type)} · updated {ago(w.updatedAt)}</p>
                  <WorkflowStepper steps={w.steps} compact />
                </Card>
              ))}
            </div>
          );
        }}
      </AsyncView>
    </>
  );
}

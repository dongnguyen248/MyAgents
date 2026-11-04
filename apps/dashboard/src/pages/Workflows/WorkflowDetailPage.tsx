import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ActivityFeed } from '../../components/activity/ActivityFeed';
import { AsyncView } from '../../components/common/AsyncView';
import { Card, PageHeader } from '../../components/common/Layout';
import { WorkflowArtifacts } from '../../components/workflows/WorkflowArtifacts';
import { WorkflowStatusBadge } from '../../components/workflows/WorkflowStatusBadge';
import { WorkflowStepper } from '../../components/workflows/WorkflowStepper';
import { retryWorkflow, tickWorkflow, useWorkflowDetail } from '../../features/workflow-monitoring';
import { titleCase } from '../../utils/format';

export function WorkflowDetailPage() {
  const { workflowId = '' } = useParams();
  const detail = useWorkflowDetail(workflowId);
  const navigate = useNavigate();
  const [ticking, setTicking] = useState(false);
  const [tickError, setTickError] = useState<string | undefined>();
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState<string | undefined>();

  const runAgain = async () => {
    setRetryError(undefined);
    setRetrying(true);
    try {
      const fresh = await retryWorkflow(workflowId);
      navigate(`/workflows/${fresh.id}`);
    } catch (err) {
      setRetryError(err instanceof Error ? err.message : 'Failed to run again');
    } finally {
      setRetrying(false);
    }
  };

  const runNextStep = async () => {
    setTickError(undefined);
    setTicking(true);
    try {
      await tickWorkflow(workflowId);
      detail.reload();
    } catch (err) {
      setTickError(err instanceof Error ? err.message : 'Failed to run the next step');
    } finally {
      setTicking(false);
    }
  };

  return (
    <AsyncView {...detail}>
      {({ workflow, events }) =>
        !workflow ? (
          <p className="muted">Workflow not found.</p>
        ) : (
          <>
            <PageHeader
              title={`${workflow.taskId} · ${workflow.title}`}
              subtitle={`${workflow.projectId.toUpperCase()} · ${titleCase(workflow.type)}`}
              back={{ to: '/workflows', label: 'Workflows' }}
              actions={<><WorkflowStatusBadge status={workflow.status} /><Link className="btn" to={`/tasks/${workflow.taskId}`}>Open task</Link></>}
            />
            {workflow.status === 'RUNNING' && (
              <Card>
                <div className="filters">
                  <button type="button" className="btn btn-primary" onClick={runNextStep} disabled={ticking}>
                    {ticking ? 'Running…' : 'Run next step'}
                  </button>
                  <span className="muted small">Runs one engine step; the run pauses again at the next approval.</span>
                </div>
                {tickError && (
                  <p className="alert" role="alert">
                    {tickError}
                  </p>
                )}
              </Card>
            )}
            {['FAILED', 'CANCELLED', 'COMPLETED'].includes(workflow.status) && (
              <Card>
                <div className="filters">
                  <button type="button" className="btn btn-primary" onClick={runAgain} disabled={retrying}>
                    {retrying ? 'Starting…' : 'Run again'}
                  </button>
                  <span className="muted small">Starts a fresh run of this task with its original requirement; this finished run stays as the record.</span>
                </div>
                {retryError && (
                  <p className="alert" role="alert">
                    {retryError}
                  </p>
                )}
              </Card>
            )}
            {workflow.status === 'WAITING_APPROVAL' && (
              <Card>
                <p className="muted">
                  This run is waiting for approval. Review the artifact and decide on the{' '}
                  <Link to="/approvals">Approvals page</Link>, then come back and run the next step.
                </p>
              </Card>
            )}
            <div className="grid two-col">
              <Card title="Steps"><WorkflowStepper steps={workflow.steps} /></Card>
              <Card title="Execution history"><ActivityFeed events={events} showTask={false} /></Card>
            </div>
            <WorkflowArtifacts artifacts={workflow.artifacts} />
          </>
        )
      }
    </AsyncView>
  );
}

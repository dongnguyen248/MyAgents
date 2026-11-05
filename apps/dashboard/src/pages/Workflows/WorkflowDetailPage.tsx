import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ActivityFeed } from '../../components/activity/ActivityFeed';
import { AsyncView } from '../../components/common/AsyncView';
import { Card, PageHeader } from '../../components/common/Layout';
import { WorkflowArtifacts } from '../../components/workflows/WorkflowArtifacts';
import { RunLiveActivity } from '../../components/workflows/RunLiveActivity';
import { WorkflowErrorBanner } from '../../components/workflows/WorkflowErrorBanner';
import { WorkflowStatusBadge } from '../../components/workflows/WorkflowStatusBadge';
import { WorkflowStepper } from '../../components/workflows/WorkflowStepper';
import { resumeWorkflow, retryWorkflow, useWorkflowDetail } from '../../features/workflow-monitoring';
import { titleCase } from '../../utils/format';

export function WorkflowDetailPage() {
  const { workflowId = '' } = useParams();
  const detail = useWorkflowDetail(workflowId);
  const navigate = useNavigate();
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState<string | undefined>();
  const [resuming, setResuming] = useState(false);
  const [resumeError, setResumeError] = useState<string | undefined>();

  // While a run is live, keep the page fresh on its own: steps, the
  // execution log and the "agent is working" strip advance without a
  // manual refresh.
  const workflowStatus = detail.data?.workflow?.status;
  const reloadDetail = detail.reload;
  useEffect(() => {
    if (workflowStatus !== 'RUNNING') return;
    const timer = setInterval(reloadDetail, 4000);
    return () => clearInterval(timer);
  }, [workflowStatus, reloadDetail]);

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

  const resume = async () => {
    setResumeError(undefined);
    setResuming(true);
    try {
      const fresh = await resumeWorkflow(workflowId);
      navigate(`/workflows/${fresh.id}`);
    } catch (err) {
      setResumeError(err instanceof Error ? err.message : 'Failed to resume');
    } finally {
      setResuming(false);
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
            <WorkflowErrorBanner workflow={workflow} />
            {['FAILED', 'CANCELLED', 'COMPLETED'].includes(workflow.status) && (
              <Card>
                <div className="filters">
                  {workflow.status === 'FAILED' && (
                    <button type="button" className="btn btn-primary" onClick={resume} disabled={resuming || retrying}>
                      {resuming ? 'Resuming…' : 'Resume from failure'}
                    </button>
                  )}
                  <button type="button" className={workflow.status === 'FAILED' ? 'btn' : 'btn btn-primary'} onClick={runAgain} disabled={retrying || resuming}>
                    {retrying ? 'Starting…' : 'Run again'}
                  </button>
                  <span className="muted small">
                    {workflow.status === 'FAILED'
                      ? 'Resume keeps the approved spec, plan and task breakdown and re-runs only the failed step. Run again starts over from the spec; either way this failed run stays as the record.'
                      : 'Starts a fresh run of this task with its original requirement; this finished run stays as the record.'}
                  </span>
                </div>
                {(retryError || resumeError) && (
                  <p className="alert" role="alert">
                    {resumeError ?? retryError}
                  </p>
                )}
              </Card>
            )}
            {workflow.status === 'WAITING_APPROVAL' && (
              <Card>
                <p className="muted">
                  This run is waiting for approval. Review the artifact and decide on the{' '}
                  <Link to="/approvals">Approvals page</Link> — once decided, the run continues
                  on its own to the next step.
                </p>
              </Card>
            )}
            <RunLiveActivity workflow={workflow} />
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

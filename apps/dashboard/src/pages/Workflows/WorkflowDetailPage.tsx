import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ActivityFeed } from '../../components/activity/ActivityFeed';
import { AsyncView } from '../../components/common/AsyncView';
import { Card, PageHeader } from '../../components/common/Layout';
import { WorkflowArtifacts } from '../../components/workflows/WorkflowArtifacts';
import { EscalatedPanel } from '../../components/workflows/EscalatedPanel';
import { ReviewTimeline } from '../../components/workflows/ReviewTimeline';
import { RunLabel } from '../../components/workflows/RunLabel';
import { RunLiveActivity } from '../../components/workflows/RunLiveActivity';
import { WorkspaceInfo } from '../../components/workflows/WorkspaceInfo';
import { WorkflowDiagnostics } from '../../components/workflows/WorkflowDiagnostics';
import { OperatorControls } from '../../components/workflows/OperatorControls';
import { WorkflowErrorBanner } from '../../components/workflows/WorkflowErrorBanner';
import { WorkflowStatusBadge } from '../../components/workflows/WorkflowStatusBadge';
import { WorkflowStepper } from '../../components/workflows/WorkflowStepper';
import { cancelWorkflow, resumeWorkflow, retryWorkflow, useRunLiveRefetch, useRunReviews, useWorkflowDetail } from '../../features/workflow-monitoring';
import { titleCase } from '../../utils/format';

export function WorkflowDetailPage() {
  const { workflowId = '' } = useParams();
  const detail = useWorkflowDetail(workflowId);
  const reviews = useRunReviews(workflowId);
  const navigate = useNavigate();
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState<string | undefined>();
  const [resuming, setResuming] = useState(false);
  const [resumeError, setResumeError] = useState<string | undefined>();
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState<string | undefined>();
  const [cancelRequested, setCancelRequested] = useState(false);

  // While a run is live, keep the page fresh: refetch when the
  // activity stream reports an event for this task, with a slow
  // watchdog poll only if the stream itself goes silent.
  const workflowStatus = detail.data?.workflow?.status;
  const reloadAll = () => {
    detail.reload();
    reviews.reload();
  };
  useRunLiveRefetch(
    detail.data?.workflow?.taskId,
    workflowStatus === 'RUNNING' ||
      workflowStatus === 'WAITING_RETRY' ||
      workflowStatus === 'AI_REVIEWING' ||
      workflowStatus === 'ESCALATED',
    reloadAll,
  );

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

  const cancel = async () => {
    setCancelError(undefined);
    setCancelling(true);
    try {
      const updated = await cancelWorkflow(workflowId);
      // A run mid-step cannot stop instantly: the backend records the
      // request and the run flips to Cancelled when the step returns.
      if (updated.status !== 'CANCELLED') {setCancelRequested(true);}
      detail.reload();
    } catch (err) {
      setCancelError(err instanceof Error ? err.message : 'Failed to cancel the run');
    } finally {
      setCancelling(false);
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
              actions={<><WorkflowStatusBadge status={workflow.status} /><RunLabel workflow={workflow} /><Link className="btn" to={`/tasks/${workflow.taskId}`}>Open task</Link></>}
            />
            <WorkflowErrorBanner workflow={workflow} />
            <EscalatedPanel
              workflow={workflow}
              onChanged={detail.reload}
              onCancel={cancel}
              cancelBusy={cancelling}
            />
            {['CANCELLED', 'COMPLETED'].includes(workflow.status) && (
              <Card>
                <div className="filters">
                  <button type="button" className="btn btn-primary" onClick={runAgain} disabled={retrying}>
                    {retrying ? 'Starting…' : 'Run again'}
                  </button>
                  <span className="muted small">
                    Starts a fresh run of this task with its original requirement; this finished run stays as the record.
                  </span>
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
                  <Link to="/approvals">Approvals page</Link> — once decided, the run continues
                  on its own to the next step.
                </p>
              </Card>
            )}
            <RunLiveActivity workflow={workflow} />
            <WorkspaceInfo workflow={workflow} />
            {cancelRequested && (
              <Card>
                <p className="muted">
                  Cancellation requested — the run stops as soon as its current step
                  finishes and then shows as Cancelled. A step already calling the
                  model cannot be interrupted mid-call.
                </p>
              </Card>
            )}
            {cancelError && (
              <p className="alert" role="alert">
                {cancelError}
              </p>
            )}
            {(resumeError || retryError) && workflow.status === 'FAILED' && (
              <p className="alert" role="alert">
                {resumeError ?? retryError}
              </p>
            )}
            <OperatorControls
              workflow={workflow}
              onChanged={detail.reload}
              onResumeFailed={resume}
              onRunAgain={runAgain}
              resumeBusy={resuming}
              runAgainBusy={retrying}
              onCancel={cancel}
              cancelBusy={cancelling}
            />
            <div className="grid two-col">
              <Card title="Steps"><WorkflowStepper steps={workflow.steps} /></Card>
              <Card title="Execution history"><ActivityFeed events={events} showTask={false} /></Card>
            </div>
            <WorkflowDiagnostics runId={workflow.id} />
            {reviews.data && reviews.data.stages.length > 0 && (
              <Card title="AI review rounds">
                <ReviewTimeline reviews={reviews.data} />
              </Card>
            )}
            <WorkflowArtifacts artifacts={workflow.artifacts} />
          </>
        )
      }
    </AsyncView>
  );
}

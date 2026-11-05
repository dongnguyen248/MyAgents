import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ActivityFeed } from '../../components/activity/ActivityFeed';
import { AsyncView } from '../../components/common/AsyncView';
import { CiBadge } from '../../components/common/Badge';
import { Card, PageHeader, Stat } from '../../components/common/Layout';
import { TaskStatusBadge } from '../../components/tasks/TaskStatusBadge';
import { WorkflowArtifacts } from '../../components/workflows/WorkflowArtifacts';
import { WorkflowErrorBanner } from '../../components/workflows/WorkflowErrorBanner';
import { WorkflowStatusBadge } from '../../components/workflows/WorkflowStatusBadge';
import { WorkflowStepper } from '../../components/workflows/WorkflowStepper';
import { useAgents } from '../../features/agent-management';
import { useTaskDetail } from '../../features/task-monitoring';
import { cancelWorkflow, resumeWorkflow, retryWorkflow } from '../../features/workflow-monitoring';
import { dateTime, duration, titleCase } from '../../utils/format';

export function TaskDetailPage() {
  const { taskId = '' } = useParams();
  const detail = useTaskDetail(taskId);
  const agents = useAgents();
  const [retrying, setRetrying] = useState(false);
  const [resuming, setResuming] = useState(false);
  const [retryError, setRetryError] = useState<string | undefined>();
  const [cancelling, setCancelling] = useState(false);
  const [confirmingCancel, setConfirmingCancel] = useState(false);
  const [cancelRequested, setCancelRequested] = useState(false);
  const [cancelError, setCancelError] = useState<string | undefined>();

  const runAgain = async (runId: string) => {
    setRetryError(undefined);
    setRetrying(true);
    try {
      await retryWorkflow(runId);
      detail.reload();
    } catch (err) {
      setRetryError(err instanceof Error ? err.message : 'Failed to run again');
    } finally {
      setRetrying(false);
    }
  };

  const resume = async (runId: string) => {
    setRetryError(undefined);
    setResuming(true);
    try {
      await resumeWorkflow(runId);
      detail.reload();
    } catch (err) {
      setRetryError(err instanceof Error ? err.message : 'Failed to resume');
    } finally {
      setResuming(false);
    }
  };
  const cancel = async (runId: string) => {
    setCancelError(undefined);
    setCancelling(true);
    try {
      const updated = await cancelWorkflow(runId);
      setConfirmingCancel(false);
      if (updated.status !== 'CANCELLED') setCancelRequested(true);
      detail.reload();
    } catch (err) {
      setCancelError(err instanceof Error ? err.message : 'Failed to cancel the run');
    } finally {
      setCancelling(false);
    }
  };
  return (
    <AsyncView {...detail}>
      {({ task, workflow, events, runs }) =>
        !task ? (
          <p className="muted">Task not found.</p>
        ) : (
          <>
            <PageHeader title={`${task.id} · ${task.title}`} back={{ to: '/tasks', label: 'Tasks' }} actions={<>
              {workflow && workflow.status === 'FAILED' && (
                <button type="button" className="btn btn-primary" onClick={() => resume(workflow.id)} disabled={resuming || retrying}>
                  {resuming ? 'Resuming…' : 'Resume'}
                </button>
              )}
              {workflow && ['FAILED', 'CANCELLED', 'COMPLETED'].includes(workflow.status) && (
                <button type="button" className={workflow.status === 'FAILED' ? 'btn' : 'btn btn-primary'} onClick={() => runAgain(workflow.id)} disabled={retrying || resuming}>
                  {retrying ? 'Starting…' : 'Run again'}
                </button>
              )}
              {workflow && !['FAILED', 'CANCELLED', 'COMPLETED'].includes(workflow.status) && (
                <button type="button" className="btn btn-danger" onClick={() => setConfirmingCancel(true)} disabled={cancelling}>
                  Cancel run
                </button>
              )}
              <TaskStatusBadge status={task.status} />
            </>} />
            {retryError && (
              <p className="alert" role="alert">
                {retryError}
              </p>
            )}
            {workflow && confirmingCancel && (
              <Card>
                <div className="filters">
                  <span className="muted small">
                    Cancel this run? It cannot be resumed afterwards — you can Run again
                    from scratch, and this run stays as the record. A step already in
                    progress finishes first.
                  </span>
                  <button type="button" className="btn btn-danger" onClick={() => cancel(workflow.id)} disabled={cancelling}>
                    {cancelling ? 'Cancelling…' : 'Yes, cancel run'}
                  </button>
                  <button type="button" className="btn" onClick={() => setConfirmingCancel(false)} disabled={cancelling}>
                    Keep running
                  </button>
                </div>
                {cancelError && (
                  <p className="alert" role="alert">
                    {cancelError}
                  </p>
                )}
              </Card>
            )}
            {workflow && cancelRequested && !confirmingCancel && (
              <Card>
                <p className="muted">
                  Cancellation requested — the run stops as soon as its current step
                  finishes and then shows as Cancelled. A step already calling the model
                  cannot be interrupted mid-call.
                </p>
              </Card>
            )}
            {workflow && <WorkflowErrorBanner workflow={workflow} />}
            <div className="grid two-col">
              <Card title="Workflow timeline">{workflow ? <WorkflowStepper steps={workflow.steps} /> : <p className="muted">No workflow.</p>}</Card>
              <div className="stack">
                <Card title="Details">
                  <dl className="stats stats-2">
                    <Stat label="Project" value={task.projectId.toUpperCase()} />
                    <Stat label="Workflow" value={titleCase(task.workflowType)} />
                    <Stat label="Priority" value={titleCase(task.priority)} />
                    <Stat label="Assigned agent" value={task.assignedAgentId ? <Link to={`/agents/${task.assignedAgentId}`}>{agents.data?.find((a) => a.id === task.assignedAgentId)?.name ?? task.assignedAgentId}</Link> : '–'} />
                    <Stat label="Revisions" value={task.revisions} />
                    <Stat label="Created" value={dateTime(task.createdAt)} />
                    <Stat label="Duration" value={task.durationSec ? duration(task.durationSec) : 'In progress'} />
                  </dl>
                </Card>
                <Card title="GitLab / CI">
                  <p>Merge request: {task.mergeRequest ?? <span className="muted">none yet</span>}</p>
                  <p><CiBadge status={task.ci} /></p>
                </Card>
              </div>
            </div>
            <WorkflowArtifacts artifacts={workflow?.artifacts} />
            {runs && runs.length > 1 && (
              <Card title="Run history">
                <div className="stack">
                  {runs.map((run, index) => (
                    <p key={run.id}>
                      <WorkflowStatusBadge status={run.status} />{' '}
                      <Link to={`/workflows/${run.id}`}>Run · {dateTime(run.startedAt)}</Link>
                      {index === 0 && <span className="muted small"> (latest — shown above)</span>}
                    </p>
                  ))}
                </div>
              </Card>
            )}
            <Card title="Execution history"><ActivityFeed events={events} showTask={false} /></Card>
          </>
        )
      }
    </AsyncView>
  );
}

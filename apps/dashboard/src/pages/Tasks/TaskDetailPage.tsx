import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ActivityFeed } from '../../components/activity/ActivityFeed';
import { AsyncView } from '../../components/common/AsyncView';
import { CiBadge } from '../../components/common/Badge';
import { Card, PageHeader, Stat } from '../../components/common/Layout';
import { TaskStatusBadge } from '../../components/tasks/TaskStatusBadge';
import { WorkflowArtifacts } from '../../components/workflows/WorkflowArtifacts';
import { WorkflowStepper } from '../../components/workflows/WorkflowStepper';
import { useAgents } from '../../features/agent-management';
import { useTaskDetail } from '../../features/task-monitoring';
import { retryWorkflow } from '../../features/workflow-monitoring';
import { dateTime, duration, titleCase } from '../../utils/format';

export function TaskDetailPage() {
  const { taskId = '' } = useParams();
  const detail = useTaskDetail(taskId);
  const agents = useAgents();
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState<string | undefined>();

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
  return (
    <AsyncView {...detail}>
      {({ task, workflow, events }) =>
        !task ? (
          <p className="muted">Task not found.</p>
        ) : (
          <>
            <PageHeader title={`${task.id} · ${task.title}`} back={{ to: '/tasks', label: 'Tasks' }} actions={<>
              {workflow && ['FAILED', 'CANCELLED', 'COMPLETED'].includes(workflow.status) && (
                <button type="button" className="btn btn-primary" onClick={() => runAgain(workflow.id)} disabled={retrying}>
                  {retrying ? 'Starting…' : 'Run again'}
                </button>
              )}
              <TaskStatusBadge status={task.status} />
            </>} />
            {retryError && (
              <p className="alert" role="alert">
                {retryError}
              </p>
            )}
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
            <Card title="Execution history"><ActivityFeed events={events} showTask={false} /></Card>
          </>
        )
      }
    </AsyncView>
  );
}

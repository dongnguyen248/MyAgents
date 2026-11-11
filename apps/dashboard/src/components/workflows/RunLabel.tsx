import { runLabelText } from '../../lib/currentRun';
import type { Workflow } from '../../types/workflow';
import { dateTime } from '../../utils/format';

interface Props {
  workflow: Workflow;
  /** Runs of the same task older than the displayed one, when known. */
  earlierRuns?: number;
}

/**
 * Names the exact run a page is showing, next to its status, so a
 * header, a stepper and a banner can never be read as belonging to
 * different runs of the same task.
 */
export function RunLabel({ workflow, earlierRuns }: Props) {
  const text = runLabelText(workflow, dateTime(workflow.startedAt), earlierRuns);
  return <span className="muted small">{text}</span>;
}

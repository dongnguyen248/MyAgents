import type { Agent } from '../../types/agent';
import type { Project } from '../../types/project';
import type { TaskFilter, TaskPriority, TaskStatus, WorkflowType } from '../../types/task';
import { titleCase } from '../../utils/format';

export const ALL_STATUSES: TaskStatus[] = [
  'NEW', 'SPEC_DRAFT', 'SPEC_REVIEW', 'SPEC_REJECTED', 'SPEC_APPROVED', 'PLAN_DRAFT', 'PLAN_REVIEW', 'PLAN_REJECTED', 'PLAN_APPROVED',
  'TASK_DRAFT', 'TASK_REVIEW', 'TASK_REJECTED', 'TASK_APPROVED', 'IMPLEMENTING', 'CODE_REVIEW', 'TESTING', 'CI', 'READY_TO_MERGE',
  'COMPLETED', 'FAILED', 'CANCELLED',
];
const WORKFLOWS: WorkflowType[] = ['feature-development', 'bug-fix', 'refactoring'];
const PRIORITIES: TaskPriority[] = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'];

function Select({ label, value, onChange, options }: { label: string; value: string; onChange: (v: string) => void; options: [string, string][] }) {
  return (
    <label className="field">
      <span>{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">All</option>
        {options.map(([v, l]) => (
          <option key={v} value={v}>{l}</option>
        ))}
      </select>
    </label>
  );
}

interface Props {
  filter: TaskFilter;
  onChange: (f: TaskFilter) => void;
  projects: Project[];
  agents: Agent[];
}

export function TaskFilters({ filter, onChange, projects, agents }: Props) {
  const set = (patch: Partial<TaskFilter>) => onChange({ ...filter, ...patch });
  return (
    <div className="filters" role="search" aria-label="Task filters">
      <Select label="Project" value={filter.projectId ?? ''} onChange={(v) => set({ projectId: v || undefined })} options={projects.map((p) => [p.id, p.name])} />
      <Select label="Agent" value={filter.agentId ?? ''} onChange={(v) => set({ agentId: v || undefined })} options={agents.map((a) => [a.id, a.name])} />
      <Select label="Status" value={filter.status ?? ''} onChange={(v) => set({ status: (v || undefined) as TaskStatus | undefined })} options={ALL_STATUSES.map((s) => [s, titleCase(s)])} />
      <Select label="Workflow" value={filter.workflowType ?? ''} onChange={(v) => set({ workflowType: (v || undefined) as WorkflowType | undefined })} options={WORKFLOWS.map((w) => [w, titleCase(w)])} />
      <Select label="Priority" value={filter.priority ?? ''} onChange={(v) => set({ priority: (v || undefined) as TaskPriority | undefined })} options={PRIORITIES.map((p) => [p, titleCase(p)])} />
      <Select label="Created" value={filter.sinceHours ? String(filter.sinceHours) : ''} onChange={(v) => set({ sinceHours: v ? Number(v) : undefined })} options={[['24', 'Last 24 hours'], ['168', 'Last 7 days']]} />
      <button type="button" className="btn" onClick={() => onChange({})}>Clear</button>
    </div>
  );
}

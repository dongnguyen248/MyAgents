import { useState } from 'react';
import { Icon } from '../components/common/Icon';
import { useProjectScope } from '../features/project-scope';
import { useProjects } from '../features/project-management';
import type { Project } from '../types/project';

interface MenuProps {
  projects: Project[];
  projectId: string | null;
  onChoose: (id: string | null) => void;
  onClose: () => void;
}

function ScopeButton({
  name,
  sub,
  open,
  onToggle,
}: {
  name: string;
  sub: string;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      className="scope"
      aria-expanded={open}
      aria-haspopup="listbox"
      onClick={onToggle}
    >
      <span className="scope-mark" aria-hidden="true">
        <Icon name="layers" className="icon-sm" />
      </span>
      <span className="scope-text">
        <span className="scope-name">{name}</span>
        <span className="scope-sub">{sub}</span>
      </span>
      <Icon name="chevrons" className="icon-sm scope-chevron" />
    </button>
  );
}

function ScopeMenu({ projects, projectId, onChoose, onClose }: MenuProps) {
  return (
    <>
      <button type="button" className="scrim" aria-label="Close project scope" onClick={onClose} />
      <div className="popover" role="listbox" aria-label="Project scope">
        <div className="popover-label">Scope</div>
        <ScopeOption
          label="All projects"
          selected={projectId === null}
          onSelect={() => onChoose(null)}
        />
        <div className="popover-sep" />
        {projects.map((project) => (
          <ScopeOption
            key={project.id}
            label={project.name}
            selected={project.id === projectId}
            onSelect={() => onChoose(project.id)}
          />
        ))}
        {projects.length === 0 && <p className="popover-label">No projects registered yet</p>}
      </div>
    </>
  );
}

function ScopeOption({
  label,
  selected,
  onSelect,
}: {
  label: string;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      className="popover-item"
      role="option"
      aria-selected={selected}
      onClick={onSelect}
    >
      <Icon name="folder" className="icon-sm" />
      <span>{label}</span>
      {selected && <Icon name="check" className="icon-sm check" />}
    </button>
  );
}

/**
 * The scope selector under the brand: "All projects" by default, one project
 * when the operator narrows the view. Pages that filter by project (Tasks,
 * Activity) read the same value, so the sidebar never lies about what is on
 * screen.
 */
export function ScopeSwitcher() {
  const { projectId, setProjectId } = useProjectScope();
  const projects = useProjects();
  const [open, setOpen] = useState(false);
  const list = projects.data ?? [];
  const active = list.find((item) => item.id === projectId);
  const onChoose = (id: string | null) => {
    setProjectId(id);
    setOpen(false);
  };

  return (
    <div className="scope-wrap">
      <ScopeButton
        name={active ? active.name : 'All projects'}
        sub={active ? 'Project scope' : 'Every run in view'}
        open={open}
        onToggle={() => setOpen((previous) => !previous)}
      />
      {open && (
        <ScopeMenu
          projects={list}
          projectId={projectId}
          onChoose={onChoose}
          onClose={() => setOpen(false)}
        />
      )}
    </div>
  );
}

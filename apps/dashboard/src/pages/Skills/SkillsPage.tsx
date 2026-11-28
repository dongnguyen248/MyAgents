import { useEffect, useState } from 'react';
import { AsyncView } from '../../components/common/AsyncView';
import { PageHeader } from '../../components/common/Layout';
import { SkillFileEditor } from '../../components/skills/SkillFileEditor';
import { SkillOverview } from '../../components/skills/SkillOverview';
import { SkillTree } from '../../components/skills/SkillTree';
import { useProjects } from '../../features/project-management';
import { useSkills } from '../../features/skill-catalogue';
import { backendBaseUrl } from '../../services/api';
import type { Skill } from '../../types/skill';
import type { Project } from '../../types/project';

function useSelection() {
  const [selection, setSelection] = useState<{ id: string; path?: string }>();
  const [dirty, setDirty] = useState(false);
  useEffect(() => {
    function warn(event: BeforeUnloadEvent) {
      if (dirty) {
        event.preventDefault();
      }
    }
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
  function select(id: string, path?: string) {
    if (dirty && !window.confirm('Discard unsaved changes?')) {
      return;
    }
    setDirty(false);
    setSelection({ id, path });
  }
  return { selection, select, setDirty };
}

type Browser = ReturnType<typeof useSelection>;
type WorkspaceProps = { data: Skill[]; projects?: Project[]; browser: Browser; reload: () => void };
function WorkspaceContent({ data, projects, browser, reload }: WorkspaceProps) {
  const { selection, setDirty } = browser;
  if (selection?.path) {
    return (
      <SkillFileEditor
        key={`${selection.id}/${selection.path}`}
        id={selection.id}
        path={selection.path}
        onDirty={setDirty}
        onSaved={reload}
      />
    );
  }
  return (
    <SkillOverview
      skills={data}
      projects={projects}
      selected={data.find((skill) => skill.id === selection?.id)}
    />
  );
}

function SkillWorkspace({ data, projects, browser, reload }: WorkspaceProps) {
  const { selection, select } = browser;
  return (
    <div className="skill-workspace">
      <SkillTree
        skills={data}
        selectedId={selection?.id}
        selectedFile={selection?.path}
        onSelect={select}
      />
      <main className="skill-content">
        <WorkspaceContent data={data} projects={projects} browser={browser} reload={reload} />
      </main>
    </div>
  );
}

function SkillNotices({ error }: { error?: Error }) {
  return (
    <>
      {!backendBaseUrl && (
        <p className="alert">
          Demo data only. Connect the API backend to browse and edit the real skills/ folder.
        </p>
      )}
      {error && (
        <p className="alert" role="alert">
          Could not load project settings: {error.message}
        </p>
      )}
    </>
  );
}

export function SkillsPage() {
  const skills = useSkills();
  const projects = useProjects();
  const browser = useSelection();
  return (
    <>
      <PageHeader
        title="Skills"
        subtitle="Manage the skill library and explore its files."
        actions={
          <button type="button" className="btn btn-ghost" onClick={skills.reload}>
            ↻ Refresh
          </button>
        }
      />
      <SkillNotices error={projects.error} />
      <AsyncView {...skills}>
        {(data) => (
          <SkillWorkspace
            data={data}
            projects={projects.data}
            browser={browser}
            reload={skills.reload}
          />
        )}
      </AsyncView>
    </>
  );
}

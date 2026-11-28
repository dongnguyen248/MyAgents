import { useState } from 'react';
import type { Skill } from '../../types/skill';

interface Node {
  name: string;
  path: string;
  children: Node[];
  directory: boolean;
}

function fileTree(paths: string[]): Node[] {
  const root: Node[] = [];
  for (const path of paths) {
    const parts = path.replace(/\/$/, '').split('/');
    let children = root;
    parts.forEach((part, index) => {
      let node = children.find((item) => item.name === part);
      if (!node) {
        node = {
          name: part,
          path: parts.slice(0, index + 1).join('/'),
          children: [],
          directory: path.endsWith('/') || index < parts.length - 1,
        };
        children.push(node);
      }
      children = node.children;
    });
  }
  return root;
}

type TreeProps = { nodes: Node[]; selected?: string; onSelect: (path: string) => void };

function TreeNode({
  node,
  selected,
  onSelect,
}: {
  node: Node;
  selected?: string;
  onSelect: (path: string) => void;
}) {
  if (node.directory) {
    return (
      <details open>
        <summary>▾ &nbsp;📁 {node.name}</summary>
        <TreeNodes nodes={node.children} selected={selected} onSelect={onSelect} />
      </details>
    );
  }
  return (
    <button
      type="button"
      className={`skill-tree-file ${selected === node.path ? 'selected' : ''}`}
      onClick={() => onSelect(node.path)}
    >
      ▤ &nbsp;{node.name}
    </button>
  );
}

function TreeNodes({ nodes, selected, onSelect }: TreeProps) {
  const sorted = [...nodes].sort(
    (a, b) => Number(b.directory) - Number(a.directory) || a.name.localeCompare(b.name),
  );
  return (
    <ul className="skill-tree-nested">
      {sorted.map((node) => (
        <li key={node.path}>
          <TreeNode node={node} selected={selected} onSelect={onSelect} />
        </li>
      ))}
    </ul>
  );
}

type Props = {
  skills: Skill[];
  selectedId?: string;
  selectedFile?: string;
  onSelect: (id: string, path?: string) => void;
};

function SkillRoot({
  skill,
  selected,
  expanded,
  onClick,
}: {
  skill: Skill;
  selected: boolean;
  expanded: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={`skill-tree-root ${selected ? 'selected' : ''}`}
      onClick={onClick}
    >
      <span>{expanded ? '⌄' : '›'}</span>
      <span>📁</span>
      <strong>{skill.id}</strong>
    </button>
  );
}

function SkillTreeEntry({
  skill,
  selectedId,
  selectedFile,
  onSelect,
}: Omit<Props, 'skills'> & { skill: Skill }) {
  const [expanded, setExpanded] = useState(false);
  function selectSkill() {
    onSelect(skill.id);
    setExpanded(!expanded);
  }
  return (
    <div>
      <SkillRoot
        skill={skill}
        selected={selectedId === skill.id && !selectedFile}
        expanded={expanded}
        onClick={selectSkill}
      />
      {expanded && (
        <TreeNodes
          nodes={fileTree(skill.files ?? [])}
          selected={selectedId === skill.id ? selectedFile : undefined}
          onSelect={(path) => onSelect(skill.id, path)}
        />
      )}
    </div>
  );
}

export function SkillTree({ skills, ...selection }: Props) {
  return (
    <nav className="skill-explorer" aria-label="Skill files">
      <div className="skill-explorer-head">
        <strong>Library</strong>
        <span>{skills.length} skills</span>
      </div>
      {skills.length === 0 && <p className="note skill-empty">No skills found in skills/.</p>}
      {skills.map((skill) => (
        <SkillTreeEntry key={skill.id} skill={skill} {...selection} />
      ))}
    </nav>
  );
}

// The skill catalogue's filter is what tells an operator which skills a project
// actually runs with, so it is tested apart from the page.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { projectsEnabling, skillsForProject } from '../src/lib/skillFilter.ts';
import type { Project } from '../src/types/project.ts';
import type { Skill } from '../src/types/skill.ts';

const skill = (id: string): Skill => ({
  id,
  name: id,
  description: `${id} description`,
  appliesTo: ['implement'],
  stackOnly: false,
  path: `skills/${id}/SKILL.md`,
});

const project = (id: string, enabledSkills: string[]): Project =>
  ({ id, name: id.toUpperCase(), enabledSkills }) as Project;

const catalogue = [skill('git'), skill('testing'), skill('python')];
const vhpc = project('vhpc', ['testing', 'python']);
const erp = project('erp', ['git']);

test('no project chosen means the whole catalogue', () => {
  assert.deepEqual(
    skillsForProject(catalogue).map((entry) => entry.id),
    ['git', 'testing', 'python'],
  );
});

test('a chosen project narrows the catalogue to its enabled skills', () => {
  assert.deepEqual(
    skillsForProject(catalogue, vhpc).map((entry) => entry.id),
    ['testing', 'python'],
  );
  assert.deepEqual(
    skillsForProject(catalogue, project('empty', [])).map((entry) => entry.id),
    [],
  );
});

test('projectsEnabling finds every project that turns a skill on', () => {
  assert.deepEqual(
    projectsEnabling(skill('testing'), [vhpc, erp]).map((entry) => entry.id),
    ['vhpc'],
  );
  assert.deepEqual(projectsEnabling(skill('python'), [erp]), []);
});

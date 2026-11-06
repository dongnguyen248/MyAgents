import type { Project } from '../types/project';

const rate = (c: number, f: number) => c / (c + f);

export const projects: Project[] = [
  {
    id: 'vhpc', name: 'VHPC', repositoryProvider: 'GitLab', repositoryUrl: '', repositoryPath: '', workspaceMode: 'auto', keepChangesOnFailure: false, testCommands: [], technologies: ['java', 'spring', 'react'],
    description: '', workflow: 'software-development', enabledSkills: ['java', 'spring', 'react', 'git', 'testing', 'security'],
    technologyGroups: { backend: ['java', 'spring'], frontend: ['react'] }, approvalChannel: 'teams',
    agentIds: ['spec-agent', 'plan-agent', 'task-agent', 'implement-agent', 'review-agent', 'test-agent', 'fix-agent'],
    ci: 'PASS', ciFailures24h: 0,
    metrics: { activeAgents: 7, running: 4, completed: 128, failed: 11, successRate: rate(128, 11), pendingApprovals: 1 },
  },
  {
    id: 'vnpc', name: 'VNPC', repositoryProvider: 'GitLab', repositoryUrl: '', repositoryPath: '', workspaceMode: 'auto', keepChangesOnFailure: false, testCommands: [], technologies: ['java', 'spring'],
    description: '', workflow: 'software-development', enabledSkills: ['git', 'testing', 'security'],
    technologyGroups: { backend: ['java', 'spring'], frontend: [] }, approvalChannel: 'teams',
    agentIds: ['spec-agent', 'plan-agent', 'task-agent', 'implement-agent', 'review-agent'],
    ci: 'RUNNING', ciFailures24h: 1,
    metrics: { activeAgents: 5, running: 5, completed: 84, failed: 9, successRate: rate(84, 9), pendingApprovals: 3 },
  },
  {
    id: 'erp', name: 'ERP', repositoryProvider: 'GitLab', repositoryUrl: '', repositoryPath: '', workspaceMode: 'auto', keepChangesOnFailure: false, testCommands: [], technologies: ['python', 'database'],
    description: '', workflow: 'software-development', enabledSkills: ['python', 'git', 'testing'],
    technologyGroups: { backend: ['python', 'database'], frontend: [] }, approvalChannel: '',
    agentIds: ['task-agent', 'implement-agent', 'test-agent', 'fix-agent'],
    ci: 'FAIL', ciFailures24h: 1,
    metrics: { activeAgents: 4, running: 3, completed: 61, failed: 7, successRate: rate(61, 7), pendingApprovals: 1 },
  },
];

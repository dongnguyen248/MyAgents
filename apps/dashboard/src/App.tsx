import { Navigate, Route, Routes } from 'react-router-dom';
import { DashboardLayout } from './layouts/DashboardLayout';
import { ActivityPage } from './pages/Activity/ActivityPage';
import { AgentDetailPage } from './pages/Agents/AgentDetailPage';
import { AgentSettingsPage } from './pages/Agents/AgentSettingsPage';
import { AgentsPage } from './pages/Agents/AgentsPage';
import { ApprovalsPage } from './pages/Approvals/ApprovalsPage';
import { DashboardPage } from './pages/Dashboard/DashboardPage';
import { LiveMapPage } from './pages/LiveMap/LiveMapPage';
import { MetricsPage } from './pages/Metrics/MetricsPage';
import { ProjectsPage } from './pages/Projects/ProjectsPage';
import { LlmPage } from './pages/Llm/LlmPage';
import { TaskDetailPage } from './pages/Tasks/TaskDetailPage';
import { TasksPage } from './pages/Tasks/TasksPage';
import { WorkflowDetailPage } from './pages/Workflows/WorkflowDetailPage';
import { WorkflowsPage } from './pages/Workflows/WorkflowsPage';

export default function App() {
  return (
    <Routes>
      <Route element={<DashboardLayout />}>
        <Route index element={<DashboardPage />} />
        <Route path="agents" element={<AgentsPage />} />
        <Route path="agents/:agentId" element={<AgentDetailPage />} />
        <Route path="agents/:agentId/settings" element={<AgentSettingsPage />} />
        <Route path="agent-settings" element={<Navigate to="/agents" replace />} />
        <Route path="tasks" element={<TasksPage />} />
        <Route path="tasks/:taskId" element={<TaskDetailPage />} />
        <Route path="workflows" element={<WorkflowsPage />} />
        <Route path="live-map" element={<LiveMapPage />} />
        <Route path="workflows/:workflowId" element={<WorkflowDetailPage />} />
        <Route path="approvals" element={<ApprovalsPage />} />
        <Route path="activity" element={<ActivityPage />} />
        <Route path="projects" element={<ProjectsPage />} />
        <Route path="metrics" element={<MetricsPage />} />
        <Route path="llm" element={<LlmPage />} />
        <Route path="settings" element={<Navigate to="/llm" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

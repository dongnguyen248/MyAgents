import { NavLink, Outlet } from 'react-router-dom';
import { ThemeToggle } from '../components/common/ThemeToggle';
import { backendBaseUrl } from '../services/api';

const GROUPS: { title?: string; links: [string, string][] }[] = [
  { links: [['/', 'Dashboard']] },
  { title: 'Workspace', links: [['/agents', 'Agents'], ['/tasks', 'Tasks'], ['/workflows', 'Workflows'], ['/approvals', 'Approvals'], ['/activity', 'Activity']] },
  { title: 'Projects', links: [['/projects', 'Projects']] },
  { title: 'Analytics', links: [['/metrics', 'Metrics']] },
  { title: 'System', links: [['/agent-settings', 'Agent Settings'], ['/settings', 'Settings']] },
];

export function DashboardLayout() {
  return (
    <div className="app">
      <a href="#main" className="skip-link">Skip to content</a>
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">◈</span>
          <div>
            <strong>AI Software Factory</strong>
            <div className="brand-sub">Control Tower</div>
          </div>
        </div>
        <nav aria-label="Main">
          {GROUPS.map((g, i) => (
            <div className="nav-group" key={i}>
              {g.title && <div className="nav-title">{g.title}</div>}
              {g.links.map(([to, label]) => (
                <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}>
                  {label}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-foot">
          <ThemeToggle />
          <div className="brand-sub">
            {backendBaseUrl ? `Backend · ${backendBaseUrl}` : 'Mock data · no backend connected'}
          </div>
        </div>
      </aside>
      <main id="main" className="main">
        <Outlet />
      </main>
    </div>
  );
}

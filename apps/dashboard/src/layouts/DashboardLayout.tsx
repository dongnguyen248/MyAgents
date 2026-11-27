import { useEffect, useState } from 'react';
import { Link, Outlet } from 'react-router-dom';
import { CommandPalette } from '../components/common/CommandPalette';
import { Icon } from '../components/common/Icon';
import { ProjectScopeProvider } from '../features/project-scope';
import { backendBaseUrl } from '../services/api';
import { ScopeSwitcher } from './ScopeSwitcher';
import { SidebarNav } from './SidebarNav';
import { TopBar } from './TopBar';

/**
 * App shell: brand + project scope + grouped nav in the sidebar, a sticky top
 * bar, and the routed page in the content column. Below 900px the sidebar
 * becomes an off-canvas panel opened from the top bar.
 */
export function DashboardLayout() {
  const [navOpen, setNavOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setSearchOpen(true);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return (
    <ProjectScopeProvider>
      <div className={navOpen ? 'app nav-open' : 'app'}>
        <a href="#main" className="skip-link">
          Skip to content
        </a>
        <aside className="sidebar" aria-label="Sidebar">
          <div className="sidebar-head">
            <Link to="/" className="brand" onClick={() => setNavOpen(false)}>
              <span className="brand-mark" aria-hidden="true">
                <Icon name="bot" className="icon-sm" />
              </span>
              <span className="brand-text">
                <span className="brand-name">AI Software Agents</span>
                <span className="brand-sub">Control Tower</span>
              </span>
            </Link>
            <ScopeSwitcher />
          </div>
          <SidebarNav onNavigate={() => setNavOpen(false)} />
          <div className="sidebar-foot">
            <div className="sidebar-user">
              <span className="avatar" aria-hidden="true">
                OP
              </span>
              <span className="scope-text">
                <span className="scope-name">Operator</span>
                <span className="scope-sub">
                  {backendBaseUrl ? 'Connected backend' : 'Mock data'}
                </span>
              </span>
            </div>
          </div>
        </aside>
        <button
          type="button"
          className="nav-backdrop"
          aria-label="Close navigation"
          onClick={() => setNavOpen(false)}
        />
        <div className="shell">
          <TopBar onOpenNav={() => setNavOpen(true)} onOpenSearch={() => setSearchOpen(true)} />
          <main id="main" className="main">
            <Outlet />
          </main>
        </div>
        <CommandPalette open={searchOpen} onClose={() => setSearchOpen(false)} />
      </div>
    </ProjectScopeProvider>
  );
}

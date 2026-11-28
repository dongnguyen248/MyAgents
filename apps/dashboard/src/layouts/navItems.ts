import type { IconName } from '../components/common/Icon';

export interface NavItem {
  to: string;
  label: string;
  icon: IconName;
  /** Exact match only (the dashboard route shares the '/' prefix with everything). */
  end?: boolean;
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

/**
 * Sidebar information architecture: what the platform *does* (Functions) and
 * what it is configured with (System). Flat links only — the sidebar never
 * hides a destination behind a submenu, so every page stays one click away.
 */
export const NAV_GROUPS: NavGroup[] = [
  {
    label: 'Functions',
    items: [
      { to: '/', label: 'Dashboard', icon: 'dashboard', end: true },
      { to: '/tasks', label: 'Tasks', icon: 'target' },
      { to: '/workflows', label: 'Workflows', icon: 'git-branch' },
      { to: '/live-map', label: 'Live Map', icon: 'map' },
      { to: '/approvals', label: 'Approvals', icon: 'clipboard' },
      { to: '/activity', label: 'Activity', icon: 'activity' },
      { to: '/projects', label: 'Projects', icon: 'folder' },
      { to: '/metrics', label: 'Metrics', icon: 'chart' },
    ],
  },
  {
    label: 'System',
    items: [
      { to: '/agents', label: 'Agents', icon: 'bot' },
      { to: '/skills', label: 'Skills', icon: 'book' },
      { to: '/rules', label: 'Rules', icon: 'clipboard' },
      { to: '/llm', label: 'LLM', icon: 'sparkles' },
    ],
  },
];

/** Every nav destination, for the command palette. */
export const NAV_ITEMS: NavItem[] = NAV_GROUPS.flatMap((group) => group.items);

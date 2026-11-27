import { Icon } from '../components/common/Icon';
import { ThemeToggle } from '../components/common/ThemeToggle';
import { backendBaseUrl } from '../services/api';

function TopBarSearch({ onOpen }: { onOpen: () => void }) {
  return (
    <button type="button" className="search-btn" onClick={onOpen}>
      <Icon name="search" className="icon-sm" />
      <span className="search-label">Search pages and agents</span>
      <kbd className="kbd">⌘K</kbd>
    </button>
  );
}

function TopBarIdentity() {
  return (
    <>
      <span className="topbar-meta">
        {backendBaseUrl ? `Backend · ${backendBaseUrl}` : 'Mock data'}
      </span>
      <span className="divider-v" aria-hidden="true" />
      <ThemeToggle compact />
      <span className="avatar" aria-hidden="true" title="Local operator">
        OP
      </span>
    </>
  );
}

/** Sticky app bar: navigation toggle, quick search, data source, theme, identity. */
export function TopBar({
  onOpenNav,
  onOpenSearch,
}: {
  onOpenNav: () => void;
  onOpenSearch: () => void;
}) {
  return (
    <header className="topbar">
      <button
        type="button"
        className="icon-btn nav-toggle"
        onClick={onOpenNav}
        aria-label="Toggle navigation"
      >
        <Icon name="panel-left" />
      </button>
      <span className="divider-v nav-toggle" aria-hidden="true" />
      <TopBarSearch onOpen={onOpenSearch} />
      <span className="topbar-spacer" />
      <TopBarIdentity />
    </header>
  );
}

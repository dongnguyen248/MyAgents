import { useState } from 'react';
import { Icon } from './Icon';

interface ToggleProps {
  theme: string;
  onToggle: () => void;
}

/** Icon form, used in the top bar. */
function IconToggle({ theme, onToggle }: ToggleProps) {
  const label = theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode';
  return (
    <button
      type="button"
      className="icon-btn"
      onClick={onToggle}
      aria-pressed={theme === 'dark'}
      aria-label={label}
      title={label}
    >
      <Icon name={theme === 'dark' ? 'sun' : 'moon'} />
    </button>
  );
}

/** Light/dark switch. `compact` renders the icon form used in the top bar. */
export function ThemeToggle({ compact = false }: { compact?: boolean }) {
  const [theme, setTheme] = useState(document.documentElement.dataset.theme ?? 'light');
  const onToggle = () => {
    const next = theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem('asf-theme', next);
    } catch {
      /* theme persistence is optional */
    }
    setTheme(next);
  };
  if (compact) {
    return <IconToggle theme={theme} onToggle={onToggle} />;
  }
  return (
    <button
      type="button"
      className="btn btn-ghost"
      onClick={onToggle}
      aria-pressed={theme === 'dark'}
    >
      <Icon name={theme === 'dark' ? 'sun' : 'moon'} className="icon-sm" />
      {theme === 'dark' ? 'Light mode' : 'Dark mode'}
    </button>
  );
}

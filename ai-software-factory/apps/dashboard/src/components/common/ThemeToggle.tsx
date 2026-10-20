import { useState } from 'react';

export function ThemeToggle() {
  const [theme, setTheme] = useState(document.documentElement.dataset.theme ?? 'light');
  const toggle = () => {
    const next = theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem('asf-theme', next);
    } catch {
      /* ignore */
    }
    setTheme(next);
  };
  return (
    <button type="button" className="btn btn-ghost" onClick={toggle} aria-pressed={theme === 'dark'}>
      {theme === 'dark' ? '☀ Light mode' : '☾ Dark mode'}
    </button>
  );
}

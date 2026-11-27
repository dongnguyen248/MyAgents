import { useState, type KeyboardEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAgents } from '../../features/agent-management';
import { NAV_ITEMS } from '../../layouts/navItems';
import type { Agent } from '../../types/agent';
import { Icon, type IconName } from './Icon';

interface Entry {
  label: string;
  hint: string;
  to: string;
  icon: IconName;
}

function buildEntries(agents: Agent[]): Entry[] {
  const pages: Entry[] = NAV_ITEMS.map((item) => ({
    label: item.label,
    hint: 'Page',
    to: item.to,
    icon: item.icon,
  }));
  const agentEntries: Entry[] = agents.map((agent) => ({
    label: agent.name,
    hint: `Agent · ${agent.id}`,
    to: `/agents/${agent.id}`,
    icon: 'bot',
  }));
  return [...pages, ...agentEntries];
}

function matchEntries(entries: Entry[], query: string): Entry[] {
  const needle = query.trim().toLowerCase();
  if (!needle) {
    return entries;
  }
  return entries.filter((entry) => `${entry.label} ${entry.hint}`.toLowerCase().includes(needle));
}

function PaletteResults({
  matches,
  query,
  onPick,
}: {
  matches: Entry[];
  query: string;
  onPick: (to: string) => void;
}) {
  if (matches.length === 0) {
    return <p className="modal-empty">No match for “{query}”.</p>;
  }
  return (
    <>
      {matches.map((entry) => (
        <Link
          key={entry.to}
          className="popover-item"
          to={entry.to}
          onClick={() => onPick(entry.to)}
        >
          <Icon name={entry.icon} className="icon-sm" />
          <span>{entry.label}</span>
          <span className="muted">{entry.hint}</span>
        </Link>
      ))}
    </>
  );
}

interface SearchProps {
  query: string;
  matches: Entry[];
  onQuery: (query: string) => void;
  onPick: (to: string) => void;
  onClose: () => void;
}

function PaletteSearch({ query, matches, onQuery, onPick, onClose }: SearchProps) {
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    const first = matches[0];
    if (event.key === 'Enter' && first) {
      onPick(first.to);
    }
    if (event.key === 'Escape') {
      onClose();
    }
  };
  return (
    <input
      autoFocus
      value={query}
      placeholder="Jump to a page or an agent…"
      aria-label="Search pages and agents"
      onChange={(event) => onQuery(event.target.value)}
      onKeyDown={onKeyDown}
    />
  );
}

function Palette({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate();
  const agents = useAgents();
  const [query, setQuery] = useState('');
  const matches = matchEntries(buildEntries(agents.data ?? []), query);
  const go = (to: string) => {
    navigate(to);
    onClose();
  };
  return (
    <>
      <PaletteSearch
        query={query}
        matches={matches}
        onQuery={setQuery}
        onPick={go}
        onClose={onClose}
      />
      <div className="modal-list">
        <PaletteResults matches={matches} query={query} onPick={go} />
      </div>
    </>
  );
}

/** Backdrop + dialog chrome around the palette body. */
function PaletteFrame({ onClose }: { onClose: () => void }) {
  return (
    <div
      className="modal-backdrop"
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <div className="modal" role="dialog" aria-modal="true" aria-label="Quick search">
        <Palette onClose={onClose} />
      </div>
    </div>
  );
}

/**
 * Cmd/Ctrl+K quick jump: every page plus every registered agent. The dialog is
 * a child component so its query resets every time the palette reopens.
 */
export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  return open ? <PaletteFrame onClose={onClose} /> : null;
}

import { Icon } from '../common/Icon';

const COPY = {
  skills: {
    title: 'Skills',
    icon: 'sparkles',
    empty: 'No skill package is bound to this agent.',
    note: 'A skill is injected into the agent’s prompt on runs whose project enables it.',
  },
  tools: {
    title: 'Tools',
    icon: 'wrench',
    empty: 'No tool is bound to this agent.',
    note: 'Tools are the ports the agent may call during a step; the sandbox enforces the rest.',
  },
} as const;

/** Skills / tools tab shared by both capability tabs of the setup drawer. */
export function AgentCapabilityList({
  kind,
  items,
}: {
  kind: 'skills' | 'tools';
  items: string[];
}) {
  const copy = COPY[kind];
  return (
    <section>
      <h3 className="section-title">{copy.title}</h3>
      {items.length === 0 ? (
        <p className="note">{copy.empty}</p>
      ) : (
        <ul className="pill-list">
          {items.map((item) => (
            <li key={item} className="chip">
              <Icon name={copy.icon} className="icon-sm" />
              {item}
            </li>
          ))}
        </ul>
      )}
      <p className="note">{copy.note}</p>
    </section>
  );
}

import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';

export function PageHeader({ title, subtitle, actions, back }: { title: string; subtitle?: string; actions?: ReactNode; back?: { to: string; label: string } }) {
  return (
    <header className="page-header">
      <div>
        {back && (
          <Link className="back" to={back.to}>
            ← {back.label}
          </Link>
        )}
        <h1>{title}</h1>
        {subtitle && <p className="muted">{subtitle}</p>}
      </div>
      {actions && <div className="toolbar">{actions}</div>}
    </header>
  );
}

export function Card({ title, actions, children, flush }: { title?: string; actions?: ReactNode; children: ReactNode; flush?: boolean }) {
  return (
    <section className="card">
      {(title || actions) && (
        <div className="card-head">
          {title && <h2>{title}</h2>}
          {actions}
        </div>
      )}
      <div className={flush ? 'card-body flush' : 'card-body'}>{children}</div>
    </section>
  );
}

export function KpiCard({ label, value, hint, tone }: { label: string; value: string | number; hint?: string; tone?: 'danger' | 'warn' | 'ok' }) {
  return (
    <div className={`kpi ${tone ? `kpi-${tone}` : ''}`}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      {hint && <div className="kpi-hint muted">{hint}</div>}
    </div>
  );
}

export function Stat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="stat">
      <dt className="muted">{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <p className="empty muted">{children}</p>;
}

/** Health score meter: number + bar + text so it works without colour. */
export function HealthMeter({ score }: { score?: number }) {
  if (score === undefined) return <span className="muted">–</span>;
  const tone = score >= 85 ? 'ok' : score >= 70 ? 'warn' : 'danger';
  return (
    <span className="meter-wrap" title={`Health score ${score}/100`}>
      <span className="meter" role="img" aria-label={`Health score ${score} out of 100`}>
        <span className={`meter-fill meter-${tone}`} style={{ width: `${score}%` }} />
      </span>
      <strong>{score}</strong>
    </span>
  );
}

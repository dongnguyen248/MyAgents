import { Link } from 'react-router-dom';
import { stageSummary, verdictTone } from '../../lib/reviewViews';
import type { ReviewFinding, ReviewRound, ReviewStage, RunReviews } from '../../types/workflow';
import { titleCase } from '../../utils/format';

const TONE_CLASS = { ok: 'badge-ok', warn: 'badge-warn', neutral: 'badge-neutral' } as const;
const SEVERITY_ORDER = ['BLOCKER', 'MAJOR', 'MINOR', 'NIT'] as const;

function VerdictChip({ verdict }: { verdict: string | null }) {
  if (!verdict) {
    return <span className="badge badge-neutral">no verdict</span>;
  }
  return (
    <span className={`badge ${TONE_CLASS[verdictTone(verdict)]}`}>
      {titleCase(verdict.replace('_', ' '))}
    </span>
  );
}

function FindingItem({ finding }: { finding: ReviewFinding }) {
  return (
    <li>
      <span
        className={`badge ${finding.severity === 'BLOCKER' ? 'badge-danger' : 'badge-neutral'}`}
      >
        {finding.severity}
      </span>{' '}
      <strong>{finding.id}</strong> <span className="muted">{finding.category}</span>{' '}
      <span className="muted">· {finding.location}</span>
      <div>{finding.problem}</div>
      <div className="muted small">
        Required change: {finding.requiredChange} · Status: {titleCase(finding.status)}
        {finding.source === 'mechanical' ? ' · mechanical check' : ''}
        {finding.waiverReason ? ` · Waived: ${finding.waiverReason}` : ''}
      </div>
    </li>
  );
}

function RoundItem({ round, stage }: { round: ReviewRound; stage: string }) {
  const counts = SEVERITY_ORDER.filter((s) => (round.counts[s] ?? 0) > 0)
    .map((s) => `${s} ${round.counts[s] ?? 0}`)
    .join(' · ');
  return (
    <li>
      <div className="filters">
        <strong>Round {round.round}</strong>
        <VerdictChip verdict={round.verdict} />
        {counts && <span className="muted small">{counts}</span>}
        <span className="muted small">
          reviewed {titleCase(stage)} v{round.reviewedArtifactVersion ?? '?'}
        </span>
      </div>
      {round.summary && <p className="small">{round.summary}</p>}
      {round.findings.length > 0 && (
        <details>
          <summary className="small">Findings ({round.findings.length})</summary>
          <ul>
            {round.findings.map((finding) => (
              <FindingItem key={finding.id} finding={finding} />
            ))}
          </ul>
        </details>
      )}
    </li>
  );
}

function StageTimeline({ stage }: { stage: ReviewStage }) {
  const summary = stageSummary(stage);
  return (
    <div>
      <div className="filters">
        <strong>{titleCase(stage.stage)}</strong>
        <span className="muted small">
          {summary.rounds} round{summary.rounds === 1 ? '' : 's'}
          {summary.openBlockers > 0 ? ` · ${summary.openBlockers} blocker(s) still open` : ''}
        </span>
        <VerdictChip verdict={summary.latestVerdict} />
      </div>
      <ul>
        {stage.rounds.map((round) => (
          <RoundItem key={round.round} round={round} stage={stage.stage} />
        ))}
      </ul>
    </div>
  );
}

/**
 * The per-stage AI review rounds of a run (GET /runs/{id}/reviews):
 * read-only history — verdict per round, severity counts, and the
 * findings behind each REQUEST_CHANGES.
 */
export function ReviewTimeline({ reviews, runHref }: { reviews: RunReviews; runHref?: string }) {
  if (reviews.stages.length === 0) {
    return <p className="muted">No AI review rounds yet.</p>;
  }
  return (
    <div>
      {reviews.stages.map((stage) => (
        <StageTimeline key={stage.stage} stage={stage} />
      ))}
      {runHref && (
        <p className="small">
          <Link to={runHref}>Open the run</Link> for the reviewed artifacts and the full history.
        </p>
      )}
    </div>
  );
}

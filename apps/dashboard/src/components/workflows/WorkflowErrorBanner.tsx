import { errorBannerText } from '../../lib/errorBanner';
import type { Workflow } from '../../types/workflow';

/**
 * Red banner stating why a run failed — the failed step plus the exact
 * error the backend recorded — so a failure is diagnosable at a glance
 * instead of by digging through the execution history. The wording is
 * computed by the pure lib function so it is unit-testable.
 */
export function WorkflowErrorBanner({ workflow }: { workflow: Workflow }) {
  const banner = errorBannerText(workflow);
  if (!banner) {return null;}
  return (
    <p className="alert" role="alert">
      {banner.headline}{' '}
      <span className="muted small">{banner.codeLine}</span>
      {banner.detailLines.length > 0 && (
        <span className="small">
          {banner.detailLines.map((line) => (
            <span key={line}>
              <br />
              {line}
            </span>
          ))}
        </span>
      )}
    </p>
  );
}

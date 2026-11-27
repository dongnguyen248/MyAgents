import type { ModelTestResult } from '../../types/settings';

interface SaveStatus {
  busy: boolean;
  error?: string;
  notice?: string;
}

function StatusText({
  status,
  test,
  testFor,
}: {
  status: SaveStatus;
  test: ModelTestResult | null;
  testFor: string;
}) {
  if (status.error) {
    return <span className="error-text">{status.error}</span>;
  }
  if (test) {
    return (
      <span className={test.ok ? 'muted small' : 'error-text'}>
        {test.ok ? '✓ ' : '✗ '}
        {testFor ? `${testFor}: ` : ''}
        {test.message}
      </span>
    );
  }
  if (status.notice) {
    return <span className="muted small">{status.notice}</span>;
  }
  return <span className="muted small">Stored by the backend on this machine.</span>;
}

/** Sticky save bar: one save covers all three tabs. */
export function LlmActionBar({
  status,
  test,
  testFor,
  onTest,
}: {
  status: SaveStatus;
  test: ModelTestResult | null;
  testFor: string;
  onTest: () => void;
}) {
  return (
    <div className="action-bar">
      <button type="submit" className="btn btn-primary" disabled={status.busy}>
        {status.busy ? 'Saving…' : 'Save'}
      </button>
      <button type="button" className="btn" disabled={status.busy} onClick={onTest}>
        Save &amp; test
      </button>
      <span className="spacer" />
      <StatusText status={status} test={test} testFor={testFor} />
    </div>
  );
}

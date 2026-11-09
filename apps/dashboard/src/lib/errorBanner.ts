import type { Workflow, WorkflowStep } from '../types/workflow';

/** The failure banner as plain text parts, React-free so the exact
 * wording a user sees can be unit-tested (tests/errorBanner.test.ts). */
export interface ErrorBannerText {
  headline: string;
  codeLine: string;
  detailLines: string[];
}

const MAX_DETAIL_LINES = 6;

function arrayItemLine(key: string, item: unknown): string | null {
  if (typeof item === 'string') {
    return `${key}: ${item}`;
  }
  if (item && typeof item === 'object') {
    const record = item as Record<string, unknown>;
    const path = typeof record.path === 'string' ? record.path : '';
    const why = [record.operation, record.reason ?? record.issue]
      .filter((part) => typeof part === 'string')
      .join(' — ');
    return `${key}: ${path}${why ? ` (${why})` : ''}`;
  }
  return null;
}

function valueLines(key: string, value: unknown): string[] {
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return [`${key}: ${value}`];
  }
  if (!Array.isArray(value)) {
    return [];
  }
  const lines: string[] = [];
  for (const item of value) {
    const line = arrayItemLine(key, item);
    if (line !== null) {
      lines.push(line);
    }
  }
  return lines;
}

/** Flatten an error's structured details into short readable lines. */
export function errorDetailLines(details: Record<string, unknown>): string[] {
  const lines: string[] = [];
  for (const [key, value] of Object.entries(details)) {
    lines.push(...valueLines(key, value));
  }
  return lines.slice(0, MAX_DETAIL_LINES);
}

function failureWhere(workflow: Workflow, failedStep: WorkflowStep | undefined): string {
  // A death inside the code-fix loop is attributed to the step whose
  // verdict triggered the fix — but the thing that actually died is
  // the fix attempt itself, so name it instead of blaming that step.
  if (workflow.error?.stage === 'CODE_FIX') {
    return ` in code fix${failedStep ? ` (after ${failedStep.label})` : ''}`;
  }
  return failedStep ? ` at ${failedStep.label}` : '';
}

/**
 * The banner text for a failed run — the failed step plus the exact
 * error the backend recorded — or null when the run has no failure
 * to show.
 */
export function errorBannerText(workflow: Workflow): ErrorBannerText | null {
  if (workflow.status !== 'FAILED' || !workflow.error) {
    return null;
  }
  const failedStep = workflow.steps.find((s) => s.state === 'failed');
  return {
    headline: `Failed${failureWhere(workflow, failedStep)}: ${workflow.error.message}`,
    codeLine: `(${workflow.error.code} · ${workflow.error.category})`,
    detailLines: workflow.error.details ? errorDetailLines(workflow.error.details) : [],
  };
}

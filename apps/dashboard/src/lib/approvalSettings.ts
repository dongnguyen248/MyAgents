import type { Project, ProjectProfileInput } from '../types/project';

/** The profile-input configuration of a project view (edit-form prefill). */
export function projectConfigurationInput(project: Project): ProjectProfileInput['configuration'] {
  const approval = projectApprovalInput(project);
  return {
    ...(approval ? { approval } : {}),
    ...(project.testCommands.length ? { testCommands: project.testCommands } : {}),
  };
}

function projectApprovalInput(
  project: Project,
): { channel: string; mode?: string; maxRevisions?: number; onExhausted?: string } | undefined {
  const anySet =
    project.approvalChannel ||
    project.approvalMode ||
    project.approvalMaxRevisions !== null ||
    project.approvalOnExhausted;
  if (!anySet) {
    return undefined;
  }
  return {
    channel: project.approvalChannel,
    ...(project.approvalMode ? { mode: project.approvalMode } : {}),
    ...(project.approvalMaxRevisions !== null
      ? { maxRevisions: project.approvalMaxRevisions }
      : {}),
    ...(project.approvalOnExhausted ? { onExhausted: project.approvalOnExhausted } : {}),
  };
}

/**
 * Client-side validation for a project's approval settings,
 * mirroring the server's `parse_approval_overrides` bounds:
 * mode is one of ai/human/none (or unset), maxRevisions is an
 * integer in 1..10 (or unset), onExhausted is escalate or
 * accept_with_warnings (or unset).
 */
export const APPROVAL_MODES = ['ai', 'human', 'none'] as const;
export const ON_EXHAUSTED_OPTIONS = ['escalate', 'accept_with_warnings'] as const;
export const MAX_REVISIONS_MIN = 1;
export const MAX_REVISIONS_MAX = 10;

export interface ApprovalSettingsInput {
  /** '' means "leave unset" (the workflow default applies). */
  mode: string;
  /** Raw form text; '' means unset. */
  maxRevisions: string;
  /** '' means unset. */
  onExhausted: string;
}

export function validateApprovalSettings(input: ApprovalSettingsInput): string[] {
  const errors: string[] = [];
  if (input.mode !== '' && !(APPROVAL_MODES as readonly string[]).includes(input.mode)) {
    errors.push(`Approval mode must be one of ${APPROVAL_MODES.join(', ')} or left unset.`);
  }
  const revisions = input.maxRevisions.trim();
  if (revisions !== '') {
    const value = Number(revisions);
    if (!Number.isInteger(value) || value < MAX_REVISIONS_MIN || value > MAX_REVISIONS_MAX) {
      errors.push(
        `Max revisions must be a whole number between ${MAX_REVISIONS_MIN} and ${MAX_REVISIONS_MAX}, or left unset.`,
      );
    }
  }
  if (
    input.onExhausted !== '' &&
    !(ON_EXHAUSTED_OPTIONS as readonly string[]).includes(input.onExhausted)
  ) {
    errors.push(`On exhausted must be one of ${ON_EXHAUSTED_OPTIONS.join(', ')} or left unset.`);
  }
  return errors;
}

/** The parsed maxRevisions for the payload, or undefined when unset. Call only after validation passes. */
export function parseMaxRevisions(text: string): number | undefined {
  const revisions = text.trim();
  return revisions === '' ? undefined : Number(revisions);
}

/** The API caps an escalation reason at 500 characters (a longer one is a 422). */
export const MAX_REASON_CHARS = 500;

/** The escalation reason rule shared by Resume and Approve anyway (mirrors the API's 422 check). */
export function escalationReasonError(reason: string): string | undefined {
  const trimmed = reason.trim();
  if (!trimmed) {
    return 'A reason is required.';
  }
  if (trimmed.length > MAX_REASON_CHARS) {
    return `The reason must be at most ${MAX_REASON_CHARS} characters.`;
  }
  return undefined;
}

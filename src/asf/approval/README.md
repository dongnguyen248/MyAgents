# Human Approval Engine (`src/asf/approval/`)

## Responsibilities
The approval package provides a pure in-memory human approval engine for managing the lifecycle of review requests across workflow stages (e.g. Spec, Plan, Task, Code Review, Deployment).

It enforces approval policies, multi-reviewer thresholds, lazy and proactive expirations, decision logging, and reviewer feedback collection.

In accordance with platform purity rules (Rule 9):
- **Time is injected:** The engine never reads the system clock; callers pass timezone-aware `now: datetime` timestamps.
- **Identifiers are injected:** IDs are generated using an injected `id_factory: Callable[[], str]` (no `uuid` or `random` imports).
- **No I/O:** The engine operates strictly in memory via the `ApprovalRepository` protocol.

## Policy Source (A2)
Approval policies are derived from project configuration via `approval_policy_from_project(profile: ProjectProfile)`:
- Source: `profile.configuration["approval"]`
- `reviewers`: Required, non-empty list of non-empty, unique identifier strings.
- `minApprovals`: Optional integer `>= 1` and `<= len(reviewers)` (default: `1`).
- `expiresInSeconds`: Optional integer `>= 1` or `null` (default: `null` = never expires).
- `channel` and any additional keys are ignored pass-through configuration.
- Missing `approval` configuration or invalid/empty reviewers raises a `ConfigError` (`VALIDATION_FAILED`) with the dotted configuration path. There is never an implicit "anyone may approve". Real project profiles do not contain reviewer identifiers until the Teams adapter is configured.

## Approval Decision Rules (A5 & A6)
When `ApprovalService.decide(decision: ApprovalDecision)` is called, rules execute in this strict order:
1. **Unknown approvalId:** If request does not exist, raise `ApprovalError` (`NOT_FOUND`).
2. **Closed-request rule (A6) & lazy expiry:**
   - Status `EXPIRED`: raise `ApprovalError` (`APPROVAL_EXPIRED`).
   - Status `APPROVED`, `REJECTED`, or `CHANGES_REQUESTED`: raise `ApprovalError` (`APPROVAL_ALREADY_DECIDED`).
   - Status `CANCELLED`: raise `ApprovalError` (`VALIDATION_FAILED` with `details.status = "CANCELLED"`).
   - If status is `PENDING`, `expiresAt` is set, and `decision.createdAt >= expiresAt`: persist status `EXPIRED` and raise `ApprovalError` (`APPROVAL_EXPIRED`).
3. **Chronology:** If `decision.createdAt < request.requestedAt`, raise `ApprovalError` (`VALIDATION_FAILED`).
4. **Authorization:** If `decision.reviewer` is not in the request's snapshotted `reviewers`, raise `ApprovalError` (`APPROVAL_NOT_AUTHORIZED`). Nothing is stored.
5. **Comment validation:** If `decision.decision` is `REJECTED` or `REQUEST_CHANGES` and `comment` is empty or whitespace-only, raise `ApprovalError` (`VALIDATION_FAILED`).
6. **Duplicate approval:** If `decision.decision` is `APPROVED` and this reviewer already approved this request, raise `ApprovalError` (`APPROVAL_ALREADY_DECIDED`) with `details.reviewer`.
7. **Store and transition:**
   - Store the decision in the repository.
   - `REJECTED` -> immediate transition to `REJECTED`.
   - `REQUEST_CHANGES` -> immediate transition to `CHANGES_REQUESTED`.
   - `APPROVED` -> count distinct approving reviewers; if `>= minApprovals`, transition to `APPROVED`; otherwise stay `PENDING`.

## Lifecycle and Expiry (A7)
- **Pending constraint:** At most one `PENDING` request is allowed per `(taskId, artifactId, type)`. Attempting a second pending request raises `ApprovalError` (`VALIDATION_FAILED`). Once closed, a new request may be opened.
- **Cancellation:** `cancel(approvalId, now)` moves a `PENDING` request to `CANCELLED`. Calling `cancel` on a closed request follows the closed-request rule (A6).
- **Proactive expiry:** `expire_due(now)` scans all `PENDING` requests with `expiresAt <= now`, moves them to `EXPIRED`, and returns the newly expired requests ordered by `(expiresAt, id)`. Subsequent calls return `[]`.
- All `now` arguments must be timezone-aware (naive raises `ValueError`).

## Feedback Collection (A8)
`feedback_for(approvalId)` returns all stored `REJECTED` and `REQUEST_CHANGES` decisions as `ApprovalFeedback` objects in decision order (`[]` if none, `NOT_FOUND` if the request is unknown).
The orchestrator supplies this feedback list in `AgentRequest.feedback` when re-invoking the producing agent, replacing earlier conventions.

## Error Codes (A9)
Errors are raised as `ApprovalError(Exception)` with attributes `code`, `message`, `details` and a method `to_platform_error(now: datetime)`.
- `NOT_FOUND` -> `SYSTEM` category
- `VALIDATION_FAILED` -> `VALIDATION` category
- `APPROVAL_EXPIRED` -> `APPROVAL` category
- `APPROVAL_ALREADY_DECIDED` -> `APPROVAL` category
- `APPROVAL_NOT_AUTHORIZED` -> `APPROVAL` category
Retryable is always `false`. Calling `to_platform_error` with a naive datetime raises `ValueError`.

## Status to State Machine Trigger Mapping (A10)
For the orchestrator in Phase 6:
- Request status `APPROVED` -> Trigger `APPROVED`
- Request status `REJECTED` -> Trigger `REJECTED`
- Request status `CHANGES_REQUESTED` -> Trigger `REQUEST_CHANGES`
- Statuses `PENDING`, `EXPIRED`, `CANCELLED` -> No trigger emitted (orchestrator decides what expiry means).

## What Is NOT Here
- No storage backends (database, disk): only the in-memory repository protocol is used.
- No Teams, Slack, email, or notification channel adapters (Phase 8).
- No orchestrator or agent dispatch logic (Phase 6).

# Phase 8 - Teams Workflows approval report

## 1. Scope and result

Implemented the confirmed **Teams Workflows / Power Automate** approach:
**no custom Teams bot** registration, hosted bot, Bot Framework endpoint or bot
SDK dependency in the application manifest.

The local automated test proves this loop:

1. Actual SpecAgent creates SPEC v1.
2. The automatic dispatcher sends the complete SPEC as an Adaptive Card.
3. An authenticated Flow callback rejects it with a required comment.
4. The orchestrator passes the previous SPEC and feedback to SpecAgent.
5. SpecAgent creates SPEC v2; a new approval/card is sent automatically.
6. The original card cannot approve v2.
7. Approving v2 automatically dispatches actual PlanAgent.
8. PLAN references the approved SPEC v2 and the demo reaches COMPLETED.

**This is offline implementation evidence, not live Teams/Gemini validation.**
The default demo uses deterministic model responses. The optional `--gemini`
flag enables the existing real model gateway only when the user explicitly
runs it. No Microsoft/model API was called during development.

GitLab and CI Gate remain deferred. Phase 8 as a whole is not complete.

## 2. Changes

| File | Change |
|---|---|
| [workflow.py](../src/asf/integrations/teams/workflow.py) | Bounded Flow delivery, constant-time callback authentication, strict decision endpoint, automatic dispatcher, health/failure handling. |
| [config.py](../src/asf/integrations/teams/config.py) | Env-only trigger/callback credentials, exact HTTPS host pinning, reviewer/destination settings; rejects bot configuration. |
| [approval.py](../src/asf/integrations/teams/approval.py) | Validates Flow-attested tenant/team/channel/reviewer identity and delegates decisions to the core. |
| [cards.py](../src/asf/integrations/teams/cards.py) | Full-artifact Adaptive Card with Approve and Reject plus required rejection comment. |
| [demo.py](../src/asf/integrations/teams/demo.py) | Local SQLite Spec -> approval/revision -> Plan demo; explicit Teams send and optional Gemini opt-in. |
| [engine.py](../src/asf/orchestrator/engine.py) | Public pending-approval query and atomic optional expected-approval-ID check; existing callers remain compatible. |
| [test_teams_approval.py](../tests/unit/test_teams_approval.py) | Authorization, binding, core approvals, stale cards, quorum, expiry and config tests. |
| [test_teams_workflow.py](../tests/unit/test_teams_workflow.py) | Fake outbound transport, in-process authenticated callbacks, automatic real-agent revision/handoff proof and failure tests. |
| [test_teams_demo.py](../tests/unit/test_teams_demo.py) | Deterministic agent chain, fake-network manual-host wiring, mocked Gemini selection and execution correlation. |
| [pyproject.toml](../pyproject.toml) | Optional `teams` extra now uses FastAPI/Uvicorn/HTTPX, not the Microsoft bot SDK. |
| [Teams setup guide](../src/asf/integrations/teams/README.md) | Replaced bot setup with Flow trigger/card/callback mapping, trust boundary, manual commands and limitations. |
| [platform.example.yaml](../config/platform.example.yaml) | Points operators to Workflows configuration. |
| [README.md](../README.md) | Corrected Phase 8 scope and no-custom-bot behavior. |
| [This report](./PHASE_8_TEAMS_REPORT.md) | Supersedes the earlier uncommitted bot implementation report. |

The obsolete new/uncommitted bot module and bot-specific tests were replaced
after the user's architecture correction. No committed pre-existing test was
deleted or weakened. The old bot milestone's 1,080 tests / JWT claims must not
be used as evidence for this different trust boundary.

## 3. Decision behavior

| Situation | Result |
|---|---|
| Approve | Core records the vote; once quorum is met, the dispatcher runs the next configured agent automatically. |
| Reject + nonblank comment | Core records feedback, returns to the producing step, and dispatches a revision; the revised artifact requires a fresh approval. |
| Reject without comment | 422; no decision or revision is recorded. |
| Wrong/missing callback secret | 401 before parsing the body. |
| Unapproved tenant/team/channel/reviewer | 403; identity is not accepted from editable card inputs. |
| A callback for another hosted run | 403. |
| Unknown run | 404 when applicable. |
| Stale approval ID / repeated vote | 409; no second vote or approval of a different version. |
| Expired approval | 410, using the trusted server clock. |
| Invalid/extra callback fields | 422, without echoing input or validation details. |
| Callback over 16,384 bytes | 413 before accumulating the oversized chunk. |
| Flow transport/non-success/oversized response | Safe INTEGRATION_UNAVAILABLE failure, dispatcher pauses; no remote URL/body is echoed. |
| Partial quorum | A fresh single-response card is sent for remaining reviewers; duplicate votes do not count. |
| Revision budget exhausted | Existing escalation policy is preserved; no unlimited agent/rejection loop. |

The demo allows three SPEC revisions and a one-hour approval expiry. It
finishes after PLAN; it is deliberately not a replacement for a complete
configured production chain. With an existing full workflow/agent registry,
the same dispatcher follows its configured steps and approval gates.

## 4. Authentication, credentials and delivery

- The generated Flow trigger URL is a credential, read from an env reference.
  HTTPS/443 and the exact configured hostname are required. No redirects.
- ASF authenticates Flow callbacks with an independent env secret, at least
  32 non-whitespace printable ASCII characters, using constant-time comparison.
- Flow must attest the responder's Entra object ID from the trusted Teams
  connector output, never a user-editable card identity, email input or name.
- ASF binds that attestation to the configured tenant/team/channel and mapped
  core reviewer. **ASF does not directly validate a Microsoft user JWT.**
- Flow owners/connections and callback secrets are part of the trust boundary.
  Someone holding the callback secret could forge a Flow attestation.
- The adapter currently uses signed-URL/legacy Anyone HTTP triggers, not Entra
  OAuth token acquisition to Flow. An organization forbidding this mode needs
  a separately reviewed OAuth implementation, not a policy workaround.
- Known configured callback/trigger secrets are rejected in outgoing cards
  and decision feedback. Exception/response/log tests use runtime-generated
  fake credentials and prove no value is echoed.
- Request bodies, authorization headers and trigger URLs are not logged.
  Uvicorn access logging is disabled in the demo; secure the external proxy
  and Power Automate action inputs/outputs too.
- Delivery is at-least-once. Accepted approval IDs are kept in process memory;
  restarting can resend a card. Actual decisions are durable in SQLite and
  guarded transactionally against stale/replayed approval IDs.
- Outbound responses are bounded to 4096 bytes; the default timeout is 30s.
  There is no automatic delivery retry. A failed delivery pauses execution
  and produces a safe health/log error until explicitly restarted.
- A card above 28,000 UTF-8 bytes fails explicitly; SPEC is never silently
  truncated. Teams/Flow/SQLite content remains confidential application data,
  not universally sanitized or encrypted storage.

## 5. Automated evidence

Phase 6 baseline: **1,027 tests, 404 subtests**.
Current: **1,098 tests, 404 subtests** = **71 added Teams cases**.
There were no skipped/xfail cases reported.

Key end-to-end local test:
`test_authenticated_reject_rewrites_spec_then_approve_automatically_runs_plan`.
It uses the actual SpecAgent, PlanAgent, SQLite store, ASGI callback and
background dispatcher. Assertions verify feedback and previous SPEC are in
the revision prompt, version increments, old-card rejection, automatic PLAN
dispatch and exact SPEC v2 linkage. Model and outbound HTTP are fake.

Other tested conditions include callback authentication, scope/identity
binding, missing feedback, replay, expiry, quorum, redirect/non-success
delivery, timeout/transport failure, secret echoes, callback/card size bounds,
paused health, repeated polling without duplicate cards and escalation.
Tests create SQLite and run callbacks/driver on the same thread.

Focused statement coverage: **96%** (328 statements, 13 missed).
The CLI's module entry and several invalid-input branches are not all covered.
This is not a claim of exhaustive security or live connector compatibility.

### Gate results

All Python commands used `.\.venv\Scripts\python.exe`.

| Gate | Result | Exit |
|---|---|---|
| `-m pytest tests\ -x -q` | 1,098 passed, 404 subtests passed | 0 |
| `-m mypy src\ --strict` | No issues, 100 source files | 0 |
| `-m ruff check src\ tests\` | All checks passed | 0 |
| `-m bandit -r src\` | 0 Low / Medium / High | 0 |
| `rg -n 'TODO\|FIXME' src\asf\agents\implement src\asf\integrations\teams src\asf\orchestrator -g '*.py'` | No matches | 1 (normal no-match status) |

Bandit reports one pre-existing specifically disabled potential issue; no new
suppression was added. Bandit is **not** a dependency-CVE audit.
The available CVE tool does not support PyPI; no current advisory-database
cleanliness claim is made. The bot SDK was removed from the manifest, not
uninstalled from the shared local virtual environment.

Additional checks:

- Teams selectors with coverage: **71 passed**, exit 0.
- `git diff --check`: exit 0.
- Literal credential-shape worktree scan: **275 text files, 0 matching lines**.
  Source: the user's five-pattern regex from the previous literal cleanup.
  Scope: `git ls-files --cached --others --exclude-standard`, limited to
  py/md/yaml/yml/toml/json/ps1/patch/bak/txt; ignored .git, venv, cache,
  evidence and artifacts excluded. This is a worktree scan, not history or
  a general secret-scanner assurance. No credential-shaped values were printed.
- No stage, commit, push or history rewrite during this Teams development.

### Raw gate output

Full test suite, exit 0:

```text
............................................................. [  5%]
.................................. [  8%]
............................................................................ [ 15%]
............................ [ 18%]
........................................................................ [ 24%]
........................................................................ [ 31%]
.................................................................... [ 37%]
........................................................................................................................ [ 48%]
........................................................................ [ 54%]
........................................................................ [ 61%]
............................................................................................. [ 69%]
........................................................................ [ 76%]
........................................................................ [ 83%]
........................................................................ [ 89%]
........................................................................ [ 96%]
..........................................           [100%]
1098 passed, 404 subtests passed in 12.19s
```

Mypy, exit 0:

```text
Success: no issues found in 100 source files
```

Ruff, exit 0:

```text
All checks passed!
```

Bandit, exit 0:

```text
[main]	INFO	profile include tests: None
[main]	INFO	profile exclude tests: None
[main]	INFO	cli include tests: None
[main]	INFO	cli exclude tests: None
[main]	INFO	running on Python 3.13.5
Working... ---------------------------------------- 100% 0:00:01
Run started:2026-11-02 09:54:21.910757+00:00

Test results:
	No issues identified.

Code scanned:
	Total lines of code: 8614
	Total lines skipped (#nosec): 0
	Total potential issues skipped due to specifically being disabled (e.g., #nosec BXXX): 1

Run metrics:
	Total issues (by severity):
		Undefined: 0
		Low: 0
		Medium: 0
		High: 0
	Total issues (by confidence):
		Undefined: 0
		Low: 0
		Medium: 0
		High: 0
Files skipped (0):
```

TODO/FIXME search, exit 1: **empty stdout/stderr**.

## 6. User setup and manual acceptance

Follow the [Workflows setup guide](../src/asf/integrations/teams/README.md).
The repository cannot create your cloud Flow, Teams connection, licensing or
public HTTPS proxy without tenant administration.

Required Flow sequence:

1. HTTP trigger with a protected generated URL and fixed destination checks.
2. Immediate Response **202**, before waiting for a human.
3. Current **Post adaptive card and wait for a response** action.
4. Resolve the responder's trusted Entra object ID.
5. POST a strictly mapped decision to the fixed ASF HTTPS callback, with the
   independent callback secret and Secure Inputs/Outputs enabled.
6. Bounded re-post branch for unauthorized/malformed consumed cards; alerts
   for delivery/auth failures. A card can be submitted only once.

The Microsoft connector declares outputs **dynamic**. The exact responder
property path must be verified in your tenant; the guide deliberately uses
mapping placeholders rather than guessing an identity claim path.

Run offline checks:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\test_teams_approval.py tests\unit\test_teams_workflow.py tests\unit\test_teams_demo.py -q
```

After configuring Flow, local env references and the approved HTTPS proxy:

```powershell
# Real Teams delivery, deterministic model responses:
.\.venv\Scripts\python.exe -m asf.integrations.teams.demo --send

# Explicitly opt into real Gemini as well, using your existing environment:
.\.venv\Scripts\python.exe -m asf.integrations.teams.demo --send --gemini --requirement "YOUR_REQUIREMENT"
```

Acceptance: receive SPEC v1 -> Reject with a comment -> receive revised SPEC v2
-> old card cannot approve v2 -> Approve v2 -> PLAN runs without manually
invoking another agent. Repeat-vote, missing-comment, wrong-reviewer and
expired-card paths must not advance the workflow.

Gemini uses one gateway/shared process-local 12-attempt budget across SPEC
and PLAN, 120s per request and at most two retries. Redacted evidence uses
the actual execution ID under ignored `.asf-evidence/`. Live resume is
explicitly rejected rather than silently resetting the same run's budget.

Remaining operational limitations:

- Single process and same SQLite-owning event-loop thread; synchronous
  agent/model/HTTP calls can block the loop. No HA/multi-worker guarantee.
- Real Teams rendering, required input behavior, responder mapping,
  licensing/DLP, trigger acceptance and callback connectivity are unverified
  until the user performs the manual live acceptance.
- Accepted delivery means Flow accepted a request, not that a card was posted;
  Flow failure monitoring/notifications are required.
- Durable delivery deduplication/retry, OAuth-authenticated Flow triggering,
  service deployment and a persistent live-model budget across restarts are
  not implemented.
- GitLab and CI Gate are not developed in this scope.

## 7. Official documentation used

- [Adaptive card flows and single-submit behavior](https://learn.microsoft.com/en-us/power-automate/create-adaptive-cards)
- [Current Teams card/wait action; dynamic outputs](https://learn.microsoft.com/en-us/connectors/teams/#post-adaptive-card-and-wait-for-a-response)
- [HTTP trigger authentication modes](https://learn.microsoft.com/en-us/power-automate/oauth-authentication)
- [Trigger URL changes](https://learn.microsoft.com/en-us/troubleshoot/power-platform/power-automate/flow-run-issues/triggers-troubleshoot#changes-to-http-or-teams-webhook-trigger-flows)
- [Inbound timeout and actions continuing after Response](https://learn.microsoft.com/en-us/power-automate/limits-and-config#timeout)

**Conclusion:** the requested no-custom-bot behavior is implemented and
verified offline. Live Teams/Flow acceptance and the remaining Phase 8
integrations are still outstanding; no readiness claim is made.

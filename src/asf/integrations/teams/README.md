# Teams Workflows approvals - no custom bot

The application sends an approval card through **Power Automate / Teams
Workflows**, not a bot that you register or host. The Workflows connector may
display cards as Microsoft's built-in Flow bot; no ASF bot app, bot credential,
Bot Framework SDK or Azure bot registration is needed.

```text
SpecAgent -> full SPEC card in Teams -> wait
  Reject + comment -> feedback + previous SPEC -> SpecAgent -> new SPEC/card
  Approve -> orchestrator automatically runs PlanAgent / the configured next step
```

GitLab and CI Gate remain deferred.

## What runs where

- **ASF:** renders the card, hosts an authenticated decision callback, persists
  core approvals in SQLite and automatically ticks the configured workflow.
- **Your Power Automate flow:** receives the card, posts it to a fixed Teams
  channel, waits for a response, identifies the responder using the connector
  and posts the decision back to ASF.
- **External prerequisites:** Workflows/Teams access, an appropriate Power
  Automate license/DLP policy for HTTP actions, and a reachable HTTPS callback
  endpoint. A Teams channel deep link or a send-only webhook is not enough.
- This change does **not** create or deploy your cloud flow, proxy, tenant
  resources or connections. No live Microsoft/model API was called during tests.

## 1. Configure ASF locally

Install the optional HTTP host/test dependencies (there is no bot SDK dependency):

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,teams]"
```

Put a notification entry in ignored `config/platform.local.yaml` using the
existing [platform configuration](../../../../config/platform.example.yaml):

```yaml
notifications:
  - name: teams-approvals
    type: teams-workflow
    credentials:
      env: ASF_TEAMS_WORKFLOW_URL
    settings:
      workflowHost: REPLACE_WITH_EXACT_LOWERCASE_FLOW_TRIGGER_HOSTNAME
      tenantId: REPLACE_WITH_TENANT_UUID
      teamId: REPLACE_WITH_TEAM_ENTRA_GROUP_UUID
      channelId: REPLACE_WITH_CHANNEL_ID
      callbackSecret:
        env: ASF_TEAMS_CALLBACK_SECRET
      reviewers:
        REPLACE_WITH_REVIEWER_ENTRA_OBJECT_UUID: core-reviewer-id
      timeoutSeconds: 30
```

The placeholders deliberately fail validation. Replace identifiers locally;
do not commit your organization/user IDs. `teamId` is the Entra group UUID.
Copy `workflowHost` from the generated trigger URL in your trusted Flow
designer; do not guess a regional host or reuse an obsolete trigger URL.
Outbound requests must use HTTPS/443 on this exact hostname. Redirects are
never followed.

Set two independent environment secrets using your secret manager:

- `ASF_TEAMS_WORKFLOW_URL`: the complete generated HTTP trigger URL, including
  its signature if present. Treat the **whole URL** as a credential. Do not put
  it in YAML `endpoint`, CLI arguments, logs or screenshots.
- `ASF_TEAMS_CALLBACK_SECRET`: a randomly generated, printable, non-whitespace
  ASCII secret of at least 32 characters. Configure the same value securely in
  the Flow callback HTTP action. It is not a Microsoft API key.

No values for either secret are provided in this repository or requested in chat.

## 2. Create the cloud flow once

Use the current **Post adaptive card and wait for a response**
(`PostCardAndWaitForResponse`) action, not the deprecated channel-only action
and not a send-only action.

### Trigger and initial response

1. Install/enable the Teams Workflows app and create an automated cloud flow
   with **When an HTTP request is received**.
2. This adapter currently supports the generated signed-URL/legacy **Anyone**
   trigger mode. Protect the URL as a secret. It does not acquire an Entra OAuth
   token for the inbound Flow trigger. If your organization disallows this mode,
   do not relax its policy: OAuth support is a separate follow-up.
3. Give the trigger the JSON schema below.
4. Add an immediate **Response** action with status **202**, before the card
   wait action. The ASF HTTP request only waits for acceptance, not for the
   human to decide. If you wait for human approval before responding, the ASF
   request will time out and pause delivery.
5. Pin Team and Channel in the Flow action to your approved destination.
   Validate incoming tenant/team/channel fields against those fixed values
   before posting. Never select a destination or callback URL from card data.

Trigger schema:

```json
{
  "type": "object",
  "required": ["runId", "approvalId", "artifactId", "artifactVersion",
               "tenantId", "teamId", "channelId", "card"],
  "properties": {
    "runId": {"type": "string"},
    "approvalId": {"type": "string"},
    "artifactId": {"type": "string"},
    "artifactVersion": {"type": "string"},
    "tenantId": {"type": "string"},
    "teamId": {"type": "string"},
    "channelId": {"type": "string"},
    "card": {"type": "object"}
  }
}
```

### Card and callback

6. Add **Post adaptive card and wait for a response**, select your fixed
   Team/Channel, and use the incoming `card` as Message/Adaptive Card. If the
   designer requires a string, use `string(triggerBody()?['card'])`.
7. The card includes full artifact text. Approve submits immediately. Reject
   opens a required-comment form with **Send rejection**. Backend validation
   also requires a nonblank comment: client validation alone is not trusted.
8. Add an **HTTP POST** to a fixed approved HTTPS URI:
   `https://YOUR_APPROVED_HOST/api/teams/decisions`. Do not take this URI from
   the trigger or card. Add `Content-Type: application/json` and
   `Authorization: Bearer <secret from your secure Flow configuration>`.
   Enable Secure Inputs/Outputs on actions containing secrets and callback
   content; do not export/run-history-share credentials.
9. Build the callback body according to this contract:

```json
{
  "actor": {
    "tenantId": "FIXED_FLOW_TENANT_UUID",
    "teamId": "FIXED_DESTINATION_TEAM_GROUP_UUID",
    "channelId": "FIXED_DESTINATION_CHANNEL_ID",
    "objectId": "RESPONDER_ENTRA_OBJECT_UUID_FROM_TEAMS_CONNECTOR"
  },
  "action": {
    "runId": "ORIGINAL_TRIGGER_RUN_ID",
    "approvalId": "ORIGINAL_TRIGGER_APPROVAL_ID",
    "decision": "APPROVED_OR_REJECTED_FROM_CARD_RESPONSE",
    "comment": "REJECTION_REASON_OR_OPTIONAL_APPROVAL_COMMENT"
  }
}
```

These are mapping placeholders, **not literal values to POST**:

| Callback field | Trusted source |
|---|---|
| actor tenant/team/channel | Fixed Flow destination settings, matching ASF config |
| actor objectId | Teams connector responder identity, not card input or display name |
| action runId/approvalId | Original HTTP trigger, not response-supplied IDs |
| action decision | Card response data `decision`, restricted to the supported enum |
| action comment | Response `rejectComment` for REJECTED, otherwise `comment` or empty |

Microsoft declares the action's outputs as **dynamic**. Select the responder's
Entra object ID from the connector's dynamic output in your tenant; do not
assume an undocumented JSON property path. If your connector exposes only a
responder email, resolve it through a trusted directory connector to an Entra
object ID. Never accept a free-text reviewer field as identity. Verify this
mapping in your tenant before any live approval is trusted.

10. Callback responses:
    - **200:** decision saved. ASF automatically dispatches the next step or
      revision; do not have the Flow invoke agents itself.
    - **403 / 422:** unauthorized responder, missing feedback or invalid data.
      A wait-for-response card is single-use, so re-post a fresh copy of the
      original card in a bounded retry branch, with an appropriate user
      notification. Do not silently drop an invalid submission.
    - **409:** stale card / duplicate vote; stop this old Flow instance.
    - **410:** expired approval; stop this Flow instance.
    - **401 / 503:** authentication/configuration or paused ASF execution;
      alert the operator. Do not fabricate an approval success.
11. Preserve the same trigger IDs when retrying a callback after a transport
    failure. Core duplicate/stale checks prevent a second decision.

**Trust boundary:** ASF authenticates the Flow using its callback secret. It
does not verify a Microsoft user JWT itself. Reviewer identity is attested by
the trusted Flow, so Flow owners/connections and its responder mapping must be
secured. Anyone with the callback secret could forge a Flow attestation; rotate
it if exposed.

## 3. Run and verify

Offline tests, no credentials or real network needed:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\test_teams_approval.py tests\unit\test_teams_workflow.py tests\unit\test_teams_demo.py -q
```

After you finish Flow and HTTPS proxy setup:

```powershell
.\.venv\Scripts\python.exe -m asf.integrations.teams.demo --help
.\.venv\Scripts\python.exe -m asf.integrations.teams.demo --send
```

`--send` contacts the Flow/Teams, but uses deterministic model replies. The
demo uses real SpecAgent and PlanAgent classes, SQLite approvals, revision
feedback and the automatic dispatcher; it does not demonstrate LLM reasoning.
The listener is bound to `127.0.0.1:3978` behind your approved HTTPS proxy.
`GET /health` returns 503 if automatic execution is paused.

To actually use the existing Gemini gateway for SPEC revision and planning,
set `ASF_LIVE_GEMINI_MODEL` and `ASF_LIVE_GEMINI_API_KEY` through your existing
environment setup, then explicitly enable it:

```powershell
.\.venv\Scripts\python.exe -m asf.integrations.teams.demo --send --gemini --requirement "YOUR_REQUIREMENT"
```

This last command contacts **both** Power Automate/Teams and Gemini. It shares
one existing Gemini gateway/budget across SpecAgent and PlanAgent (12 total
attempts, 120s per attempt, at most two retries). Redacted model evidence goes
under ignored `.asf-evidence/`; execution/approval state goes under ignored
`artifacts/teams-workflow-demo.sqlite`.

The default flow is SPEC -> human approval -> PLAN -> completed. A rejection
passes the previous SPEC and feedback back to SpecAgent, creates SPEC v2 and a
fresh approval ID, and does not run PlanAgent until approval. The existing
three-revision safety limit remains; further rejection escalates for operator
review instead of creating an unlimited loop.

The HTTP host stays up after completion to safely reject duplicate callbacks.
Stop it with Ctrl+C. Offline demo runs can resume with `--run-id YOUR_RUN_ID`.
Old bot-demo databases use a different pinned workflow and are intentionally
not accepted as Workflows demo executions. Live Gemini resume is rejected to
avoid resetting the process-local request budget for the same run.

For the full configured agent chain, construct `TeamsWorkflow(config, engine)`
with your own registered agents/stores and host `create_app(workflow, run_id)`.
The pump continues through all configured non-approval steps, pauses at each
approval and uses the existing retry/Fix/escalation policies. It does not add
repository, sandbox, GitLab or CI implementations.

## Limits and failure behavior

- This remains Phase 6's **single-process, same-event-loop-thread** model.
  Synchronous agent/model calls can block the loop up to their configured
  timeouts; no multi-worker/HA scheduling is claimed.
- Workflow URL is env-only and host-pinned. The existing bounded urllib
  transport is reused; no redirects or automatic delivery retries. Outbound
  responses are bounded to 4096 bytes; remote messages/URLs are never echoed.
- Only full rendered artifacts are sent; cards above 28,000 UTF-8 bytes fail
  explicitly, never truncate a SPEC and ask approval for a hidden remainder.
- Outbound 2xx means the Flow accepted the request, **not** that Teams rendered
  a card. Check Flow run failures and configure failure notifications.
- Delivery failure pauses automatic dispatch; inspect `/health` and safe logs,
  fix the Flow/network setup and restart explicitly. No silent retries.
- Delivery correlation is process-local: restarting may send a duplicate card.
  Core decisions and exact approval ID checks are durable/transactional;
  Teams delivery is at-least-once, not exactly-once.
- Multi-reviewer quorum remains enforced. After a successful partial approval,
  ASF sends a fresh single-response card for remaining reviewers. Repeated
  votes cannot satisfy quorum.
- Known configured workflow/callback secrets are blocked from outgoing cards
  and decision feedback. General artifact/comment content is application data,
  not universally secret-free; do not submit credentials, and protect Teams,
  Flow run history and the unencrypted SQLite database.
- TLS termination, caller rate limits, Flow licensing/DLP, directory identity
  mapping, owner/co-owner availability and deployment remain operator duties.

## Official references

- [Create adaptive card flows](https://learn.microsoft.com/en-us/power-automate/create-adaptive-cards)
- [Current Teams connector action](https://learn.microsoft.com/en-us/connectors/teams/#post-adaptive-card-and-wait-for-a-response)
- [HTTP trigger authentication modes](https://learn.microsoft.com/en-us/power-automate/oauth-authentication)
- [Trigger URL changes](https://learn.microsoft.com/en-us/troubleshoot/power-platform/power-automate/flow-run-issues/triggers-troubleshoot#changes-to-http-or-teams-webhook-trigger-flows)
- [Power Automate limits](https://learn.microsoft.com/en-us/power-automate/limits-and-config)

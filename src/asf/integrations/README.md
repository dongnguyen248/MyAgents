# src/asf/integrations/

Adapters to external systems (ports & adapters). The core and agents depend on **interfaces in `contracts/`**; each folder here provides one concrete adapter.

```text
Approval Service -> Notification/Approval channel -> Teams | Slack | Email
Git Service      -> GitLab | GitHub | Azure DevOps
CI Service       -> GitLab CI | GitHub Actions | Jenkins
```

LLM provider adapters live in `src/asf/models/providers/`.
Adding a provider = adding an adapter folder; core code does not change.

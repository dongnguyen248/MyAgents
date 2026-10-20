# integrations/
Adapters to external systems (ports & adapters). The core and agents depend on **interfaces in `core/contracts/`**; each folder here provides one concrete adapter.

```text
Approval Service -> Notification/Approval channel -> Teams | Slack | Email
Git Service      -> GitLab | GitHub | Azure DevOps
LLM Service      -> OpenAI | Anthropic | Google | DeepSeek | local
```
Adding a provider = adding an adapter folder; core code does not change.

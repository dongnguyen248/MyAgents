# integrations/gitlab/
Adapter for the Git-hosting interface (GitLab / local GitLab): branches, merge requests, status. Replaceable by GitHub/Azure DevOps adapters.

Implemented as part of the provider-neutral hosting package:
`src/asf/integrations/hosting/` — see `ports.py` for the contract,
`gitlab.py` for this provider's adapter, `factory.py` for building a
provider from a project profile's repository URL, and `actions.py` for
the workflow's `run-pipeline` / `await-merge` handlers.

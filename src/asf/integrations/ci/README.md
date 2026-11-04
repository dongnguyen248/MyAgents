# integrations/ci/
Adapter for CI pipeline triggering and result retrieval (provider-neutral interface).

Implemented as part of the hosting package:
`src/asf/integrations/hosting/` — pipelines are the provider's own (a
push triggers GitLab CI / GitHub Actions when the project repo carries
`.gitlab-ci.yml` / `.github/workflows`); the hosting adapters read the
latest pipeline status for the run's branch and the workflow's
`run-pipeline` action gates on it.

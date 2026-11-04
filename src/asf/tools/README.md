# tools/

**Responsibility:** Tool declarations and execution adapters used by agents through contracts.

`ports.py` declares the `RepositoryPort` / `SandboxPort` contracts and
`changeset.py` the change-set model. `fake.py` holds the in-memory /
scripted implementations used by tests and by demo projects without a
local folder. `local.py` holds the real local-workspace adapters: a
project whose profile sets `repository.path` gets filesystem-backed
repository reads, change sets written into that folder, and test
commands executed there for real (a trusted local workspace, not an
isolation sandbox).

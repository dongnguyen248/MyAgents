# src/asf/configuration/
**Responsibility:** configuration models and loaders.

Layers (later overrides earlier): global -> project (`projects/*.yaml`) -> workflow -> agent.
No secrets in files; reference environment/secret-manager keys instead.

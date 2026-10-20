# Configuration Subsystem (`src/asf/configuration/`)

**Responsibility:** Typed configuration models, strict loaders, secret reference resolution, and error translation.

## Configuration Layers

Platform configuration is resolved hierarchically across layers (lowest to highest priority):
1. **Built-in model defaults:** Declared on Pydantic field definitions (`PlatformConfig` and sub-models). A defaults-only configuration validates cleanly without any configuration files.
2. `<config_dir>/platform.yaml` *(optional)*: Base system and integration settings.
3. `<config_dir>/platform.local.yaml` *(optional)*: Local environment overrides, ignored by git.

### Merging Semantics
- **Mappings (dictionaries):** Merged recursively at any depth.
- **Lists and scalars:** Overwritten entirely by the higher-priority layer (including `null`).

## Configuration Directory Resolution

The platform config directory `<config_dir>` is resolved with the following precedence:
1. **Explicit argument:** `load_platform_config(config_dir=...)`. Must exist and be a valid directory, else `ConfigError`.
2. **Environment variable:** `ASF_CONFIG_DIR` read from the injected `environ` mapping. Must exist, else `ConfigError`.
3. **Default directory:** `./config`. If missing, the platform silently falls back to built-in model defaults.

*Note:* Environment variables are read only through injectable mapping parameters (defaulting to `os.environ`); runtime code and tests never mutate `os.environ`.

## Secret References (Zero Secrets in Config)

Credentials and sensitive tokens must never appear as literal values in configuration files or code.
- Credential fields and secret-like keys (matching case-insensitively the regex `(secret|token|password|passwd|api[_-]?key|credentials?)$`) must be either `null` or an explicit reference:
  ```yaml
  credentials:
    env: MODEL_PROVIDER_API_KEY
  ```
- **Deferred Resolution:** Secrets are not resolved during configuration loading. Adapters resolve `SecretRef.resolve(environ)` at the point of use.
- **Leak Prevention:** `SecretRef.__repr__`, `SecretRef.__str__`, Pydantic JSON dumps (`model_dump()`), and error messages output only the variable name, never the resolved secret value.
- Non-secret fields with similar prefixes (e.g. `max_tokens`) are accepted as regular integer/scalar parameters.

## Project Profiles & Contract Mapping

Project configurations reside in `projects/<id>.yaml`. Each profile maps 1:1 to the `Project` data contract (`contracts/schemas/contracts.schema.json`):

| Project Contract Field | Type | YAML Field in `projects/*.yaml` | Default if Absent | Description |
|---|---|---|---|---|
| `id` | `string` | `id` | File stem (e.g. `sample` for `sample.yaml`) | Unique project identifier |
| `name` | `string` | `name` | *(required)* | Human-readable project display name |
| `description` | `string` | `description` | `""` | Optional project summary |
| `repository` | `object` | `repository` | *(required)* | Repository provider and metadata |
| `technology` | `object` | `technology` | *(required)* | Technology stack (backend, frontend) |
| `workflow` | `string` | `workflow` | *(required)* | Target workflow definition ID |
| `enabledAgents` | `array[str]` | `enabledAgents` | `[]` | List of enabled agent identifiers |
| `enabledSkills` | `array[str]` | `enabledSkills` | `[]` | List of enabled skill packages |
| `configuration` | `object` | `configuration` | `{}` | Extensible project settings (e.g. approval channel) |
| `status` | `enum` | `status` | `"ACTIVE"` | Lifecycle status (`ACTIVE`, `INACTIVE`, `ARCHIVED`) |

### Scope Boundary
- **Per-project overrides:** Project-level overrides of global platform settings (e.g. overriding platform log level or global model profile definitions per project) are explicitly out of scope.
- `ProjectProfile.configuration` is an open pass-through dictionary for project-specific metadata (such as approval notification channels).

## Error Mapping & Diagnostics

All configuration errors raise `ConfigError` containing a tuple of `ConfigIssue(path, message)` and optional `source`:
- **Dotted Paths:** Hierarchical error locations are reported in dotted notation (e.g. `models.profiles.fast.timeoutSeconds`).
- **Duplicate Keys & Root Structure:** Duplicate mapping keys or non-mapping YAML roots are rejected immediately.
- **PlatformError Contract:** `ConfigError.to_platform_errors(now=None)` converts configuration errors into dictionaries conforming to the `PlatformError` contract (`code: "VALIDATION_FAILED"`, `category: "VALIDATION"`, `retryable: false`).

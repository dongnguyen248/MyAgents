# models/

**Responsibility:** Model gateway port, error taxonomy, and testing implementations for language model interactions.

## Architecture

Platform components and agents never communicate directly with external model APIs. Instead, they depend exclusively on the `ModelGateway` port.

### Components

1. **`ModelGateway` (`ports.py`):**
   Protocol declaring the asynchronous or synchronous model completion interface:
   `complete(request: ModelRequest) -> ModelResponse`

2. **`ScriptedModelGateway` (`fake.py`):**
   In-memory, deterministic fake implementation for unit tests and local execution:
   - Plays back a sequence of scripted items (`str`, `ModelResponse`, `ModelGatewayError`, or `Exception`).
   - Records deep copies of all requests in `.requests`.
   - Raises `RuntimeError("script exhausted")` when script items are exhausted.
   - Contains no latency, no sleeping, and no clock access.

3. **Model Errors (`errors.py`):**
   Standardized `ModelGatewayError(code, message, *, details=None)` matching catalog error codes:
   - `LLM_TIMEOUT` (category `LLM`, retryable `True`)
   - `LLM_RATE_LIMITED` (category `LLM`, retryable `True`)
   - `LLM_INVALID_RESPONSE` (category `LLM`, retryable `True`)
   - `INTEGRATION_UNAVAILABLE` (category `INTEGRATION`, retryable `True`)
   - `to_platform_error(now: datetime)` converts error to `PlatformError` contract dictionary.


### Providers (Future Phase)

Concrete provider adapters (such as remote model endpoints or local model runners) will reside under `asf.models.providers/` in Phase 6+. Agents remain completely agnostic of underlying providers.

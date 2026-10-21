# models/

**Responsibility:** Model gateway port, error taxonomy, and testing implementations for language model interactions.

## Architecture

Platform components and agents never communicate directly with external model APIs. Instead, they depend exclusively on the `ModelGateway` port.

### Components

1. **`ModelGateway` (`ports.py`):**
   Protocol declaring the asynchronous or synchronous model completion interface:
   `complete(request: ModelRequest) -> ModelResponse`

2. **`ScriptedFakeModelGateway` (`fake.py`):**
   In-memory, deterministic fake implementation for unit tests and local execution:
   - Returns scripted responses based on matching prompts, regex patterns, or FIFO queues.
   - Records full call history (`calls`) for verification.
   - Supports simulated latency, token usage accounting, and simulated failure injection.

3. **Model Errors (`errors.py`):**
   Standardized hierarchy of model gateway exceptions:
   - `GatewayError` (base)
   - `GatewayTimeoutError`
   - `GatewayAuthError`
   - `GatewayRateLimitError`
   - `GatewayInvalidRequestError`
   - `GatewayContentFilterError`
   - `GatewayServiceUnavailableError`

### Providers (Future Phase)

Concrete provider adapters (such as remote model endpoints or local model runners) will reside under `asf.models.providers/` in Phase 6+. Agents remain completely agnostic of underlying providers.

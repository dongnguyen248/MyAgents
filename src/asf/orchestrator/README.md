# core/orchestrator/
**Responsibility:** the only component that sequences agents.

Future flow: receive task -> determine workflow -> dispatch agent -> wait for result -> request approval -> handle rejection -> continue.

Agents never call one another; they return artifacts to the orchestrator. Not implemented yet.

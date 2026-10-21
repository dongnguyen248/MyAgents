# src/asf/state_machine/

## Responsibility
The `asf.state_machine` module provides the pure state machine logic, stage generation, and lifecycle transition functions for workflows. It defines how execution moves through generated stages and maps fine-grained stages to coarse task and run statuses.

## Purity Guarantee
The state machine is **100% pure**:
- No filesystem I/O (`open` is forbidden).
- No network, sockets, HTTP requests, or subprocesses.
- No environment access (`os.environ` is forbidden).
- No random numbers.
- No clock calls during state transitions (`apply` is a deterministic mathematical function; same inputs always produce identical outputs).
- Timestamps in `InvalidTransition.to_platform_error` accept an explicit `now` parameter or an injectable UTC default evaluated only upon error serialization.

## Public API

### Enums & Types
- `Trigger(StrEnum)`: `START`, `COMPLETE`, `APPROVED`, `REJECTED`, `REQUEST_CHANGES`, `ADVANCE`, `REVISE`, `RESUME`, `FAIL`, `CANCEL`.
- `StageKind(StrEnum)`: `INITIAL`, `DRAFT`, `REVIEW`, `REJECTED`, `APPROVED`, `ESCALATED`, `STEP`, `COMPLETED`, `FAILED`, `CANCELLED`.
- `StageInfo(frozen dataclass)`: `name: str`, `kind: StageKind`, `step_id: str | None`.
- `Edge(frozen dataclass)`: `source: str`, `trigger: Trigger`, `target: str`, `guard: Literal["none", "within_limit", "limit_reached"]`.
- `StageGraph(frozen dataclass)`: `stages: tuple[StageInfo, ...]`, `edges: tuple[Edge, ...]`, `max_revisions: Mapping[str, int]`.
- `RunState(frozen dataclass)`: `stage: str`, `revisions: Mapping[str, int]`. Created initially with `RunState.initial()`.

### Functions
- `build_graph(definition: WorkflowDefinition) -> StageGraph`: Constructs the generated stage graph and transition rules from a workflow definition.
- `apply(graph: StageGraph, state: RunState, trigger: str | Trigger) -> RunState`: Computes the next state deterministically. Neither the graph nor the input state is ever mutated.
- `allowed_triggers(graph: StageGraph, stage: str) -> tuple[str, ...]`: Returns the valid triggers from the given stage.
- `kind_of(graph: StageGraph, stage: str) -> StageKind`: Returns the category of the given stage.
- `task_status(graph: StageGraph, stage: str) -> str`: Maps a stage to its corresponding coarse `Task.status` (`NEW`, `IN_PROGRESS`, `WAITING`, `COMPLETED`, `FAILED`, `CANCELLED`).
- `run_status(graph: StageGraph, stage: str) -> str`: Maps a stage to its corresponding coarse `WorkflowRun.status` (`PENDING`, `RUNNING`, `WAITING`, `COMPLETED`, `FAILED`, `CANCELLED`).

### Exceptions
- `InvalidTransition(Exception)`: Raised when a trigger is invalid for the current stage, or when stage or trigger is unknown. Provides `.to_platform_error(now=None)` adhering to the `PlatformError` contract (`WORKFLOW_INVALID_TRANSITION`).

## How to Read a Graph
A `StageGraph` represents a finite state machine:
- `stages` are the vertices, each having a name, a stage kind, and an optional step identifier.
- `edges` are directed transitions `(source, trigger, target, guard)`.
- Revisions are tracked per step in `RunState.revisions`. Rejections trigger `REVISE`, which evaluates the guard: if below `maxRevisions`, it returns to draft; otherwise, it transitions to escalated rework.
- Terminal stages (`COMPLETED`, `FAILED`, `CANCELLED`) have zero outgoing transitions.

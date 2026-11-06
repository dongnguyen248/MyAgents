# harness/harness2/

A Harness²-style improvement loop for the ASF agents, re-implemented
natively on ASF ports (design record: `docs/architecture/harness2.md`).
**Implemented up to stage H3**: the harness is an addressable object
with a fingerprint (H1, runtime side in `src/asf/agents/_shared/harness.py`),
the rollout plumbing plus a harness-sensitive offline demo exist
(H2), and the real improver plus the full Parallel/Sequential engine
are built (H3). Selection/reflection/library (H4) and the
run/judge/report CLI (H5) are **not** built yet. Google's Harness²
runtime is not integrated and is not a dependency; the method
(Propose–Probe–Compose, selection, reflection, per-domain library) is
re-implemented for ASF's single-shot agents.

The loop is offline and human-gated: it never rewrites tracked
source. Its output is a patch + report for a human to apply.

- `trigger.py` — the **trigger**, which is *not* the method:
  `ImprovementTrigger` protocol, `NullImprovementTrigger` (default,
  `available` is `False`, suggests nothing) and
  `MetricsImprovementTrigger` (deterministic threshold rules over a
  typed `MetricsOverview`: `healthScore < 70` → investigate the
  agent, `avgRevisions > 1.5` → tighten prompt/template,
  approval rates `< 0.5` → review artifact templates,
  `testPassRate < 0.8` → strengthen test generation). It only
  decides *which* agent deserves an improvement cycle.
  `default_trigger()` returns the null trigger.
- `surface.py` — the editable harness surface per agent: allowed and
  frozen paths, always-on character caps, tree validation.
- `bundle.py` — converts between an agent's repo files and a harness
  `Tree` (round-trip tested).
- `adapter.py` — the `TaskAdapter` protocol the loop drives an agent
  through (tasks, execution, trajectories, deliverables, scoring).
- `trajectory.py` — recording gateway decorator and the
  `[ACTION]/[OBSERVATION]/[ERROR]` trajectory renderer.
- `ledger.py` — rollout/session accounting with the Harness² budget
  identity (R = 4k rollouts, P = 3k improver sessions per task).
- `context.py` — the budgeted evidence digest builder with leak
  tripwires (scores and verdict artifacts never enter evidence).
- `improver.py` — the `ImproverPort` and the real `GatewayImprover`:
  renders a mission template, parses the reply's edit blocks with
  the agents' parser, one repair call on a malformed reply.
- `prompts.py` + `prompts/` — the improver mission templates
  (propose_inv, propose_dom, aggregate, compose_round), filled in a
  single pass and refused at load if they mention measurement.
- `recursion.py` — the full Parallel(k) / Sequential(k) engine:
  Stage retry/fallback (an improver error counts as a failed
  attempt), candidate notes fed to compositions as decisions, an
  optional bounded thread pool per phase.
- `demo.py` — the offline, harness-sensitive demo
  (`python -m harness.harness2 demo ...`): a request-aware fake
  gateway whose solver reply improves when the harness carries the
  marker line the scripted improver adds.

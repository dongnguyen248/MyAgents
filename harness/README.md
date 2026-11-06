# harness/
Offline evaluation and improvement of the agents. Separate from runtime `src/asf/evaluation/`.

- `evaluation/` — deterministic benchmark cases plus a runner that drives the
  real Spec -> Plan agents through the orchestrator with a scripted model
  gateway, auto-approves, and scores completion / artifacts / revisions.
  Run it with: `.venv/bin/python -m harness.evaluation.cli [--out report.json]`
- `optimization/` — configuration experiments executed as real orchestrator
  runs. Currently: a fix-cycle experiment comparing `CodeLoopPolicy`
  budgets (`max_fixes=0` vs `3`) on a review-fails-first code-loop scenario
  (`harness/optimization/experiments.py::run_fix_cycle_experiment`).
- `harness2/` — a Harness²-style improvement loop, re-implemented natively
  (design record: `docs/architecture/harness2.md`). **Implemented up to
  stage H2**: harness objects with fingerprints, rollout plumbing, and a
  harness-sensitive offline demo. The metrics **trigger** in
  `harness2/trigger.py` is not the method — it only decides which agent
  deserves an improvement cycle. The real improver (H3), selection /
  reflection / library (H4), and the run/judge/report CLI (H5) are not
  built yet. The loop is offline and human-gated: it never rewrites
  tracked source.

Everything under `harness/` is offline: no network, no secrets. The
Harness² loop's real runs (H3+) cost real model calls and are driven
explicitly from its CLI, never per production request.

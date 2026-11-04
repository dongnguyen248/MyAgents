# harness/
Offline evaluation and future self-improvement of the agents. Separate from runtime `core/evaluation/`.

- `evaluation/` — deterministic benchmark cases plus a runner that drives the
  real Spec -> Plan agents through the orchestrator with a scripted model
  gateway, auto-approves, and scores completion / artifacts / revisions.
  Run it with: `.venv/bin/python -m harness.evaluation.cli [--out report.json]`
- `optimization/` — configuration experiments executed as real orchestrator
  runs. Currently: a fix-cycle experiment comparing `CodeLoopPolicy`
  budgets (`max_fixes=0` vs `3`) on a review-fails-first code-loop scenario
  (`harness/optimization/experiments.py::run_fix_cycle_experiment`).
- `harness2/` — the Harness² adapter seam. Google Harness² is **not**
  integrated and nothing here makes network calls; the default adapter is
  the null adapter (off), and a deterministic local rules adapter is
  provided for offline use.

Everything under `harness/` is offline and deterministic: no network, no
real LLM calls, no secrets.

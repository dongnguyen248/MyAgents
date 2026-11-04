# harness/evaluation/
Benchmark cases, datasets and scoring for agent quality.

- `cases.py` — `BenchmarkCase` (`id`, `requirement`, `expected_artifacts`,
  `max_revisions`, `must_complete`) and `load_cases(directory)` reading
  `*.json` files.
- `cases/` — deterministic benchmark cases (calculator, todo API, invoice
  service), each expecting `["SPEC", "PLAN"]`.
- `runner.py` — `EvaluationRunner` builds an `Orchestrator` with the real
  SpecAgent + PlanAgent (scripted model gateway with canned SPEC/PLAN
  replies), an in-memory approval service, a fixed stepping clock and
  sequential ids. It auto-approves every pending approval and scores each
  case: completion 0.5, expected artifacts 0.3, within `max_revisions` 0.2.
  `run_all` aggregates a `Report` (`mean_score`, `pass_rate`).
- `cli.py` — run all cases:

  ```bash
  .venv/bin/python -m harness.evaluation.cli [--cases DIR] [--out report.json]
  ```

  Prints one line per case plus a summary, writes the JSON report when
  `--out` is given, and exits 0 only if every case passes.

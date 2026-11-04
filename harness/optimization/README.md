# harness/optimization/
Experiments on prompt, skill, tool-guidance and agent-configuration optimization.

## Fix-cycle experiment (`experiments.py`)

`run_fix_cycle_experiment()` compares `CodeLoopPolicy` fix budgets on a
deterministic code-loop scenario executed end-to-end through the real
orchestrator and agents (Spec -> Plan -> Task -> Implement -> Review ->
Test/Fix): the first code review always requests changes, so the run can
only complete if the fix budget lets the FixAgent repair the code.

- `max_fixes=0` — escalates at `CODE_FIX_ESCALATED`, FixAgent never runs.
- `max_fixes=3` — completes after exactly one fix cycle.

The result reports, per configuration, completion, fix cycles used,
revisions and score, plus a declared winner with a one-line rationale.
Design choice: the full code loop is exercised directly (rather than the
lighter spec/plan revision fallback) because it is the configuration knob
with a real, measurable effect on run outcomes.

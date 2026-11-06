"""CLI for the Harness² loop: `python -m harness.harness2 {run,judge,report,demo}`.

Only `demo` is implemented in H2 (offline, scripted improver, fake
solver). `run` arrives with the real improver in H3/H5, `judge` and
`report` with the judge port in H5; until then they say so and exit
non-zero rather than pretending.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from harness.harness2.demo import SOLVER_MARKER, DemoOptions, run_demo
from harness.harness2.ledger import expected_rollouts, expected_sessions

__all__ = ["main"]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harness.harness2")
    subcommands = parser.add_subparsers(dest="command", required=True)
    demo = subcommands.add_parser("demo", help="offline harness-sensitive demo (H2)")
    demo.add_argument("--mode", choices=["parallel", "sequential"], default="parallel")
    demo.add_argument("--k", type=int, default=1)
    demo.add_argument("--agent", choices=["spec", "plan"], default="spec")
    demo.add_argument("--task", default="calculator")
    for name in ("run", "judge", "report"):
        subcommands.add_parser(name, help="not implemented yet (later stage)")
    return parser


def _run_demo(args: argparse.Namespace) -> int:
    options = DemoOptions(mode=args.mode, k=args.k, agent=args.agent, task_id=args.task)
    result = run_demo(options)
    run = result.run
    print(f"mode={run.mode} k={run.k} task={run.task_id} agent={args.agent}")
    print(
        f"rollouts: {len(run.ledger.rollouts)} (expected {expected_rollouts(run.k)})  "
        f"improver sessions: {len(run.ledger.sessions)} (expected {expected_sessions(run.k)})"
    )
    for final in run.finals:
        state = "delivered" if final.delivered else "not delivered"
        print(f"final {final.label}: {state}")
    if result.adopted is None:
        print("adopted edit: none (no delivered final)")
        return 1
    print(f"adopted edit ({result.adopted.label}):")
    for line in result.adopted_diff:
        print(f"  {line}")
    print(f"  + {SOLVER_MARKER}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "demo":
        return _run_demo(args)
    print(
        f"'{args.command}' is not implemented yet: the real improver lands in H3 "
        "and the run/judge/report CLI in H5 (docs/architecture/harness2.md).",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

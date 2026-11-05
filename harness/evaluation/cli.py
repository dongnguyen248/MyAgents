"""CLI: ``python -m harness.evaluation.cli [--cases DIR] [--out report.json]``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from harness.evaluation.cases import load_cases
from harness.evaluation.runner import EvaluationRunner

DEFAULT_CASES_DIR = Path(__file__).resolve().parent / "cases"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run offline ASF benchmark cases.")
    parser.add_argument(
        "--cases",
        type=Path,
        default=DEFAULT_CASES_DIR,
        help="Directory of benchmark case JSON files.",
    )
    parser.add_argument(
        "--out", type=Path, default=None, help="Write the JSON report to this path."
    )
    args = parser.parse_args(argv)

    cases = load_cases(args.cases)
    report = EvaluationRunner().run_all(cases)
    for result in report.results:
        status = "PASS" if result.passed else "FAIL"
        print(
            f"{result.case_id}: {status} score={result.score:.2f} "
            f"artifacts={','.join(result.artifacts_produced) or '-'} "
            f"revisions={result.revisions} duration={result.duration_seconds:.0f}s"
        )
        for failure in result.failures:
            print(f"  - {failure}")
    print(
        f"summary: {len(report.results)} cases, mean_score={report.mean_score:.2f}, "
        f"pass_rate={report.pass_rate:.2f}"
    )
    if args.out is not None:
        args.out.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return 0 if all(result.passed for result in report.results) else 1


if __name__ == "__main__":
    sys.exit(main())

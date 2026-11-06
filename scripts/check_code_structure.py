"""AST-based code-structure checker (stdlib only, deterministic).

Measures the Appendix A numeric limits that Ruff cannot: function
code lines (blank lines, comment-only lines and the docstring are
excluded), plus parameters, nesting depth and cyclomatic complexity
per function; lines, public methods and ``self.<field>`` count per
class; non-blank lines per file; banner and numbered step comments.

With ``--baseline FILE`` the checker ratchets: a violation fails
only when it is new or worse than its baseline entry, so the
baseline file must only ever shrink as refactors land.

Exit codes: 0 = no (new) violations, 1 = violations found,
2 = usage or baseline errors.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

MAX_FUNCTION_LINES = 30
MAX_FUNCTION_PARAMS = 4
MAX_FUNCTION_NESTING = 3
MAX_FUNCTION_COMPLEXITY = 10
MAX_CLASS_LINES = 300
MAX_CLASS_METHODS = 10
MAX_CLASS_FIELDS = 7
MAX_FILE_LINES = 500

BANNER_PATTERN = re.compile(r"^\s*#.*[-=*_~]{5,}")
NUMBERED_PATTERN = re.compile(r"^\s*#\s*\d+[.)]\s+\S")
NESTING_NODES = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith)
DECISION_NODES = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.IfExp)


@dataclass(frozen=True)
class Violation:
    file: str
    symbol: str
    rule: str
    measured: int
    limit: int

    def key(self) -> tuple[str, str, str]:
        return (self.file, self.symbol, self.rule)

    def describe(self) -> str:
        return f"{self.file} {self.symbol} {self.rule}: {self.measured} > {self.limit}"


@dataclass
class FunctionMetrics:
    params: int = 0
    code_lines: int = 0
    nesting: int = 0
    complexity: int = 1


def is_stub_body(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    if len(node.body) != 1:
        return False
    statement = node.body[0]
    if isinstance(statement, ast.Pass):
        return True
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and statement.value.value is Ellipsis
    )


def docstring_span(node: ast.FunctionDef | ast.AsyncFunctionDef) -> range:
    if not node.body:
        return range(0)
    first = node.body[0]
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        return range(first.lineno, (first.end_lineno or first.lineno) + 1)
    return range(0)


def count_code_lines(node: ast.FunctionDef | ast.AsyncFunctionDef, source_lines: list[str]) -> int:
    skipped = docstring_span(node)
    total = 0
    for lineno in range(node.lineno, (node.end_lineno or node.lineno) + 1):
        if lineno in skipped:
            continue
        text = source_lines[lineno - 1].strip()
        if text and not text.startswith("#"):
            total += 1
    return total


def count_params(node: ast.FunctionDef | ast.AsyncFunctionDef, is_method: bool) -> int:
    args = node.args
    total = len(args.args) + len(args.kwonlyargs)
    total += 1 if args.vararg is not None else 0
    total += 1 if args.kwarg is not None else 0
    if is_method and args.args:
        total -= 1
    return total


def nesting_depth(node: ast.AST, depth: int = 0) -> int:
    deepest = depth
    for child in ast.iter_child_nodes(node):
        child_depth = depth + 1 if isinstance(child, NESTING_NODES) else depth
        deepest = max(deepest, nesting_depth(child, child_depth))
    return deepest


def cyclomatic_complexity(node: ast.AST) -> int:
    total = 1
    for child in ast.walk(node):
        if isinstance(child, DECISION_NODES):
            total += 1
        elif isinstance(child, ast.BoolOp):
            total += len(child.values) - 1
        elif isinstance(child, ast.comprehension):
            total += 1 + len(child.ifs)
        elif isinstance(child, ast.Match):
            total += len(child.cases)
    return total


def measure_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    source_lines: list[str],
    is_method: bool,
) -> FunctionMetrics:
    return FunctionMetrics(
        params=count_params(node, is_method),
        code_lines=count_code_lines(node, source_lines),
        nesting=nesting_depth(node),
        complexity=cyclomatic_complexity(node),
    )


def function_violations(file: str, symbol: str, metrics: FunctionMetrics) -> list[Violation]:
    checks = [
        ("function-lines", metrics.code_lines, MAX_FUNCTION_LINES),
        ("function-params", metrics.params, MAX_FUNCTION_PARAMS),
        ("function-nesting", metrics.nesting, MAX_FUNCTION_NESTING),
        ("function-complexity", metrics.complexity, MAX_FUNCTION_COMPLEXITY),
    ]
    return [
        Violation(file, symbol, rule, measured, limit)
        for rule, measured, limit in checks
        if measured > limit
    ]


def class_fields(node: ast.ClassDef) -> set[str]:
    fields: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Attribute):
            continue
        if isinstance(child.value, ast.Name) and child.value.id == "self":
            if isinstance(child.ctx, ast.Store):
                fields.add(child.attr)
    return fields


def class_violations(file: str, node: ast.ClassDef) -> list[Violation]:
    lines = (node.end_lineno or node.lineno) - node.lineno + 1
    methods = sum(
        1
        for child in node.body
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not child.name.startswith("_")
    )
    checks = [
        ("class-lines", lines, MAX_CLASS_LINES),
        ("class-methods", methods, MAX_CLASS_METHODS),
        ("class-fields", len(class_fields(node)), MAX_CLASS_FIELDS),
    ]
    return [
        Violation(file, node.name, rule, measured, limit)
        for rule, measured, limit in checks
        if measured > limit
    ]


@dataclass
class FileReport:
    violations: list[Violation] = field(default_factory=list)


def check_comments(file: str, source_lines: list[str]) -> list[Violation]:
    banners = sum(1 for line in source_lines if BANNER_PATTERN.match(line))
    numbered = sum(1 for line in source_lines if NUMBERED_PATTERN.match(line))
    found = []
    if banners:
        found.append(Violation(file, "", "banner-comment", banners, 0))
    if numbered:
        found.append(Violation(file, "", "numbered-comment", numbered, 0))
    return found


def check_tree(tree: ast.Module, file: str, source_lines: list[str]) -> list[Violation]:
    found: list[Violation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            found.extend(class_violations(file, node))
    for node, symbol, is_method in iter_functions(tree):
        if is_stub_body(node):
            continue
        metrics = measure_function(node, source_lines, is_method)
        found.extend(function_violations(file, symbol, metrics))
    return found


def iter_functions(
    tree: ast.Module,
) -> list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, str, bool]]:
    found = []

    def visit(node: ast.AST, prefix: str, in_class: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                visit(child, f"{prefix}{child.name}.", True)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found.append((child, f"{prefix}{child.name}", in_class))
                visit(child, f"{prefix}{child.name}.", False)
            else:
                visit(child, prefix, in_class)

    visit(tree, "", False)
    return found


def display_path(path: Path) -> str:
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.name


def check_file(path: Path) -> list[Violation]:
    text = path.read_text(encoding="utf-8")
    source_lines = text.splitlines()
    relative = display_path(path)
    found = check_comments(relative, source_lines)
    non_blank = sum(1 for line in source_lines if line.strip())
    if non_blank > MAX_FILE_LINES:
        found.append(Violation(relative, "", "file-lines", non_blank, MAX_FILE_LINES))
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return found
    found.extend(check_tree(tree, relative, source_lines))
    return found


def collect(roots: list[Path]) -> list[Violation]:
    found: list[Violation] = []
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            found.extend(check_file(path))
    return sorted(found, key=lambda v: (v.file, v.symbol, v.rule))


def baseline_entries(violations: list[Violation]) -> list[dict[str, object]]:
    return [
        {
            "file": v.file,
            "symbol": v.symbol,
            "rule": v.rule,
            "measured": v.measured,
            "limit": v.limit,
        }
        for v in violations
    ]


def load_baseline(path: Path) -> dict[tuple[str, str, str], int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        (entry["file"], entry["symbol"], entry["rule"]): int(entry["measured"])
        for entry in data["violations"]
    }


def new_or_worse(
    violations: list[Violation], baseline: dict[tuple[str, str, str], int]
) -> list[Violation]:
    failing = []
    for violation in violations:
        allowed = baseline.get(violation.key())
        if allowed is None or violation.measured > allowed:
            failing.append(violation)
    return failing


def parse_args(argv: list[str]) -> tuple[list[Path], Path | None, Path | None]:
    roots: list[Path] = []
    baseline: Path | None = None
    write_baseline: Path | None = None
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--baseline":
            baseline = Path(argv[index + 1])
            index += 2
        elif arg == "--write-baseline":
            write_baseline = Path(argv[index + 1])
            index += 2
        else:
            roots.append(Path(arg))
            index += 1
    return (roots or [Path("src"), Path("harness")]), baseline, write_baseline


def main(argv: list[str] | None = None) -> int:
    roots, baseline_path, write_path = parse_args(argv or [])
    violations = collect(roots)
    if write_path is not None:
        payload = {"violations": baseline_entries(violations)}
        write_path.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
        print(f"baseline written: {len(violations)} violations -> {write_path}")
        return 0
    if baseline_path is not None:
        failing = new_or_worse(violations, load_baseline(baseline_path))
    else:
        failing = violations
    for violation in failing:
        print(violation.describe())
    print(f"{len(failing)} violation(s), {len(violations)} total measured")
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

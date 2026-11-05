"""CLI commands and diagnostic utilities.

The console entry point: ``asf --version`` prints the installed
package version and ``asf serve`` runs the demo API server (the
same entry the module form ``python -m asf.api.demo`` uses — all
of its flags, such as ``--port``/``--db``/``--mariadb``/
``--selftest``, are passed through). Serving needs the ``api``
extra.
"""

from __future__ import annotations

import sys
from importlib.metadata import PackageNotFoundError, version

__all__ = ["main"]


def _package_version() -> str:
    try:
        return version("ai-software-agents")
    except PackageNotFoundError:
        return "0.1.0"


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("--version", "-V"):
        print(f"asf {_package_version()}")
        return
    if args and args[0] == "serve":
        # Hand the remaining arguments to the demo server's own
        # argument parser untouched.
        sys.argv = [sys.argv[0], *args[1:]]
        from asf.api.demo import main as demo_main

        demo_main()
        return
    print("usage: asf [--version] | serve [demo options]", file=sys.stderr)
    raise SystemExit(2)

"""The ``asf`` console entry point (packaging, Prompt 9 item 2)."""

from __future__ import annotations

import pytest

from asf.cli import main


def test_cli_version(capsys: pytest.CaptureFixture[str]) -> None:
    main(["--version"])
    out = capsys.readouterr().out
    assert out.startswith("asf ")
    assert out.strip() != "asf"


def test_cli_unknown_command_exits_with_usage(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["frobnicate"])
    assert excinfo.value.code == 2
    assert "usage:" in capsys.readouterr().err

"""LocalSandbox hardening: environment isolation, process-tree
timeouts, streamed output caps, and POSIX resource limits.

All commands are `python -c` one-liners — no external toolchain is
involved. POSIX-only assertions are skipped on Windows with reasons;
the tree-kill on Windows goes through taskkill and is exercised by
the timing assertions there.
"""

from __future__ import annotations

import contextlib
import os
import sys
import time
from pathlib import Path

import pytest

from asf.tools.changeset import ChangeSet, FileChange
from asf.tools.local import (
    LocalSandbox,
    LocalWorkspace,
    SandboxResourceLimits,
    SandboxSettings,
    WorkspaceSandbox,
    build_sandbox_env,
)
from asf.tools.ports import CommandSpec, SandboxError

PYTHON = sys.executable


def _run(sandbox: LocalSandbox, *specs: CommandSpec):  # noqa: ANN202
    # ChangeSet requires at least one change; a unique marker file is
    # the least intrusive way to run commands against a tree.
    marker = ChangeSet(
        changes=[
            FileChange(
                path=f".sandbox-marker-{os.urandom(4).hex()}",
                operation="create",
                content="",
            ),
        ]
    )
    return sandbox.run(list(specs), marker, "main").commands


POSIX_ONLY = pytest.mark.skipif(
    os.name != "posix",
    reason="process-group/rlimit semantics are POSIX-only",
)


# -- build_sandbox_env (pure policy) ------------------------------------


def test_build_sandbox_env_keeps_only_the_minimal_set():
    base = {
        "PATH": "/usr/bin",
        "LANG": "en_US.UTF-8",
        "LC_ALL": "C",
        "TMPDIR": "/tmp",
        "HOME": "/real/home",
        "RANDOM_TOOL_STATE": "x",
        "JAVA_HOME": "/opt/jdk",
    }
    env = build_sandbox_env(base, (), {}, home="/run/home")
    assert env["PATH"] == "/usr/bin"
    assert env["LANG"] == "en_US.UTF-8"
    assert env["TMPDIR"] == "/tmp"
    assert env["HOME"] == "/run/home"  # never the real home
    assert "RANDOM_TOOL_STATE" not in env
    assert "JAVA_HOME" not in env  # toolchain vars need the allowlist


def test_build_sandbox_env_allowlist_and_extra():
    base = {"PATH": "/usr/bin", "JAVA_HOME": "/opt/jdk", "NODE_PATH": "/n"}
    env = build_sandbox_env(
        base,
        ("JAVA_HOME",),
        {"CI_FLAG": "1", "PATH": "/custom"},
        home="/run/home",
    )
    assert env["JAVA_HOME"] == "/opt/jdk"
    assert "NODE_PATH" not in env
    assert env["CI_FLAG"] == "1"
    assert env["PATH"] == "/custom"  # extra wins over inherited


def test_build_sandbox_env_never_passes_asf_prefixed_names():
    base = {
        "PATH": "/usr/bin",
        "ASF_MARIADB_PASSWORD": "pw",
        "ASF_GITHUB_TOKEN": "tok",
        "asf_lowercase": "x",
    }
    env = build_sandbox_env(
        base,
        ("ASF_MARIADB_PASSWORD",),  # even when allowlisted
        {"ASF_DECLARED": "y"},  # even when declared in testEnv
        home="/run/home",
    )
    assert not any(name.upper().startswith("ASF_") for name in env)
    assert env["PATH"] == "/usr/bin"


def test_build_sandbox_env_rejects_invalid_names():
    with pytest.raises(ValueError):
        build_sandbox_env({}, ("NOT A NAME",), {}, home="/h")
    with pytest.raises(ValueError):
        build_sandbox_env({}, (), {"1BAD": "x"}, home="/h")


# -- environment isolation end to end ------------------------------------


def test_backend_secrets_do_not_reach_commands(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ASF_SECRET_TEST", "s3cr3t-value")
    monkeypatch.setenv("UNRELATED_BACKEND_VAR", "also-hidden")
    sandbox = LocalSandbox(tmp_path)  # reads the real process env
    (result,) = _run(
        sandbox,
        CommandSpec(
            argv=(
                PYTHON,
                "-c",
                "import os; print(os.environ.get('ASF_SECRET_TEST'));"
                " print(os.environ.get('UNRELATED_BACKEND_VAR'));"
                " print('PATH' in os.environ);"
                " print(os.path.isdir(os.environ['HOME']));"
                " print(os.environ['HOME'])",
            )
        ),
    )
    lines = result.stdout.strip().splitlines()
    assert lines[0] == "None"  # the ASF_ secret is gone
    assert lines[1] == "None"  # and so is everything not allowlisted
    assert lines[2] == "True"  # PATH survives: tools still run
    assert lines[3] == "True"  # HOME exists during the run...
    home = Path(lines[4])
    assert home != Path.home()  # ...but is the per-run temp dir
    assert home.parent == Path("/tmp") or "asf-sandbox-" in home.name


def test_project_settings_reach_commands_through_the_workspace(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ASF_SECRET_TEST", "s3cr3t-value")
    monkeypatch.setenv("MY_TOOL_HOME", "/opt/tool")
    workspace = LocalWorkspace(
        {"proj": tmp_path},
        sandbox_settings={
            "proj": SandboxSettings(
                env_allowlist=("MY_TOOL_HOME",),
                env_extra={"PROJECT_FLAG": "on"},
            )
        },
    )
    sandbox = WorkspaceSandbox(workspace, fallback=None)  # type: ignore[arg-type]
    workspace.bind("proj")
    (result,) = _run(
        sandbox,
        CommandSpec(
            argv=(
                PYTHON,
                "-c",
                "import os; print(os.environ.get('MY_TOOL_HOME'));"
                " print(os.environ.get('PROJECT_FLAG'));"
                " print(os.environ.get('ASF_SECRET_TEST'))",
            )
        ),
    )
    assert result.stdout.strip().splitlines() == ["/opt/tool", "on", "None"]


# -- timeouts kill the whole tree -----------------------------------------


_GRANDCHILD_PARENT = (
    "import subprocess, sys, time;"
    "child = subprocess.Popen([sys.executable, '-c',"
    " 'import time; time.sleep(60)']);"
    "open('grandchild.pid', 'w').write(str(child.pid));"
    "time.sleep(60)"
)


def test_timeout_kills_the_whole_process_tree(tmp_path: Path):
    sandbox = LocalSandbox(tmp_path)
    started = time.monotonic()
    (result,) = _run(
        sandbox,
        CommandSpec(
            argv=(PYTHON, "-c", _GRANDCHILD_PARENT),
            timeout_seconds=1,
        ),
    )
    elapsed = time.monotonic() - started
    # timeout (1s) + SIGTERM grace (3s) at the very worst — never the
    # 60s the tree wanted to live.
    assert elapsed < 1 + 5
    assert result.timed_out is True
    assert result.exit_code != 0
    assert 900 <= result.duration_ms < 6000


@POSIX_ONLY
def test_timeout_leaves_no_orphan_grandchild(tmp_path: Path):
    sandbox = LocalSandbox(tmp_path)
    (result,) = _run(
        sandbox,
        CommandSpec(
            argv=(PYTHON, "-c", _GRANDCHILD_PARENT),
            timeout_seconds=1,
        ),
    )
    assert result.timed_out is True
    pid = int((tmp_path / "grandchild.pid").read_text(encoding="utf-8"))
    # The grandchild may take a moment to actually exit after SIGKILL.
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail(f"grandchild {pid} survived the sandbox timeout")
    # It must also be reaped (a zombie still answers kill(pid, 0)).
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, 0)


def test_normal_command_reports_exit_code_duration_and_streams(tmp_path: Path):
    sandbox = LocalSandbox(tmp_path)
    (result,) = _run(
        sandbox,
        CommandSpec(
            argv=(
                PYTHON,
                "-c",
                "import sys; print('out'); print('err', file=sys.stderr); raise SystemExit(7)",
            )
        ),
    )
    assert result.exit_code == 7
    assert result.stdout.strip() == "out"
    assert result.stderr.strip() == "err"
    assert result.timed_out is False
    assert result.stdout_truncated is False
    assert result.duration_ms >= 0


# -- streamed output caps ---------------------------------------------------


def test_huge_output_is_capped_while_the_command_completes(tmp_path: Path):
    # 200MB through the pipe: the old capture_output design buffered
    # all of it in RAM. The reader must keep only the cap, keep
    # draining (or the writer blocks forever), and flag truncation.
    sandbox = LocalSandbox(tmp_path)
    (result,) = _run(
        sandbox,
        CommandSpec(
            argv=(
                PYTHON,
                "-c",
                "import sys; chunk = b'x' * 1_000_000\n"
                "for _ in range(200): sys.stdout.buffer.write(chunk)",
            ),
            timeout_seconds=120,
            output_limit_bytes=100_000,
        ),
    )
    assert result.exit_code == 0
    assert result.timed_out is False
    assert len(result.stdout.encode("utf-8")) <= 100_000
    assert result.stdout_truncated is True
    assert set(result.stdout) == {"x"}


def test_stderr_has_its_own_cap(tmp_path: Path):
    sandbox = LocalSandbox(tmp_path)
    (result,) = _run(
        sandbox,
        CommandSpec(
            argv=(PYTHON, "-c", "import sys; sys.stderr.write('e' * 5000); print('ok')"),
            output_limit_bytes=1000,
        ),
    )
    assert result.stdout.strip() == "ok"
    assert len(result.stderr) == 1000
    assert result.stderr_truncated is True
    assert result.stdout_truncated is False


# -- argv[0] validation -------------------------------------------------------


def test_relative_argv0_must_stay_inside_the_project(tmp_path: Path):
    sandbox = LocalSandbox(tmp_path)
    with pytest.raises(SandboxError):
        _run(sandbox, CommandSpec(argv=("../outside.py",)))
    with pytest.raises(SandboxError):
        _run(sandbox, CommandSpec(argv=("sub/../../outside.py",)))
    with pytest.raises(SandboxError):
        _run(sandbox, CommandSpec(argv=()))


def test_relative_argv0_inside_the_project_runs(tmp_path: Path):
    (tmp_path / "tool.py").write_text("print('from-tool')\n", encoding="utf-8")
    sandbox = LocalSandbox(tmp_path)
    (result,) = _run(sandbox, CommandSpec(argv=(PYTHON, "tool.py")))
    assert result.stdout.strip() == "from-tool"


@POSIX_ONLY
def test_relative_argv0_script_executes_directly(tmp_path: Path):
    script = tmp_path / "tool.py"
    script.write_text(
        "#!/usr/bin/env python3\nprint('direct')\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    sandbox = LocalSandbox(tmp_path)
    (result,) = _run(sandbox, CommandSpec(argv=("./tool.py",)))
    assert result.exit_code == 0
    assert result.stdout.strip() == "direct"


# -- POSIX resource limits ----------------------------------------------------


@POSIX_ONLY
def test_resource_limits_are_applied_to_the_child(tmp_path: Path):
    settings = SandboxSettings(
        resource_limits=SandboxResourceLimits(
            cpu_seconds=5,
            max_processes=7,
        )
    )
    sandbox = LocalSandbox(tmp_path, settings=settings)
    (result,) = _run(
        sandbox,
        CommandSpec(
            argv=(
                PYTHON,
                "-c",
                "import resource;"
                " print(resource.getrlimit(resource.RLIMIT_CPU)[0]);"
                " print(resource.getrlimit(resource.RLIMIT_NPROC)[0])",
            )
        ),
    )
    assert result.exit_code == 0
    assert result.stdout.strip().splitlines() == ["5", "7"]


@POSIX_ONLY
def test_cpu_limit_kills_a_busy_loop_before_the_timeout(tmp_path: Path):
    settings = SandboxSettings(
        resource_limits=SandboxResourceLimits(
            cpu_seconds=1,
        )
    )
    sandbox = LocalSandbox(tmp_path, settings=settings)
    started = time.monotonic()
    (result,) = _run(
        sandbox,
        CommandSpec(
            argv=(PYTHON, "-c", "while True: pass"),
            timeout_seconds=30,
        ),
    )
    elapsed = time.monotonic() - started
    assert elapsed < 10  # killed by SIGXCPU, not by the 30s timeout
    assert result.timed_out is False
    assert result.exit_code != 0


def test_no_limits_by_default(tmp_path: Path):
    sandbox = LocalSandbox(tmp_path)
    (result,) = _run(sandbox, CommandSpec(argv=(PYTHON, "-c", "print('fine')")))
    assert result.stdout.strip() == "fine"

"""MariaDB execution store: configuration (server tests are integrated)."""

from __future__ import annotations

import threading

import pytest

from asf.storage.mariadb import MariaDbConfig, MariaDbExecutionStore


def test_config_defaults(monkeypatch: pytest.MonkeyPatch):
    for key in (
        "ASF_MARIADB_HOST",
        "ASF_MARIADB_PORT",
        "ASF_MARIADB_USER",
        "ASF_MARIADB_PASSWORD",
        "ASF_MARIADB_DATABASE",
    ):
        monkeypatch.delenv(key, raising=False)
    config = MariaDbConfig.from_env()
    assert (config.host, config.port, config.user, config.database) == (
        "127.0.0.1",
        3306,
        "asf",
        "asf",
    )
    assert config.password == ""


def test_config_reads_the_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ASF_MARIADB_HOST", "db.internal")
    monkeypatch.setenv("ASF_MARIADB_PORT", "3307")
    monkeypatch.setenv("ASF_MARIADB_USER", "factory")
    monkeypatch.setenv("ASF_MARIADB_PASSWORD", "s3cret")
    monkeypatch.setenv("ASF_MARIADB_DATABASE", "factory_runs")
    config = MariaDbConfig.from_env()
    assert (config.host, config.port, config.user) == ("db.internal", 3307, "factory")
    assert config.password == "s3cret" and config.database == "factory_runs"


def test_store_rejects_an_unsafe_database_name():
    # The name is interpolated into CREATE DATABASE, so anything beyond
    # letters/digits/underscore is refused before any connection attempt.
    with pytest.raises(ValueError, match="Invalid MariaDB database name"):
        MariaDbExecutionStore(MariaDbConfig(database="asf; DROP TABLE x"))


class _FakeConnection:
    def __init__(self, *, ping_error: Exception | None = None) -> None:
        self.ping_error = ping_error
        self.pings = 0
        self.closed = False

    def ping(self, reconnect: bool = False) -> None:
        self.pings += 1
        if self.ping_error is not None:
            raise self.ping_error

    def close(self) -> None:
        self.closed = True


def _store_with_cached(connection: _FakeConnection) -> MariaDbExecutionStore:
    store = MariaDbExecutionStore.__new__(MariaDbExecutionStore)
    store._config = MariaDbConfig(database="asf")
    store._local = threading.local()
    store._local.connection = connection
    return store


def test_reused_connection_is_pinged_and_a_dead_one_replaced():
    fresh = _FakeConnection()
    dead = _FakeConnection(ping_error=RuntimeError("server has gone away"))
    store = _store_with_cached(dead)
    store._connect = lambda *, database: fresh  # type: ignore[method-assign]

    assert store._connection() is fresh
    assert dead.pings == 1 and dead.closed

    # A healthy cached connection is kept (ping succeeds, no swap).
    assert store._connection() is fresh
    assert fresh.pings == 1


def test_connection_is_not_pinged_inside_a_transaction():
    # A reconnect mid-transaction would silently lose it, so the
    # liveness check is skipped while one is open.
    dead = _FakeConnection(ping_error=RuntimeError("server has gone away"))
    store = _store_with_cached(dead)
    store._local.in_transaction = True
    assert store._connection() is dead
    assert dead.pings == 0

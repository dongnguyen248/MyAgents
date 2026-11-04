"""MariaDB execution store: configuration (server tests are integrated)."""

from __future__ import annotations

import pytest

from asf.storage.mariadb import MariaDbConfig, MariaDbExecutionStore


def test_config_defaults(monkeypatch: pytest.MonkeyPatch):
    for key in (
        "ASF_MARIADB_HOST", "ASF_MARIADB_PORT", "ASF_MARIADB_USER",
        "ASF_MARIADB_PASSWORD", "ASF_MARIADB_DATABASE",
    ):
        monkeypatch.delenv(key, raising=False)
    config = MariaDbConfig.from_env()
    assert (config.host, config.port, config.user, config.database) == (
        "127.0.0.1", 3306, "asf", "asf",
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

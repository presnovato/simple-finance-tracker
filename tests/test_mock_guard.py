import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from finance_bot.api.server import create_app
from finance_bot.config import RAILWAY_ENV_VARS
from tools import seed_mock_database
from tools._mock_guard import (
    MOCK_FLAG,
    MOCK_TOKEN,
    MockGuardError,
    check_mock_environment,
    require_mock_environment,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_settings(path: Path, value: str) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            "CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute("INSERT INTO settings VALUES ('mock_database', ?)", (value,))
        connection.commit()
    finally:
        connection.close()


class _MockAuth:
    def authenticate(self, _credential: str) -> dict:
        return {"id": 1}


def test_guard_accepts_safe_environment():
    assert check_mock_environment({MOCK_FLAG: "1", "BOT_TOKEN": MOCK_TOKEN}) == []


def test_guard_allows_empty_token():
    assert check_mock_environment({MOCK_FLAG: "1"}) == []


def test_guard_rejects_missing_flag():
    assert check_mock_environment({}) != []


def test_guard_rejects_railway_environment():
    problems = check_mock_environment({MOCK_FLAG: "1", "RAILWAY_PROJECT_ID": "x"})
    assert any("Railway" in problem for problem in problems)


def test_guard_rejects_production_token():
    problems = check_mock_environment(
        {MOCK_FLAG: "1", "BOT_TOKEN": "123456789:real-token"}
    )
    assert any("BOT_TOKEN" in problem for problem in problems)


def test_require_mock_environment_raises():
    with pytest.raises(MockGuardError):
        require_mock_environment({})


def test_reset_refuses_database_without_marker(tmp_path, monkeypatch):
    database = tmp_path / "finance.db"
    _write_settings(database, "0")
    monkeypatch.setattr(seed_mock_database, "DB_PATH", str(database))

    with pytest.raises(MockGuardError):
        seed_mock_database._reset_database_file()

    assert database.exists()


def test_reset_refuses_corrupt_file(tmp_path, monkeypatch):
    database = tmp_path / "finance.db"
    database.write_bytes(b"not a sqlite database")
    monkeypatch.setattr(seed_mock_database, "DB_PATH", str(database))

    with pytest.raises(MockGuardError):
        seed_mock_database._reset_database_file()

    assert database.exists()


def test_reset_deletes_marked_mock_database(tmp_path, monkeypatch):
    database = tmp_path / "finance.db"
    _write_settings(database, "1")
    monkeypatch.setattr(seed_mock_database, "DB_PATH", str(database))

    seed_mock_database._reset_database_file()

    assert not database.exists()


def test_create_app_rejects_mock_authenticator_on_railway(monkeypatch):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")

    with pytest.raises(RuntimeError, match="TelegramInitDataAuthenticator"):
        create_app(authenticator=_MockAuth())


def test_create_app_allows_mock_authenticator_off_railway(monkeypatch):
    for name in RAILWAY_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    app = create_app(authenticator=_MockAuth())

    assert app is not None


def test_compose_publishes_mock_port_on_localhost_only():
    text = (REPO_ROOT / "docker-compose.mock.yml").read_text(encoding="utf-8")

    assert '"127.0.0.1:${MOCK_TMA_PORT:-8080}:8080"' in text
    assert 'FINANCE_TRACKER_MOCK: "1"' in text
    assert 'MOCK_BIND_HOST: "0.0.0.0"' in text


def test_mock_server_refuses_production_like_environment():
    environment = dict(os.environ)
    environment.pop(MOCK_FLAG, None)
    environment["BOT_TOKEN"] = "123456789:real-token"

    result = subprocess.run(
        [sys.executable, "tools/mock_tma_server.py"],
        capture_output=True,
        text=True,
        env=environment,
        cwd=REPO_ROOT,
        timeout=60,
    )

    assert result.returncode == 2
    assert "Отказ" in result.stderr

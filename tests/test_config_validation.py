from finance_bot import config


def _make_valid(monkeypatch) -> None:
    monkeypatch.setattr(config, "BOT_TOKEN", "123456789:AA" + "x" * 35)
    monkeypatch.setattr(config, "ALLOWED_USER_ID", 42)
    monkeypatch.setattr(config, "TMA_URL", "https://example.up.railway.app")
    monkeypatch.setattr(config, "TIMEZONE", "Europe/Moscow")
    monkeypatch.setattr(config, "PRIMARY_MODEL", "vendor/primary")
    monkeypatch.setattr(config, "FALLBACK_MODEL", "vendor/fallback")


def test_validate_config_accepts_valid(monkeypatch):
    _make_valid(monkeypatch)
    assert config.validate_config() == []


def test_validate_config_allows_localhost_http(monkeypatch):
    _make_valid(monkeypatch)
    monkeypatch.setattr(config, "TMA_URL", "http://localhost:5173")
    assert config.validate_config() == []
    monkeypatch.setattr(config, "TMA_URL", "http://127.0.0.1:5173")
    assert config.validate_config() == []


def test_validate_config_reports_each_problem(monkeypatch):
    cases = (
        ("BOT_TOKEN", "", "BOT_TOKEN"),
        ("BOT_TOKEN", "not-a-token", "BOT_TOKEN"),
        ("ALLOWED_USER_ID", 0, "ALLOWED_USER_ID"),
        ("TMA_URL", "http://evil.example", "TMA_URL"),
        ("TIMEZONE", "Nowhere/Nothing", "TIMEZONE"),
        ("PRIMARY_MODEL", "   ", "PRIMARY_MODEL"),
        ("FALLBACK_MODEL", "", "FALLBACK_MODEL"),
    )
    for field, value, expected in cases:
        _make_valid(monkeypatch)
        monkeypatch.setattr(config, field, value)
        problems = config.validate_config()
        assert any(expected in problem for problem in problems), (field, problems)


def test_validate_config_reports_all_problems_at_once(monkeypatch):
    monkeypatch.setattr(config, "BOT_TOKEN", "")
    monkeypatch.setattr(config, "ALLOWED_USER_ID", 0)
    monkeypatch.setattr(config, "TMA_URL", "ftp://example")
    monkeypatch.setattr(config, "TIMEZONE", "Bad/Zone")
    monkeypatch.setattr(config, "PRIMARY_MODEL", "")
    monkeypatch.setattr(config, "FALLBACK_MODEL", "")

    assert len(config.validate_config()) == 6


def test_backup_retention_days_falls_back_to_default():
    assert config._backup_retention_days("7") == 7
    assert config._backup_retention_days("1") == 1
    assert config._backup_retention_days("0") == 7
    assert config._backup_retention_days("abc") == 7


def test_backup_dir_falls_back_when_blank():
    assert config._backup_dir("   ") == config.DEFAULT_BACKUP_DIR
    assert config._backup_dir(" /tmp/daily ") == "/tmp/daily"

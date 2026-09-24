from pathlib import Path

from tools import check_secrets


def _telegram_token() -> str:
    # Собираем в рантайме, чтобы тестовый файл сам не выглядел утечкой.
    return "8418554077" + ":" + "AA" + "F" * 35


def _openrouter_key() -> str:
    return "sk-or-v1-" + "a" * 40


def test_detects_and_masks_synthetic_tokens(tmp_path):
    token = _telegram_token()
    key = _openrouter_key()
    path = tmp_path / "leak.txt"
    path.write_text(f"bot={token}\nkey={key}\n", encoding="utf-8")

    findings = check_secrets.scan_paths([str(path)])

    assert len(findings) == 2
    assert {name for _, _, name, _ in findings} == {
        "telegram-bot-token",
        "openrouter-api-key",
    }
    for _, _, _, masked in findings:
        assert token not in masked
        assert key not in masked
        assert "…" in masked


def test_detects_private_key(tmp_path):
    # Части на разных строках, чтобы сам тестовый файл не выглядел ключом.
    begin = "-----BEGIN "
    end = "RSA PRIVATE KEY-----"
    path = tmp_path / "id_rsa"
    path.write_text(begin + end + "\n", encoding="utf-8")

    findings = check_secrets.scan_paths([str(path)])

    assert [name for _, _, name, _ in findings] == ["private-key"]


def test_clean_file_has_no_findings(tmp_path):
    path = tmp_path / "clean.txt"
    path.write_text("обычный текст без секретов\n", encoding="utf-8")

    assert check_secrets.scan_paths([str(path)]) == []
    assert check_secrets.main([str(path)]) == 0


def test_main_returns_one_and_masks_on_finding(tmp_path, capsys):
    token = _telegram_token()
    path = tmp_path / "leak.txt"
    path.write_text(token + "\n", encoding="utf-8")

    assert check_secrets.main([str(path)]) == 1

    out = capsys.readouterr().out
    assert "telegram-bot-token" in out
    assert token not in out


def test_script_itself_is_clean():
    """Скрипт не должен находить секреты в собственном исходнике."""
    assert check_secrets.scan_paths([str(Path(check_secrets.__file__))]) == []

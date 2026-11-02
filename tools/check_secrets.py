"""Локальная проверка файлов на утечки секретов.

Ищет токены Telegram-бота, ключи OpenRouter и приватные ключи. Зависимостей
нет — только stdlib, чтобы запускаться в CI и локально.

Запуск:

    python tools/check_secrets.py [путь ...]

Без аргументов проверяет файлы из `git ls-files`. Код возврата 1 при находке.
Значения секретов маскируются и никогда не печатаются целиком.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# Ограничение, чтобы случайно не читать огромные бинарные ассеты.
MAX_FILE_BYTES = 5 * 1024 * 1024

TELEGRAM_TOKEN_RE = re.compile(r"\b\d{8,10}:AA[A-Za-z0-9_-]{30,}\b")
OPENROUTER_KEY_RE = re.compile(r"\bsk-or-v1-[a-f0-9]{32,}\b")
# Собираем шаблон из частей, чтобы сам скрипт не выглядел приватным ключом.
_PRIVATE_KEY_BEGIN = "-----BEGIN "
_PRIVATE_KEY_RE = re.compile(_PRIVATE_KEY_BEGIN + r".*PRIVATE KEY-----")

PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("telegram-bot-token", TELEGRAM_TOKEN_RE),
    ("openrouter-api-key", OPENROUTER_KEY_RE),
    ("private-key", _PRIVATE_KEY_RE),
)


def mask(secret: str) -> str:
    """Показывает только края значения, чтобы его нельзя было восстановить."""
    if len(secret) <= 8:
        return "…"
    return f"{secret[:6]}…{secret[-2:]}"


def scan_text(text: str) -> list[tuple[int, str, str]]:
    """Возвращает находки как (номер строки, имя правила, маска)."""
    findings: list[tuple[int, str, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for name, pattern in PATTERNS:
            for match in pattern.finditer(line):
                findings.append((lineno, name, mask(match.group(0))))
    return findings


def git_tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        capture_output=True,
        check=True,
    )
    names = result.stdout.decode("utf-8", "surrogateescape").split("\0")
    return [Path(name) for name in names if name]


def iter_files(paths: list[str]):
    if not paths:
        yield from git_tracked_files()
        return
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file() and ".git" not in child.parts:
                    yield child
        elif path.is_file():
            yield path


def _read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None
    except OSError:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def scan_paths(paths: list[str]) -> list[tuple[str, int, str, str]]:
    """Сканирует пути; возвращает (файл, строка, правило, маска)."""
    results: list[tuple[str, int, str, str]] = []
    for path in iter_files(paths):
        text = _read_text(path)
        if text is None:
            continue
        for lineno, name, masked in scan_text(text):
            results.append((str(path), lineno, name, masked))
    return results


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    findings = scan_paths(args)
    if not findings:
        print("Секретов не найдено.")
        return 0
    print(f"Найдены возможные секреты: {len(findings)}")
    for path, lineno, name, masked in findings:
        print(f"{path}:{lineno}: {name}: {masked}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

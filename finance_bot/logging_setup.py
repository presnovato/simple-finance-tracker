"""Разделение потоков логирования по уровню (spec 08).

Railway показывает записи из stderr как ошибки, поэтому обычные INFO/WARNING
должны идти в stdout, а настоящие ERROR/CRITICAL — в stderr ровно один раз.
Форматирование сохраняет время, уровень и имя logger.
"""

import logging
import sys


class _MaxLevelFilter(logging.Filter):
    """Пропускает записи не выше заданного уровня."""

    def __init__(self, max_level: int) -> None:
        super().__init__()
        self.max_level = max_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno <= self.max_level


def build_handlers(stdout=None, stderr=None) -> tuple[logging.Handler, ...]:
    """Потоковые обработчики: DEBUG/INFO/WARNING → stdout, ERROR → stderr."""
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    out_handler = logging.StreamHandler(stdout if stdout is not None else sys.stdout)
    out_handler.setLevel(logging.DEBUG)
    out_handler.addFilter(_MaxLevelFilter(logging.WARNING))
    out_handler.setFormatter(formatter)

    err_handler = logging.StreamHandler(stderr if stderr is not None else sys.stderr)
    err_handler.setLevel(logging.ERROR)
    err_handler.setFormatter(formatter)

    return out_handler, err_handler


def configure_logging(
    level: int = logging.INFO,
    *,
    stdout=None,
    stderr=None,
) -> None:
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    for handler in build_handlers(stdout, stderr):
        root.addHandler(handler)

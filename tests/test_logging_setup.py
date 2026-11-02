"""Разделение логов по потокам (spec 08)."""

import io
import logging

from finance_bot.logging_setup import build_handlers


def test_levels_are_split_between_stdout_and_stderr_without_duplication():
    out, err = io.StringIO(), io.StringIO()
    logger = logging.getLogger("finance_bot.test.route")
    logger.propagate = False
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)
    for handler in build_handlers(out, err):
        logger.addHandler(handler)

    try:
        logger.info("hello-info")
        logger.warning("hello-warn")
        logger.error("hello-error")
    finally:
        for handler in logger.handlers:
            handler.flush()
        logger.handlers.clear()

    out_text, err_text = out.getvalue(), err.getvalue()
    assert "hello-info" in out_text
    assert "hello-warn" in out_text
    assert "hello-error" not in out_text
    assert "hello-error" in err_text
    # Ошибка попадает в stderr ровно один раз.
    assert err_text.count("hello-error") == 1
    # Формат сохраняет уровень и имя logger.
    assert "INFO" in out_text
    assert "finance_bot.test.route" in out_text
    assert "ERROR" in err_text

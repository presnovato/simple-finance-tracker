from finance_bot.handlers import capture
from finance_bot.handlers.capture import is_many_caption


def test_many_mode_requires_explicit_caption_marker():
    assert is_many_caption("список") is True
    assert is_many_caption("Расходы за день") is True
    assert is_many_caption("обычный чек") is False
    assert is_many_caption(None) is False


def test_many_mode_command_is_one_shot():
    capture._awaiting_many_shot = True
    assert capture._consume_many_mode(None) is True
    assert capture._consume_many_mode(None) is False

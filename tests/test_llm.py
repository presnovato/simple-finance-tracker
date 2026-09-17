from datetime import date

from finance_bot.services import llm


async def test_correction_prompt_contains_previous_message_context(monkeypatch):
    captured = {}

    monkeypatch.setattr(llm, "OPENROUTER_API_KEY", "test-key")

    async def fake_call(model, messages, plugins=None):
        captured["messages"] = messages
        return (
            '{"type":"расход","amount":1947,"category":"Прочее",'
            '"comment":"Плати по миру"}'
        )

    monkeypatch.setattr(llm, "_call", fake_call)

    corrected = await llm.correct_operation(
        {"amount": None, "type": "расход"},
        "1947р Расход Прочее",
        date(2026, 9, 8),
        context="⚠️ Не разобрал уверенно — допиши вручную.",
    )

    prompt = captured["messages"][0]["content"]
    assert "⚠️ Не разобрал уверенно" in prompt
    assert "1947р Расход Прочее" in prompt
    assert corrected["amount"] is not None
    assert str(corrected["amount"]) == "1947"


async def test_text_extraction_without_key_does_not_call_network(monkeypatch):
    monkeypatch.setattr(llm, "OPENROUTER_API_KEY", "")

    async def fail(*_args, **_kwargs):
        raise AssertionError("AI без ключа не должен вызывать сеть")

    monkeypatch.setattr(llm, "_call", fail)
    parsed = await llm.extract_from_text("такси 450", date(2026, 9, 17))

    assert parsed["date"] == date(2026, 9, 17)
    assert parsed["amount"] is None

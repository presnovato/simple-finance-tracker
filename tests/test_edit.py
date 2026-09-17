from types import SimpleNamespace

from finance_bot.handlers import edit


async def test_reply_to_uncertain_capture_uses_saved_pending_context(monkeypatch):
    calls = {}
    reply = SimpleNamespace(
        message_id=77,
        text="⚠️ Не разобрал уверенно — допиши вручную.",
        caption=None,
    )
    message = SimpleNamespace(
        reply_to_message=reply,
        text="1947р Расход Прочее",
        reply=lambda *_args, **_kwargs: None,
    )

    async def get_operation(_message_id):
        return None

    async def get_pending(_message_id):
        return {
            "source": "бот-текст",
            "context": "исходный текст",
            "draft": {"amount": None, "type": "расход"},
        }

    async def correct_operation(*args, **kwargs):
        calls["correction"] = (args, kwargs)
        return {
            "amount": 1947,
            "type": "расход",
            "category": "Прочее",
            "comment": "Плати по миру",
        }

    async def save_and_confirm(*args, **kwargs):
        calls["save"] = (args, kwargs)

    async def delete_pending(_message_id):
        calls["deleted"] = True

    monkeypatch.setattr(edit.queries, "get_by_tg_message_id", get_operation)
    monkeypatch.setattr(edit.queries, "get_pending_capture", get_pending)
    monkeypatch.setattr(edit.queries, "delete_pending_capture", delete_pending)
    monkeypatch.setattr(edit.llm, "correct_operation", correct_operation)
    monkeypatch.setattr(edit.capture, "save_and_confirm", save_and_confirm)

    await edit.on_correction(message)

    assert calls["correction"][1]["context"] == "исходный текст"
    assert calls["save"][0][2] == "бот-текст"
    assert calls["deleted"] is True

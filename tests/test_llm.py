from datetime import date
import json

import httpx
import pytest

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


def _install_transport(monkeypatch, handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(llm, "_http_client", client)
    monkeypatch.setattr(llm, "OPENROUTER_API_KEY", "test-key")
    return client


async def test_call_raises_unavailable_on_payment_required(monkeypatch):
    def handler(_request):
        return httpx.Response(402, json={"error": {"message": "no credits"}})

    client = _install_transport(monkeypatch, handler)
    try:
        with pytest.raises(llm.LLMUnavailable) as excinfo:
            await llm._call("vendor/model", [{"role": "user", "content": "hi"}])
        assert excinfo.value.status == 402
        assert "кредиты" in excinfo.value.reason
    finally:
        await client.aclose()


async def test_call_raises_unavailable_on_timeout(monkeypatch):
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    client = _install_transport(monkeypatch, handler)
    try:
        with pytest.raises(llm.LLMUnavailable):
            await llm._call("vendor/model", [{"role": "user", "content": "hi"}])
    finally:
        await client.aclose()


async def test_junk_200_response_is_parse_failure(monkeypatch):
    def handler(_request):
        return httpx.Response(200, text="это не JSON")

    client = _install_transport(monkeypatch, handler)
    try:
        raw = await llm._call("vendor/model", [{"role": "user", "content": "hi"}])
        assert raw == ""

        parsed = await llm.extract_from_text("такси 450", date(2026, 9, 17))
        assert parsed["amount"] is None
        assert parsed["needs_review"] is True
    finally:
        await client.aclose()


async def test_payload_contains_provider_preferences_when_enabled(monkeypatch):
    captured = {}

    def handler(request):
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "{}"}}]}
        )

    client = _install_transport(monkeypatch, handler)
    monkeypatch.setattr(llm, "LLM_DENY_DATA_COLLECTION", True)
    try:
        await llm._call("vendor/model", [{"role": "user", "content": "hi"}])
    finally:
        await client.aclose()

    assert captured["payload"]["provider"] == {"data_collection": "deny"}


async def test_payload_omits_provider_preferences_when_disabled(monkeypatch):
    captured = {}

    def handler(request):
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "{}"}}]}
        )

    client = _install_transport(monkeypatch, handler)
    monkeypatch.setattr(llm, "LLM_DENY_DATA_COLLECTION", False)
    try:
        await llm._call("vendor/model", [{"role": "user", "content": "hi"}])
    finally:
        await client.aclose()

    assert "provider" not in captured["payload"]


async def test_extract_raises_when_both_models_are_unavailable(monkeypatch):
    def handler(_request):
        return httpx.Response(429, json={"error": {"message": "rate limited"}})

    client = _install_transport(monkeypatch, handler)
    try:
        with pytest.raises(llm.LLMUnavailable):
            await llm.extract_from_text("такси 450", date(2026, 9, 17))
    finally:
        await client.aclose()


async def test_check_models_available_notifies_owner_about_missing_model(monkeypatch):
    def handler(_request):
        return httpx.Response(200, json={"data": [{"id": "vendor/primary"}]})

    client = _install_transport(monkeypatch, handler)
    monkeypatch.setattr(llm, "PRIMARY_MODEL", "vendor/primary")
    monkeypatch.setattr(llm, "FALLBACK_MODEL", "vendor/missing")

    sent = []

    class FakeBot:
        async def send_message(self, chat_id, text, **kwargs):
            sent.append((chat_id, text))

    try:
        missing = await llm.check_models_available(FakeBot())
    finally:
        await client.aclose()

    assert missing == ["vendor/missing"]
    assert len(sent) == 1
    assert "vendor/missing" in sent[0][1]


async def test_check_models_available_ignores_network_failure(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("no net", request=request)

    client = _install_transport(monkeypatch, handler)

    class FakeBot:
        async def send_message(self, *args, **kwargs):
            raise AssertionError("не должно быть сообщений")

    try:
        assert await llm.check_models_available(FakeBot()) == []
    finally:
        await client.aclose()

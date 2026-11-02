import io
import json
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from finance_mcp import server


class StubFinanceClient:
    def __init__(self):
        self.calls = []

    def request(self, path, *, params=None):
        self.calls.append((path, params))
        return {"path": path, "params": params or {}}


def _modern_message(method, request_id=1, params=None, *, version=None):
    value = dict(params or {})
    value["_meta"] = {
        "io.modelcontextprotocol/protocolVersion": (
            version or server.MODERN_PROTOCOL_VERSION
        ),
        "io.modelcontextprotocol/clientCapabilities": {},
        "io.modelcontextprotocol/clientInfo": {
            "name": "test-client",
            "version": "1.0",
        },
    }
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": value,
    }


def test_dual_era_discovery_and_legacy_initialize():
    mcp = server.MCPServer(StubFinanceClient())
    discover = mcp.handle(_modern_message("server/discover", "discover-1"))
    assert discover["result"]["resultType"] == "complete"
    assert discover["result"]["supportedVersions"] == ["2026-07-28"]
    assert discover["result"]["capabilities"] == {
        "tools": {"listChanged": False}
    }

    initialized = mcp.handle({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "legacy-client", "version": "1.0"},
        },
    })
    assert initialized["result"]["protocolVersion"] == "2025-11-25"
    assert "resultType" not in initialized["result"]

    # 2025 clients can attach the progressToken without modern version metadata.
    legacy_tools = mcp.handle({
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/list",
        "params": {"_meta": {"progressToken": 9}},
    })
    assert len(legacy_tools["result"]["tools"]) == 3

    unsupported = mcp.handle({
        "jsonrpc": "2.0",
        "id": 5,
        "method": "initialize",
        "params": {"protocolVersion": "2026-07-28"},
    })
    assert unsupported["error"]["code"] == -32602


def test_tools_list_and_calls_work_in_both_protocol_eras():
    client = StubFinanceClient()
    mcp = server.MCPServer(client)

    legacy_tools = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert [tool["name"] for tool in legacy_tools["result"]["tools"]] == [
        "finance_get_week",
        "finance_get_snapshot",
        "finance_list_operations",
    ]
    assert all(tool["annotations"]["readOnlyHint"] for tool in legacy_tools["result"]["tools"])

    modern_tools = mcp.handle(_modern_message("tools/list", 2))
    assert modern_tools["result"]["resultType"] == "complete"
    assert len(modern_tools["result"]["tools"]) == 3

    weekly = mcp.handle({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "finance_get_week",
            "arguments": {"week_start": "2026-09-28"},
        },
    })
    assert json.loads(weekly["result"]["content"][0]["text"]) == {
        "path": "/api/integrations/finance/week",
        "params": {"week_start": "2026-09-28"},
    }
    assert client.calls[-1] == (
        "/api/integrations/finance/week", {"week_start": "2026-09-28"}
    )

    operations = mcp.handle(_modern_message(
        "tools/call",
        4,
        {
            "name": "finance_list_operations",
            "arguments": {
                "date_from": "2026-09-01",
                "date_to": "2026-09-30",
                "needs_review": True,
                "cursor": "cursor-value",
            },
        },
    ))
    assert operations["result"]["resultType"] == "complete"
    assert json.loads(operations["result"]["content"][0]["text"])["params"] == {
        "date_from": "2026-09-01",
        "date_to": "2026-09-30",
        "needs_review": "true",
        "before": "cursor-value",
    }


def test_tool_validation_and_errors_are_explicit():
    mcp = server.MCPServer(StubFinanceClient())
    invalid_date = mcp.handle({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "finance_get_week",
            "arguments": {"week_start": "20260928"},
        },
    })
    result = invalid_date["result"]
    assert result["isError"] is True
    assert json.loads(result["content"][0]["text"]) == {
        "error": "invalid_tool_request",
        "detail": "week_start must be YYYY-MM-DD",
    }

    bad_version = mcp.handle(_modern_message(
        "tools/list", 2, version="2099-01-01"
    ))
    assert bad_version["error"]["code"] == -32022
    assert bad_version["error"]["data"] == {
        "supported": ["2026-07-28"],
        "requested": "2099-01-01",
    }

    missing_meta = mcp.handle({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/list",
        "params": {
            "_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}
        },
    })
    assert missing_meta["error"]["code"] == -32602

    unknown_tool = mcp.handle({
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {"name": "finance_write_operation", "arguments": {}},
    })
    assert unknown_tool["error"]["code"] == -32601


def test_stdio_framing_keeps_stdout_as_jsonrpc_only(monkeypatch, capsys):
    client = StubFinanceClient()
    monkeypatch.setattr(server, "FinanceClient", lambda: client)
    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "finance_get_snapshot", "arguments": {}},
        },
    ]
    monkeypatch.setattr(
        server.sys,
        "stdin",
        io.StringIO("\n".join(json.dumps(request) for request in requests) + "\n"),
    )
    output = io.StringIO()
    monkeypatch.setattr(server.sys, "stdout", output)

    server.run_stdio_server()

    responses = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [item["id"] for item in responses] == [1, 2, 3]
    assert responses[0]["result"]["protocolVersion"] == "2025-11-25"
    assert len(responses[1]["result"]["tools"]) == 3
    assert json.loads(responses[2]["result"]["content"][0]["text"]) == {
        "path": "/api/integrations/finance/snapshot",
        "params": {},
    }
    assert capsys.readouterr().out == ""


def test_finance_client_url_policy_and_header_only_token(monkeypatch):
    assert server.FinanceClient._validate_base_url(
        "http://127.0.0.1:8080/"
    ) == "http://127.0.0.1:8080"
    assert server.FinanceClient._validate_base_url(
        "https://finance.example/api"
    ) == "https://finance.example/api"
    for unsafe in (
        "http://finance.example",
        "https://finance.example:not-a-port",
        "https://user:password@finance.example",
        "https://finance.example?token=x",
        "https://finance.example#fragment",
    ):
        with pytest.raises(ValueError):
            server.FinanceClient._validate_base_url(unsafe)

    captured = {}

    class Response:
        headers = {"Content-Length": "11"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _maximum):
            return b'{"ok":true}'

    class Opener:
        def open(self, request, *, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return Response()

    monkeypatch.setattr(server, "build_opener", lambda *_handlers: Opener())
    client = server.FinanceClient(
        "https://finance.example", "private-agent-token"
    )
    assert client.request("/api/integrations/finance/snapshot") == {"ok": True}
    request = captured["request"]
    assert "private-agent-token" not in request.full_url
    assert request.get_header("Authorization") == "Bearer private-agent-token"
    assert captured["timeout"] == server.REQUEST_TIMEOUT_SECONDS


def test_redirect_handler_refuses_to_forward_agent_token():
    handler = server._NoRedirectHandler()
    request = Request("https://finance.example/api/integrations/finance/week")
    with pytest.raises(server.FinanceTransportError, match="redirects are not allowed"):
        handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://other.example/steal-token",
        )


def test_finance_api_errors_are_preserved_without_exposing_request_token(monkeypatch):
    error = HTTPError(
        "https://finance.example/api/integrations/finance/snapshot",
        503,
        "Unavailable",
        {},
        io.BytesIO(b'{"error":"integration_not_configured"}'),
    )

    class Opener:
        def open(self, _request, *, timeout):
            raise error

    monkeypatch.setattr(server, "build_opener", lambda *_handlers: Opener())
    client = server.FinanceClient(
        "https://finance.example", "private-agent-token"
    )
    with pytest.raises(server.FinanceAPIError) as raised:
        client.request("/api/integrations/finance/snapshot")
    assert raised.value.status == 503
    assert raised.value.detail == {"error": "integration_not_configured"}
    assert "private-agent-token" not in str(raised.value)


def test_oversized_response_is_rejected(monkeypatch):
    class Response:
        headers = {"Content-Length": str(server.MAX_RESPONSE_BYTES + 1)}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class Opener:
        def open(self, _request, *, timeout):
            return Response()

    monkeypatch.setattr(server, "build_opener", lambda *_handlers: Opener())
    client = server.FinanceClient("https://finance.example", "token")
    with pytest.raises(server.FinanceAPIError, match="response_too_large"):
        client.request("/api/integrations/finance/snapshot")

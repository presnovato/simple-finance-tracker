"""Dependency-free STDIO MCP bridge to the owner-only Finance Tracker API."""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import socket
import sys
from datetime import date
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from . import __version__

logger = logging.getLogger(__name__)
MAX_RESPONSE_BYTES = 1_048_576
REQUEST_TIMEOUT_SECONDS = 15
LEGACY_PROTOCOL_VERSIONS = {
    "2024-11-05",
    "2025-03-26",
    "2025-06-18",
    "2025-11-25",
}
MODERN_PROTOCOL_VERSION = "2026-07-28"

TOOLS = [
    {
        "name": "finance_get_week",
        "description": (
            "Read recorded Finance Tracker totals for one Monday-to-Sunday week. "
            "This does not confirm that every real-world transaction was recorded."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "week_start": {
                    "type": "string",
                    "format": "date",
                    "description": "Optional Monday in YYYY-MM-DD format; defaults to the current finance week.",
                }
            },
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
    },
    {
        "name": "finance_get_snapshot",
        "description": (
            "Read current dated cash-anchor and debt snapshot. Missing or untracked "
            "values remain null with an explanation."
        ),
        "inputSchema": {"type": "object", "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
    },
    {
        "name": "finance_list_operations",
        "description": (
            "Read a page of recorded active operations for a date range of at most "
            "31 days. Use only when weekly aggregates need investigation."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string", "format": "date"},
                "date_to": {"type": "string", "format": "date"},
                "type": {"type": "string", "enum": ["расход", "доход", "перевод"]},
                "category": {"type": "string"},
                "needs_review": {"type": "boolean"},
                "cursor": {"type": "string"},
            },
            "required": ["date_from", "date_to"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
    },
]


class FinanceAPIError(RuntimeError):
    def __init__(self, status: int | None, detail: object):
        self.status = status
        self.detail = detail
        super().__init__(str(detail))


class FinanceTransportError(RuntimeError):
    pass


def _is_loopback_host(hostname: str | None) -> bool:
    if not hostname:
        return False
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise FinanceTransportError("redirects are not allowed for the Finance API")


class FinanceClient:
    def __init__(self, base_url: str | None = None, token: str | None = None):
        configured_url = base_url or os.getenv(
            "FINANCE_API_URL", "http://127.0.0.1:8080"
        )
        self.base_url = self._validate_base_url(configured_url)
        self.token = (
            token if token is not None else os.getenv("FINANCE_AGENT_TOKEN", "")
        ).strip()

    @staticmethod
    def _validate_base_url(value: str) -> str:
        normalized = value.strip().rstrip("/")
        try:
            parsed = urlparse(normalized)
            hostname = parsed.hostname
            parsed.port
        except ValueError as exc:
            raise ValueError("FINANCE_API_URL must be a valid absolute URL") from exc
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or not hostname:
            raise ValueError("FINANCE_API_URL must be an absolute HTTP(S) URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("FINANCE_API_URL must not contain userinfo")
        if parsed.query or parsed.fragment:
            raise ValueError("FINANCE_API_URL must not contain a query or fragment")
        if parsed.scheme == "http" and not _is_loopback_host(hostname):
            raise ValueError("FINANCE_API_URL must use HTTPS outside loopback development")
        return normalized

    def request(self, path: str, *, params: dict[str, str] | None = None) -> object:
        if not self.token:
            raise FinanceAPIError(None, "integration_not_configured")
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        request = Request(
            url,
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"},
            method="GET",
        )
        try:
            with build_opener(_NoRedirectHandler()).open(
                request, timeout=REQUEST_TIMEOUT_SECONDS
            ) as response:
                length = response.headers.get("Content-Length")
                if length is not None:
                    try:
                        content_length = int(length)
                    except ValueError as exc:
                        raise FinanceAPIError(None, "invalid_api_response") from exc
                    if content_length > MAX_RESPONSE_BYTES:
                        raise FinanceAPIError(None, "response_too_large")
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            raw = exc.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise FinanceAPIError(exc.code, "response_too_large") from exc
            try:
                detail = json.loads(raw.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                detail = f"http_{exc.code}"
            raise FinanceAPIError(exc.code, detail) from exc
        except FinanceTransportError:
            raise
        except (OSError, URLError, socket.timeout, TimeoutError, HTTPException) as exc:
            raise FinanceTransportError("Finance Tracker API is unreachable") from exc
        if len(raw) > MAX_RESPONSE_BYTES:
            raise FinanceAPIError(None, "response_too_large")
        try:
            return json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FinanceAPIError(None, "invalid_api_response") from exc


def _parse_date(value: object, name: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"{name} must be YYYY-MM-DD")
    return parsed


def call_tool(name: str, arguments: dict, client: FinanceClient) -> object:
    allowed = {
        "finance_get_week": {"week_start"},
        "finance_get_snapshot": set(),
        "finance_list_operations": {
            "date_from", "date_to", "type", "category", "needs_review", "cursor"
        },
    }
    if name not in allowed:
        raise ValueError("unknown tool")
    extra = set(arguments) - allowed[name]
    if extra:
        raise ValueError("unexpected argument")

    if name == "finance_get_week":
        start_text = arguments.get("week_start")
        params = {}
        if start_text is not None:
            start = _parse_date(start_text, "week_start")
            if start.weekday() != 0:
                raise ValueError("week_start must be a Monday")
            params["week_start"] = start.isoformat()
        return client.request("/api/integrations/finance/week", params=params)

    if name == "finance_get_snapshot":
        return client.request("/api/integrations/finance/snapshot")

    start = _parse_date(arguments.get("date_from"), "date_from")
    end = _parse_date(arguments.get("date_to"), "date_to")
    if start > end:
        raise ValueError("date_from must not be after date_to")
    if (end - start).days + 1 > 31:
        raise ValueError("date range must not exceed 31 days")
    needs_review = arguments.get("needs_review")
    if needs_review is not None and not isinstance(needs_review, bool):
        raise ValueError("needs_review must be a boolean")
    params = {"date_from": start.isoformat(), "date_to": end.isoformat()}
    for key in ("type", "category"):
        value = arguments.get(key)
        if value is not None:
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{key} must be a non-empty string")
            params[key] = value
    cursor = arguments.get("cursor")
    if cursor is not None:
        if not isinstance(cursor, str) or not cursor.strip():
            raise ValueError("cursor must be a non-empty string")
        params["before"] = cursor
    if needs_review is not None:
        params["needs_review"] = "true" if needs_review else "false"
    return client.request("/api/integrations/finance/operations", params=params)


def _json_result(value: object, *, is_error: bool = False) -> dict:
    result = {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}]}
    if isinstance(value, dict):
        result["structuredContent"] = value
    if is_error:
        result["isError"] = True
    return result


def _tool_error(exc: Exception) -> dict:
    if isinstance(exc, FinanceAPIError):
        value = {"error": exc.detail}
        if exc.status is not None:
            value["status"] = exc.status
    elif isinstance(exc, FinanceTransportError):
        value = {"error": "finance_api_unreachable"}
    elif isinstance(exc, ValueError):
        value = {"error": "invalid_tool_request", "detail": str(exc)}
    else:
        logger.exception("Finance MCP tool failed")
        value = {"error": "invalid_tool_request"}
    return _json_result(value, is_error=True)


def _rpc_error(request_id: object, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _modern_rpc_error(request_id: object, requested: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": -32022,
            "message": "Unsupported protocol version",
            "data": {
                "supported": [MODERN_PROTOCOL_VERSION],
                "requested": requested,
            },
        },
    }


def _modern_result(result: dict) -> dict:
    return {"resultType": "complete", **result}


def _request_protocol_version(message: dict) -> tuple[str | None, dict | None]:
    params = message.get("params")
    if params is None:
        return None, None
    if not isinstance(params, dict):
        return None, {"code": -32602, "message": "params must be an object"}
    meta = params.get("_meta")
    if meta is None:
        return None, None
    if not isinstance(meta, dict):
        return None, {"code": -32602, "message": "_meta must be an object"}
    version = meta.get("io.modelcontextprotocol/protocolVersion")
    if version is None and "io.modelcontextprotocol/clientCapabilities" not in meta:
        # Legacy revisions may put progressToken or other metadata here without
        # per-request protocol fields.
        return None, None
    if not isinstance(version, str) or not version:
        return None, {
            "code": -32602,
            "message": "_meta.io.modelcontextprotocol/protocolVersion is required",
        }
    if not isinstance(meta.get("io.modelcontextprotocol/clientCapabilities"), dict):
        return None, {
            "code": -32602,
            "message": "_meta.io.modelcontextprotocol/clientCapabilities is required",
        }
    if version != MODERN_PROTOCOL_VERSION:
        return version, {"unsupported_version": True, "requested": version}
    return version, None


class MCPServer:
    def __init__(self, client: FinanceClient | None = None):
        self.client = client or FinanceClient()
        self.shutdown_requested = False

    def handle(self, message: dict) -> dict | None:
        method = message.get("method")
        request_id = message.get("id")
        is_request = "id" in message
        version, protocol_error = _request_protocol_version(message)
        modern = version == MODERN_PROTOCOL_VERSION
        if protocol_error is not None:
            if protocol_error.get("unsupported_version"):
                return _modern_rpc_error(request_id, protocol_error["requested"])
            return _rpc_error(
                request_id, protocol_error["code"], protocol_error["message"]
            )

        if method == "server/discover":
            if version is None:
                return _rpc_error(
                    request_id, -32602, "modern request metadata is required"
                )
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": _modern_result({
                    "supportedVersions": [MODERN_PROTOCOL_VERSION],
                    "capabilities": {"tools": {"listChanged": False}},
                    "_meta": {
                        "io.modelcontextprotocol/serverInfo": {
                            "name": "finance-tracker",
                            "version": __version__,
                        }
                    },
                    "instructions": (
                        "All Finance Tracker tools are read-only. Weekly data covers "
                        "recorded operations; snapshot data is current as of its returned date."
                    ),
                    "ttlMs": 3_600_000,
                    "cacheScope": "public",
                }),
            }
        if method == "initialize":
            requested = str((message.get("params") or {}).get("protocolVersion", ""))
            if requested not in LEGACY_PROTOCOL_VERSIONS:
                return _rpc_error(
                    request_id,
                    -32602,
                    "unsupported legacy protocol version; supported legacy versions: "
                    + ", ".join(sorted(LEGACY_PROTOCOL_VERSIONS)),
                )
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": requested,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "finance-tracker", "version": __version__},
                    "instructions": "All Finance Tracker tools are read-only. Weekly data covers recorded operations; snapshot data is current as of its returned date.",
                },
            }
        if method in {"notifications/initialized", "notifications/cancelled"}:
            return None
        if method == "ping":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": _modern_result({}) if modern else {},
            } if is_request else None
        if method == "shutdown":
            self.shutdown_requested = True
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": _modern_result({}) if modern else None,
            }
        if method == "tools/list":
            result = {"tools": TOOLS}
            if modern:
                result = _modern_result(result)
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        if method == "tools/call":
            params = message.get("params") or {}
            name = params.get("name")
            if not isinstance(name, str):
                return _rpc_error(request_id, -32602, "tool name is required")
            if name not in {tool["name"] for tool in TOOLS}:
                return _rpc_error(request_id, -32601, f"unknown tool: {name}")
            arguments = params.get("arguments") or {}
            if not isinstance(arguments, dict):
                return _rpc_error(request_id, -32602, "tool arguments must be an object")
            try:
                result = _json_result(call_tool(name, arguments, self.client))
            except Exception as exc:
                result = _tool_error(exc)
            if modern:
                result = _modern_result(result)
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        if not is_request:
            return None
        return _rpc_error(request_id, -32601, f"method not found: {method}")


def _configure_stdio_utf8() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def run_stdio_server() -> None:
    _configure_stdio_utf8()
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    server = MCPServer()
    for raw_line in sys.stdin:
        if not raw_line.strip():
            continue
        try:
            message = json.loads(raw_line)
            response = (
                server.handle(message)
                if isinstance(message, dict)
                else _rpc_error(None, -32600, "JSON-RPC message must be an object")
            )
        except json.JSONDecodeError:
            response = _rpc_error(None, -32700, "parse error")
        except Exception:
            logger.exception("Finance MCP protocol handling failed")
            response = _rpc_error(None, -32603, "internal error")
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
            sys.stdout.flush()

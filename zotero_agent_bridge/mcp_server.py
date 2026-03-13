from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any, BinaryIO
from urllib.parse import unquote

import requests

from .config import Settings
from .errors import BridgeError

DEFAULT_PROTOCOL_VERSION = "2025-03-26"
SERVER_NAME = "zotero-agent-bridge"
SERVER_VERSION = "0.1.0"
RESOURCE_SERVER_INFO_URI = "zotero://server/info"
RESOURCE_BRIDGE_HEALTH_URI = "zotero://bridge/health"
RESOURCE_BRIDGE_CAPABILITIES_URI = "zotero://bridge/capabilities"
RESOURCE_ITEM_URI_PREFIX = "zotero://items/"


class BridgeHttpClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        session: Any | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.session = session or requests.Session()
        self.timeout_seconds = timeout_seconds

    def _headers(self) -> dict[str, str]:
        return {
            "X-Bridge-Token": self.token,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.base_url}/{path.lstrip('/')}"

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        kwargs = {
            "method": method.upper(),
            "url": self._url(path),
            "headers": self._headers(),
            "params": params,
            "json": json_body,
        }
        try:
            response = self.session.request(timeout=self.timeout_seconds, **kwargs)
        except TypeError:
            response = self.session.request(**kwargs)
        except requests.RequestException as exc:
            raise BridgeError(503, "bridge_http_unavailable", "Bridge HTTP API is unavailable", {"error": str(exc)}) from exc

        if response.status_code >= 400:
            details: dict[str, Any] = {"status_code": response.status_code}
            message = f"Bridge HTTP API request failed with status {response.status_code}"
            code = "bridge_http_error"
            try:
                payload = response.json()
            except Exception:
                payload = None
            if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
                error = payload["error"]
                code = error.get("code") or code
                message = error.get("message") or message
                details = error.get("details") or details
            else:
                body = getattr(response, "text", "")
                if body:
                    details["body"] = body[:500]
            raise BridgeError(response.status_code, code, message, details)

        if getattr(response, "content", b""):
            return response.json()
        return None


@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


@dataclass(slots=True)
class ResourceSpec:
    uri: str
    name: str
    description: str
    mime_type: str = "application/json"

    def as_dict(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "name": self.name,
            "description": self.description,
            "mimeType": self.mime_type,
        }


@dataclass(slots=True)
class ResourceTemplateSpec:
    uri_template: str
    name: str
    description: str
    mime_type: str = "application/json"

    def as_dict(self) -> dict[str, Any]:
        return {
            "uriTemplate": self.uri_template,
            "name": self.name,
            "description": self.description,
            "mimeType": self.mime_type,
        }


class ZoteroBridgeMCPServer:
    def __init__(
        self,
        http_client: BridgeHttpClient,
        *,
        input_stream: BinaryIO | None = None,
        output_stream: BinaryIO | None = None,
        error_stream: BinaryIO | None = None,
    ) -> None:
        self.http_client = http_client
        self.input_stream = input_stream or sys.stdin.buffer
        self.output_stream = output_stream or sys.stdout.buffer
        self.error_stream = error_stream or sys.stderr.buffer
        self.protocol_version = DEFAULT_PROTOCOL_VERSION

    def list_tools(self) -> list[dict[str, Any]]:
        return [spec.as_dict() for spec in self._tool_specs()]

    def list_resources(self) -> list[dict[str, Any]]:
        return [spec.as_dict() for spec in self._resource_specs()]

    def list_resource_templates(self) -> list[dict[str, Any]]:
        return [spec.as_dict() for spec in self._resource_template_specs()]

    def _tool_specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="search_items",
                description="Search Zotero items by free-text query.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "q": {"type": "string", "minLength": 1},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                    },
                    "required": ["q"],
                    "additionalProperties": False,
                },
            ),
            ToolSpec(
                name="create_item",
                description="Create a Zotero parent item from a DOI, PDF path, or manual metadata fields.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "doi": {"type": "string"},
                        "pdf_path": {"type": "string"},
                        "manual_fields": {"type": "object"},
                        "tags": {"type": "array", "items": {}},
                        "collections": {"type": "array", "items": {"type": "string"}},
                        "dedupe": {"type": "boolean", "default": True},
                    },
                    "additionalProperties": False,
                },
            ),
            ToolSpec(
                name="update_item",
                description="Update Zotero item fields, creators, tags, or collections with version checking.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "item_key": {"type": "string"},
                        "version": {"type": "integer"},
                        "fields": {"type": "object"},
                        "creators": {"type": "array", "items": {"type": "object"}},
                        "tags": {"type": "array", "items": {}},
                        "collections": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["item_key", "version"],
                    "additionalProperties": False,
                },
            ),
            ToolSpec(
                name="import_pdf",
                description="Link a PDF to an existing Zotero item, or create a new parent item from the PDF if item_key is omitted.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "item_key": {"type": "string"},
                        "pdf_path": {"type": "string"},
                        "title": {"type": "string"},
                        "content_type": {"type": "string"},
                        "doi": {"type": "string"},
                        "manual_fields": {"type": "object"},
                        "tags": {"type": "array", "items": {}},
                        "collections": {"type": "array", "items": {"type": "string"}},
                        "dedupe": {"type": "boolean", "default": True},
                    },
                    "required": ["pdf_path"],
                    "additionalProperties": False,
                },
            ),
            ToolSpec(
                name="create_note",
                description="Create a Markdown-backed child note under a Zotero item.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "item_key": {"type": "string"},
                        "markdown": {"type": "string"},
                        "title": {"type": "string"},
                    },
                    "required": ["item_key", "markdown"],
                    "additionalProperties": False,
                },
            ),
            ToolSpec(
                name="export_item",
                description="Export one item or a batch of items from Zotero into the local mirror.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "item_key": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "default": 200},
                        "start": {"type": "integer", "minimum": 0, "default": 0},
                        "include_notes": {"type": "boolean", "default": True},
                    },
                    "additionalProperties": False,
                },
            ),
        ]

    def _resource_specs(self) -> list[ResourceSpec]:
        return [
            ResourceSpec(
                uri=RESOURCE_SERVER_INFO_URI,
                name="Server Info",
                description="Static information about the Zotero MCP server, tools, and resource templates.",
            ),
            ResourceSpec(
                uri=RESOURCE_BRIDGE_HEALTH_URI,
                name="Bridge Health",
                description="Live health data from the local Zotero bridge.",
            ),
            ResourceSpec(
                uri=RESOURCE_BRIDGE_CAPABILITIES_URI,
                name="Bridge Capabilities",
                description="Current read/write/MCP capability flags from the local Zotero bridge.",
            ),
        ]

    def _resource_template_specs(self) -> list[ResourceTemplateSpec]:
        return [
            ResourceTemplateSpec(
                uri_template="zotero://items/{item_key}",
                name="Zotero Item",
                description="Read one Zotero item bundle by item key.",
            )
        ]

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        arguments = arguments or {}
        if name == "search_items":
            result = self.http_client.request("GET", "/items/search", params={"q": arguments["q"], "limit": arguments.get("limit", 20)})
        elif name == "create_item":
            result = self.http_client.request("POST", "/items", json_body=arguments)
        elif name == "update_item":
            item_key = arguments.get("item_key")
            if not item_key:
                raise BridgeError(422, "invalid_tool_arguments", "item_key is required")
            payload = dict(arguments)
            payload.pop("item_key", None)
            result = self.http_client.request("PATCH", f"/items/{item_key}", json_body=payload)
        elif name == "import_pdf":
            pdf_path = arguments.get("pdf_path")
            if not pdf_path:
                raise BridgeError(422, "invalid_tool_arguments", "pdf_path is required")
            item_key = arguments.get("item_key")
            if item_key:
                payload = {
                    "pdf_path": pdf_path,
                    "title": arguments.get("title"),
                    "content_type": arguments.get("content_type"),
                }
                result = self.http_client.request("POST", f"/items/{item_key}/attachments/linked-pdf", json_body=payload)
            else:
                payload = {
                    "pdf_path": pdf_path,
                    "doi": arguments.get("doi"),
                    "manual_fields": arguments.get("manual_fields"),
                    "tags": arguments.get("tags", []),
                    "collections": arguments.get("collections", []),
                    "dedupe": arguments.get("dedupe", True),
                }
                result = self.http_client.request("POST", "/items", json_body=payload)
        elif name == "create_note":
            item_key = arguments.get("item_key")
            if not item_key:
                raise BridgeError(422, "invalid_tool_arguments", "item_key is required")
            result = self.http_client.request(
                "POST",
                f"/items/{item_key}/notes",
                json_body={"markdown": arguments.get("markdown", ""), "title": arguments.get("title")},
            )
        elif name == "export_item":
            result = self.http_client.request("POST", "/sync/export", json_body=arguments)
        else:
            raise BridgeError(404, "unknown_tool", f"Unknown tool: {name}")
        return self._tool_success(result)

    def read_resource(self, uri: str) -> dict[str, Any]:
        if uri == RESOURCE_SERVER_INFO_URI:
            payload = {
                "serverInfo": {
                    "name": SERVER_NAME,
                    "version": SERVER_VERSION,
                    "protocolVersion": self.protocol_version,
                },
                "tools": self.list_tools(),
                "resources": self.list_resources(),
                "resourceTemplates": self.list_resource_templates(),
            }
        elif uri == RESOURCE_BRIDGE_HEALTH_URI:
            payload = self.http_client.request("GET", "/health")
        elif uri == RESOURCE_BRIDGE_CAPABILITIES_URI:
            payload = self.http_client.request("GET", "/capabilities")
        elif uri.startswith(RESOURCE_ITEM_URI_PREFIX):
            item_key = unquote(uri.removeprefix(RESOURCE_ITEM_URI_PREFIX))
            if not item_key:
                raise BridgeError(422, "invalid_resource_uri", "item_key is required")
            payload = self.http_client.request("GET", f"/items/{item_key}")
        else:
            raise BridgeError(404, "unknown_resource", f"Unknown resource: {uri}")
        return self._resource_success(uri, payload)

    def _tool_success(self, payload: Any) -> dict[str, Any]:
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(payload, ensure_ascii=False, indent=2),
                }
            ],
            "structuredContent": payload,
            "isError": False,
        }

    def _tool_error(self, exc: BridgeError) -> dict[str, Any]:
        payload = {
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
                "status_code": exc.status_code,
            }
        }
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(payload, ensure_ascii=False, indent=2),
                }
            ],
            "structuredContent": payload,
            "isError": True,
        }

    def _resource_success(self, uri: str, payload: Any) -> dict[str, Any]:
        return {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": "application/json",
                    "text": json.dumps(payload, ensure_ascii=False, indent=2),
                }
            ]
        }

    def _bridge_error_response(self, request_id: Any, exc: BridgeError) -> dict[str, Any]:
        return self._error_response(
            request_id,
            -32000,
            exc.message,
            {
                "code": exc.code,
                "details": exc.details,
                "status_code": exc.status_code,
            },
        )

    def handle_request(self, message: dict[str, Any]) -> dict[str, Any] | None:
        jsonrpc = message.get("jsonrpc")
        if jsonrpc != "2.0":
            return self._error_response(message.get("id"), -32600, "Invalid Request", {"reason": "jsonrpc must be 2.0"})

        method = message.get("method")
        params = message.get("params") or {}
        request_id = message.get("id")

        if method == "initialize":
            requested_version = params.get("protocolVersion")
            self.protocol_version = requested_version or DEFAULT_PROTOCOL_VERSION
            return self._success_response(
                request_id,
                {
                    "protocolVersion": self.protocol_version,
                    "capabilities": {
                        "tools": {"listChanged": False},
                        "resources": {"subscribe": False, "listChanged": False},
                    },
                    "serverInfo": {
                        "name": SERVER_NAME,
                        "version": SERVER_VERSION,
                    },
                },
            )
        if method == "notifications/initialized":
            return None
        if method == "ping":
            return self._success_response(request_id, {"ok": True})
        if method == "tools/list":
            return self._success_response(request_id, {"tools": self.list_tools()})
        if method == "resources/list":
            return self._success_response(request_id, {"resources": self.list_resources()})
        if method in {"resources/templates/list", "resourceTemplates/list"}:
            return self._success_response(request_id, {"resourceTemplates": self.list_resource_templates()})
        if method == "resources/read":
            uri = params.get("uri")
            if not uri:
                return self._error_response(request_id, -32602, "Invalid params", {"reason": "uri is required"})
            try:
                result = self.read_resource(uri)
            except BridgeError as exc:
                return self._bridge_error_response(request_id, exc)
            return self._success_response(request_id, result)
        if method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments") or {}
            if not name:
                return self._error_response(request_id, -32602, "Invalid params", {"reason": "name is required"})
            try:
                result = self.call_tool(name, arguments)
            except BridgeError as exc:
                result = self._tool_error(exc)
            return self._success_response(request_id, result)
        return self._error_response(request_id, -32601, "Method not found", {"method": method})

    def _success_response(self, request_id: Any, result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _error_response(self, request_id: Any, code: int, message: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        error = {"code": code, "message": message}
        if data:
            error["data"] = data
        return {"jsonrpc": "2.0", "id": request_id, "error": error}

    def _read_message(self) -> dict[str, Any] | None:
        headers: dict[str, str] = {}
        while True:
            line = self.input_stream.readline()
            if not line:
                return None if not headers else None
            if line in (b"\r\n", b"\n"):
                break
            decoded = line.decode("utf-8").strip()
            if not decoded:
                break
            key, _, value = decoded.partition(":")
            headers[key.strip().lower()] = value.strip()
        content_length = headers.get("content-length")
        if not content_length:
            raise ValueError("Missing Content-Length header")
        size = int(content_length)
        body = self.input_stream.read(size)
        if not body:
            return None
        return json.loads(body.decode("utf-8"))

    def _write_message(self, message: dict[str, Any]) -> None:
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        header = f"Content-Length: {len(payload)}\r\nContent-Type: application/json\r\n\r\n".encode("utf-8")
        self.output_stream.write(header)
        self.output_stream.write(payload)
        self.output_stream.flush()

    def _log_error(self, message: str) -> None:
        self.error_stream.write(f"{message}\n".encode("utf-8"))
        self.error_stream.flush()

    def serve_forever(self) -> None:
        while True:
            try:
                message = self._read_message()
            except json.JSONDecodeError as exc:
                self._write_message(self._error_response(None, -32700, "Parse error", {"error": str(exc)}))
                continue
            except Exception as exc:
                self._log_error(f"mcp read error: {exc}")
                self._write_message(self._error_response(None, -32603, "Internal error", {"error": str(exc)}))
                continue
            if message is None:
                return
            response = self.handle_request(message)
            if response is not None and "id" in response:
                self._write_message(response)


def default_http_base_url(settings: Settings) -> str:
    return f"http://{settings.host}:{settings.port}"


def build_server(base_url: str | None = None, token: str | None = None) -> ZoteroBridgeMCPServer:
    settings = Settings.from_env()
    client = BridgeHttpClient(base_url or default_http_base_url(settings), token or settings.api_token)
    return ZoteroBridgeMCPServer(client)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Zotero Agent Bridge MCP server")
    parser.add_argument("--base-url", dest="base_url", help="Bridge HTTP base URL")
    parser.add_argument("--token", dest="token", help="Bridge API token")
    args = parser.parse_args(argv)
    server = build_server(base_url=args.base_url, token=args.token)
    server.serve_forever()


if __name__ == "__main__":
    main()

"""FraudLens TigerGraph MCP server.

Default execution is a real line-delimited JSON-RPC MCP stdio boundary.  If
the official Python MCP SDK is importable, ``--protocol sdk`` (or ``auto``)
uses its ``FastMCP`` implementation instead.  No network listener is opened.
The local parquet backend is available only behind an explicit test flag.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, TextIO

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from graph_tools.backend import LocalParquetBackend, make_production_backend  # noqa: E402
from mcp.service import ToolService  # noqa: E402

PROTOCOL_VERSION = "2024-11-05"


class StdioJsonRpcServer:
    """Minimal MCP stdio server used when the optional SDK is unavailable."""

    def __init__(self, service: ToolService, input_stream: TextIO | None = None, output_stream: TextIO | None = None) -> None:
        self.service = service
        self.input = input_stream or sys.stdin
        self.output = output_stream or sys.stdout

    def _write(self, message: dict[str, Any]) -> None:
        self.output.write(json.dumps(message, separators=(",", ":"), default=str) + "\n")
        self.output.flush()

    def _result(self, request_id: Any, result: Any) -> None:
        self._write({"jsonrpc": "2.0", "id": request_id, "result": result})

    def _error(self, request_id: Any, code: int, message: str) -> None:
        self._write({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})

    def serve(self) -> int:
        for line in self.input:
            if not line.strip():
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError as exc:
                self._error(None, -32700, f"parse error: {exc}")
                continue
            request_id = request.get("id")
            method = request.get("method")
            params = request.get("params") or {}
            if method == "initialize":
                self._result(request_id, {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fraudlens-tigergraph", "version": "1"},
                })
            elif method in {"notifications/initialized", "initialized"}:
                continue
            elif method == "ping":
                self._result(request_id, {})
            elif method == "tools/list":
                self._result(request_id, {"tools": self.service.describe()})
            elif method == "tools/call":
                name = params.get("name")
                arguments = params.get("arguments") or {}
                try:
                    value = self.service.call(str(name), arguments)
                    self._result(request_id, {
                        "content": [{"type": "text", "text": json.dumps(value, default=str)}],
                        "structuredContent": value,
                        "isError": False,
                    })
                except Exception as exc:
                    # Tool failures are valid MCP tool results; malformed tool
                    # names/arguments are still visible to the caller.
                    self._result(request_id, {
                        "content": [{"type": "text", "text": json.dumps({"error": str(exc)})}],
                        "structuredContent": {"error": str(exc)},
                        "isError": True,
                    })
            elif request_id is not None:
                self._error(request_id, -32601, f"method not found: {method}")
        return 0


def _make_fastmcp(service: ToolService) -> Any:
    """Build an SDK server when the official ``mcp`` package is installed."""
    from mcp.server.fastmcp import FastMCP  # type: ignore

    server = FastMCP("fraudlens-tigergraph")
    for name in service.tool_names():
        function = getattr(service, name)
        function.__name__ = name
        server.tool()(function)
    return server


def _build_backend(args: argparse.Namespace) -> Any:
    if args.backend == "local-test":
        if not args.allow_local_test_backend or not args.case_store:
            raise SystemExit(
                "local-test backend is explicit: pass --allow-local-test-backend and --case-store"
            )
        return LocalParquetBackend(case_store_path=Path(args.case_store))
    return make_production_backend()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("tigergraph", "local-test"), default="tigergraph")
    parser.add_argument("--protocol", choices=("auto", "stdio", "sdk"), default="auto")
    parser.add_argument("--allow-local-test-backend", action="store_true")
    parser.add_argument("--case-store", help="explicit JSON store for local-test case writes")
    args = parser.parse_args()
    service = ToolService(_build_backend(args))
    if args.protocol in {"auto", "sdk"}:
        try:
            sdk_server = _make_fastmcp(service)
            print("using Python MCP SDK FastMCP over stdio", file=sys.stderr)
            sdk_server.run(transport="stdio")
            return 0
        except ImportError:
            if args.protocol == "sdk":
                raise SystemExit("Python MCP SDK is not installed; use --protocol stdio or install mcp")
            print("MCP SDK unavailable; using stdio JSON-RPC fallback", file=sys.stderr)
    return StdioJsonRpcServer(service).serve()


if __name__ == "__main__":
    raise SystemExit(main())

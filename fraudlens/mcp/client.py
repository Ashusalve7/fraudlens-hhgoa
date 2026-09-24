"""Clients for the FraudLens local MCP boundary.

``StdioMCPClient`` launches ``mcp/server.py`` as a child process and speaks
line-delimited MCP JSON-RPC over stdin/stdout.  It is a real process boundary;
it does not call graph methods in the agent process.  The SDK FastMCP server is
selected automatically by the child when the official Python SDK is installed.
``InProcessMCPClient`` is deliberately named and documented as test-only.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from mcp.service import ToolService

ROOT = Path(__file__).resolve().parent.parent
PROTOCOL_VERSION = "2024-11-05"


class MCPClientError(RuntimeError):
    """Transport or remote MCP tool failure."""


class StdioMCPClient:
    """Synchronous MCP client for a per-process stdio server."""

    def __init__(
        self,
        *,
        server_path: Path | None = None,
        backend: str = "tigergraph",
        protocol: str = "auto",
        case_store: Path | None = None,
        allow_local_test_backend: bool = False,
        env: dict[str, str] | None = None,
    ) -> None:
        self.server_path = Path(server_path or Path(__file__).with_name("server.py"))
        if not self.server_path.exists():
            raise MCPClientError(f"MCP server does not exist: {self.server_path}")
        if backend not in {"tigergraph", "local-test"}:
            raise ValueError("backend must be tigergraph or local-test")
        if backend == "local-test" and not allow_local_test_backend:
            raise ValueError("local-test backend requires allow_local_test_backend=True")
        if backend == "local-test" and case_store is None:
            raise ValueError("local-test backend requires an explicit case_store path")
        self.backend = backend
        self.protocol = protocol
        self.case_store = Path(case_store) if case_store else None
        self._env = {**os.environ, **(env or {})}
        self.process: subprocess.Popen[str] | None = None
        self._next_id = 1
        self._initialized = False

    def __enter__(self) -> "StdioMCPClient":
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def start(self) -> None:
        if self.process is not None:
            return
        command = [
            sys.executable,
            str(self.server_path),
            "--backend", self.backend,
            "--protocol", self.protocol,
        ]
        if self.backend == "local-test":
            command.extend(["--allow-local-test-backend", "--case-store", str(self.case_store)])
        try:
            self.process = subprocess.Popen(
                command,
                cwd=str(ROOT),
                env=self._env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
        except OSError as exc:
            raise MCPClientError(f"could not start MCP server: {exc}") from exc
        try:
            self._request("initialize", {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "fraudlens-client", "version": "1"},
            })
            self._notify("notifications/initialized", {})
            self._initialized = True
        except Exception:
            self.close()
            raise

    def _write(self, message: dict[str, Any]) -> None:
        if self.process is None or self.process.stdin is None:
            raise MCPClientError("MCP server is not started")
        try:
            self.process.stdin.write(json.dumps(message, separators=(",", ":"), default=str) + "\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise MCPClientError(f"MCP server stdin closed: {exc}") from exc

    def _read(self) -> dict[str, Any]:
        if self.process is None or self.process.stdout is None:
            raise MCPClientError("MCP server is not started")
        line = self.process.stdout.readline()
        if not line:
            stderr = ""
            if self.process.stderr is not None:
                stderr = self.process.stderr.read()
            raise MCPClientError(f"MCP server closed its stdout{(': ' + stderr[-500:]) if stderr else ''}")
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise MCPClientError(f"invalid MCP JSON-RPC response: {line[:300]}") from exc
        if not isinstance(value, dict):
            raise MCPClientError("MCP response is not an object")
        return value

    def _request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        request_id = self._next_id
        self._next_id += 1
        self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
        response = self._read()
        if response.get("id") != request_id:
            raise MCPClientError(f"MCP response id mismatch for {method}: {response}")
        if "error" in response:
            raise MCPClientError(f"MCP {method} failed: {response['error']}")
        return response.get("result")

    def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def list_tools(self) -> list[dict[str, Any]]:
        self.start()
        result = self._request("tools/list", {})
        return list(result.get("tools", [])) if isinstance(result, dict) else []

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        self.start()
        result = self._request("tools/call", {"name": name, "arguments": arguments or {}})
        if not isinstance(result, dict):
            raise MCPClientError(f"MCP tool {name} returned an invalid result")
        if result.get("isError"):
            text = ""
            for item in result.get("content", []):
                if isinstance(item, dict) and item.get("text"):
                    text = str(item["text"])
                    break
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict) and parsed.get("error"):
                    text = str(parsed["error"])
            except json.JSONDecodeError:
                pass
            raise MCPClientError(f"MCP tool {name} failed: {text or 'unknown error'}")
        if isinstance(result.get("structuredContent"), dict):
            return result["structuredContent"]
        for item in result.get("content", []):
            if isinstance(item, dict) and item.get("text"):
                try:
                    return json.loads(item["text"])
                except json.JSONDecodeError:
                    return item["text"]
        return result

    def close(self) -> None:
        process = self.process
        self.process = None
        self._initialized = False
        if process is None:
            return
        try:
            if process.stdin:
                process.stdin.close()
        except OSError:
            pass
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        finally:
            for stream in (process.stdout, process.stderr):
                try:
                    if stream:
                        stream.close()
                except OSError:
                    pass


class InProcessMCPClient:
    """Explicit test-only client that bypasses the MCP transport.

    This class is never selected by the production adapter.  It exists so
    algorithm and validation tests can run without a subprocess or a remote
    TigerGraph instance.
    """

    def __init__(self, backend: Any) -> None:
        self.service = ToolService(backend)
        self.calls: list[dict[str, Any]] = []

    def __enter__(self) -> "InProcessMCPClient":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        return None

    def list_tools(self) -> list[dict[str, Any]]:
        return self.service.describe()

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        self.calls.append({"tool": name, "arguments": arguments or {}})
        return self.service.call(name, arguments or {})

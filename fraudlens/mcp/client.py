"""Synchronous clients for the official FraudLens MCP stdio boundary."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from datetime import timedelta
from pathlib import Path
from typing import Any

from mcp.sdk_compat import configure_official_sdk

configure_official_sdk()

from mcp.client.session import ClientSession  # noqa: E402
from mcp.client.stdio import StdioServerParameters, stdio_client  # noqa: E402
from mcp.service import ToolService  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


class MCPClientError(RuntimeError):
    """Official SDK transport or remote MCP tool failure."""


def _error_text(result: Any) -> str:
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if not text:
            continue
        try:
            parsed = json.loads(str(text))
            if isinstance(parsed, dict) and parsed.get("error"):
                return str(parsed["error"])
        except json.JSONDecodeError:
            pass
        return str(text)
    return "unknown MCP tool error"


class StdioMCPClient:
    """Persistent official-SDK client with a synchronous facade.

    One MCP server process and one initialized ``ClientSession`` are retained
    for the lifetime of this object.  Calls from the synchronous agent thread
    are submitted to the client's private asyncio loop.
    """

    def __init__(
        self,
        *,
        server_path: Path | None = None,
        backend: str = "tigergraph",
        protocol: str = "sdk",
        case_store: Path | None = None,
        load_dir: Path | None = None,
        out_dir: Path | None = None,
        allow_local_test_backend: bool = False,
        env: dict[str, str] | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self.server_path = Path(server_path or Path(__file__).with_name("server.py"))
        if not self.server_path.exists():
            raise MCPClientError(f"MCP server does not exist: {self.server_path}")
        if backend not in {"tigergraph", "local-test"}:
            raise ValueError("backend must be tigergraph or local-test")
        if protocol != "sdk":
            raise ValueError("only the official MCP SDK protocol is supported")
        if backend == "local-test" and not allow_local_test_backend:
            raise ValueError("local-test backend requires allow_local_test_backend=True")
        if backend == "local-test" and load_dir is None:
            raise ValueError("local-test backend requires an explicit load_dir")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

        self.backend = backend
        self.case_store = Path(case_store) if case_store else None
        self.load_dir = Path(load_dir) if load_dir else None
        self.out_dir = Path(out_dir) if out_dir else None
        self.timeout_seconds = float(timeout_seconds)
        self._environment = {**os.environ, **{str(k): str(v) for k, v in (env or {}).items()}}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._session: ClientSession | None = None
        self._stop_event: asyncio.Event | None = None
        self._ready = threading.Event()
        self._failure: BaseException | None = None
        self._submit_lock = threading.Lock()

    def _parameters(self) -> StdioServerParameters:
        command = [
            sys.executable,
            str(self.server_path),
            "--backend",
            self.backend,
        ]
        if self.backend == "local-test":
            command.append("--allow-local-test-backend")
            command.extend(["--load-dir", str(self.load_dir)])
            if self.out_dir is not None:
                command.extend(["--out-dir", str(self.out_dir)])
            if self.case_store is not None:
                command.extend(["--case-store", str(self.case_store)])
        return StdioServerParameters(
            command=sys.executable,
            args=command[1:],
            env=self._environment,
            cwd=str(ROOT),
            encoding="utf-8",
            encoding_error_handler="replace",
        )

    async def _session_runner(self) -> None:
        try:
            async with (
                stdio_client(self._parameters(), errlog=sys.stderr) as streams,
                ClientSession(*streams) as session,
            ):
                await session.initialize()
                self._session = session
                self._stop_event = asyncio.Event()
                self._ready.set()
                await self._stop_event.wait()
        except BaseException as exc:  # surfaced synchronously by start/call
            self._failure = exc
            self._ready.set()
        finally:
            self._session = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._ready.clear()
        self._failure = None
        self._stop_event = None
        loop = asyncio.new_event_loop()
        self._loop = loop
        self._thread = threading.Thread(
            target=self._thread_main,
            name="fraudlens-mcp-client",
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(self.timeout_seconds):
            self.close()
            raise MCPClientError("timed out while starting the official MCP SDK session")
        if self._failure is not None or self._session is None:
            failure = self._failure
            self.close()
            raise MCPClientError(f"could not initialize official MCP SDK session: {failure}")

    def _thread_main(self) -> None:
        loop = self._loop
        if loop is None:
            return
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._session_runner())
        finally:
            loop.close()

    def _run(self, coroutine: Any) -> Any:
        try:
            self.start()
        except Exception:
            close = getattr(coroutine, "close", None)
            if callable(close):
                close()
            raise
        loop = self._loop
        if loop is None or self._session is None:
            close = getattr(coroutine, "close", None)
            if callable(close):
                close()
            raise MCPClientError("official MCP client session is not running")
        future: asyncio.Future[Any] | None = None
        try:
            with self._submit_lock:
                future = asyncio.run_coroutine_threadsafe(coroutine, loop)
                return future.result(timeout=self.timeout_seconds)
        except TimeoutError as exc:
            if future is not None:
                future.cancel()
            raise MCPClientError("official MCP SDK call timed out") from exc
        except MCPClientError:
            raise
        except Exception as exc:
            raise MCPClientError(f"official MCP SDK call failed: {exc}") from exc

    def list_tools(self) -> list[dict[str, Any]]:
        async def operation() -> list[dict[str, Any]]:
            assert self._session is not None
            result = await self._session.list_tools()
            return [tool.model_dump(by_alias=True, exclude_none=True) for tool in result.tools]

        return self._run(operation())

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        if not isinstance(name, str) or not name.strip():
            raise MCPClientError("MCP tool name must be a non-empty string")
        payload = arguments or {}
        if not isinstance(payload, dict):
            raise MCPClientError("MCP tool arguments must be an object")

        async def operation() -> Any:
            assert self._session is not None
            return await self._session.call_tool(
                name,
                payload,
                read_timeout_seconds=timedelta(seconds=self.timeout_seconds),
            )

        result = self._run(operation())
        if bool(getattr(result, "isError", False)):
            raise MCPClientError(f"MCP tool {name} failed: {_error_text(result)}")
        structured = getattr(result, "structuredContent", None)
        if isinstance(structured, dict):
            return structured
        for item in getattr(result, "content", []) or []:
            text = getattr(item, "text", None)
            if text is None:
                continue
            try:
                return json.loads(str(text))
            except json.JSONDecodeError:
                return str(text)
        return result.model_dump(by_alias=True, exclude_none=True)

    def close(self) -> None:
        loop, thread = self._loop, self._thread
        self._loop = None
        self._thread = None
        self._session = None
        if loop is None or thread is None:
            return

        stop_event = self._stop_event

        async def stop() -> None:
            if stop_event is not None:
                stop_event.set()

        if loop.is_running() and self._stop_event is not None:
            future = asyncio.run_coroutine_threadsafe(stop(), loop)
            try:
                future.result(timeout=3)
            except Exception:
                future.cancel()
                if not loop.is_closed():
                    loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)
        if thread.is_alive() and loop.is_running() and not loop.is_closed():
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=2)
        self._stop_event = None

    def __enter__(self) -> StdioMCPClient:
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()


class InProcessMCPClient:
    """Explicit test-only client that bypasses the MCP transport."""

    def __init__(self, backend: Any) -> None:
        self.service = ToolService(backend)
        self.calls: list[dict[str, Any]] = []

    def __enter__(self) -> InProcessMCPClient:
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        return None

    def list_tools(self) -> list[dict[str, Any]]:
        return self.service.describe()

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        self.calls.append({"tool": name, "arguments": arguments or {}})
        return self.service.call(name, arguments or {})

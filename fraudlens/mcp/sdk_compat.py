"""Make the official ``mcp`` SDK coexist with FraudLens' local package.

The application package is also named ``mcp``.  Python would therefore resolve
``mcp.server`` and ``mcp.client`` to the local modules instead of the official
SDK.  This helper puts the installed SDK package first while keeping local
modules such as ``mcp.service`` and ``mcp.agent_adapter`` importable.
"""
from __future__ import annotations

import importlib.metadata
import sys
from pathlib import Path
from types import ModuleType


class MCPSDKUnavailableError(RuntimeError):
    """The required official Python MCP SDK is not installed."""


def configure_official_sdk(*, official_first: bool = False) -> Path:
    """Expose the installed SDK beneath the already-loaded local ``mcp`` package."""
    try:
        distribution = importlib.metadata.distribution("mcp")
        official_root = Path(distribution.locate_file("mcp")).resolve()
    except importlib.metadata.PackageNotFoundError as exc:
        raise MCPSDKUnavailableError(
            "the official 'mcp' Python SDK is required; install the locked project dependencies"
        ) from exc
    if not (official_root / "__init__.py").is_file():
        raise MCPSDKUnavailableError(f"installed mcp distribution has no package at {official_root}")

    package = sys.modules.get("mcp")
    if not isinstance(package, ModuleType):
        raise MCPSDKUnavailableError("local mcp package was not initialized")
    package_paths = [str(value) for value in getattr(package, "__path__", [])]
    local_root = str(Path(__file__).resolve().parent)
    candidates = (
        (str(official_root), *package_paths, local_root)
        if official_first
        else (local_root, *package_paths, str(official_root))
    )
    reordered: list[str] = []
    for value in candidates:
        if value not in reordered:
            reordered.append(value)
    package.__path__ = reordered  # type: ignore[attr-defined]

    # When server.py/client.py are imported as mcp.server/mcp.client rather
    # than executed as scripts, turn those local modules into package shells
    # whose children come from the SDK.  Local classes remain available on the
    # original module object.
    for child in ("server", "client"):
        current = sys.modules.get(f"mcp.{child}")
        if isinstance(current, ModuleType) and not hasattr(current, "__path__"):
            current.__path__ = [str(official_root / child)]  # type: ignore[attr-defined]
    return official_root

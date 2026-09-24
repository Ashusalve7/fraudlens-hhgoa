"""MCP-mediated evidence access for the investigation engine and dashboard.

Production graph operations cross the official MCP boundary.  A connected
pyTigerGraph object is accepted only as an explicit compatibility path for
in-process tests; regular callers should construct ``Evidence()`` and let the
allow-listed MCP server own the graph connection.
"""

from __future__ import annotations

from typing import Any

from graph_tools.backend import TigerGraphBackend
from mcp.agent_adapter import Evidence as _MCPEvidence


class Evidence(_MCPEvidence):
    """Drop-in evidence facade that preserves the existing runner API."""

    def __init__(self, conn: Any | None = None, *, lazy: bool = True) -> None:
        self.conn = conn
        if conn is None:
            super().__init__(mode="mcp")
        else:
            super().__init__(
                mode="inprocess-test",
                backend=TigerGraphBackend(conn),
            )
        # ``lazy`` is retained for callers written against the previous facade.
        # The official MCP client starts safely on its first tool call.
        self.lazy = bool(lazy)


__all__ = ["Evidence"]

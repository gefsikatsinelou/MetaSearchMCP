"""MCP server entry-point wrapper around :mod:`metasearchmcp.broker`."""

from __future__ import annotations

from metasearchmcp.broker import run

if __name__ == "__main__":
    run()

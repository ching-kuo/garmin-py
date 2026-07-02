"""Per-domain MCP tool registrars.

``garmin_cli.mcp_server.create_mcp_server`` composes the tool surface by
calling each ``register_*_tools(mcp, config)`` in this package. Every module
binds the Garmin endpoint callables it uses at ITS own module scope so the test
suite can monkeypatch them there (e.g. ``garmin_cli.mcp_tools.health.get_sleep``).
Shared infrastructure (auth wrapper, envelope, validation, report fan-out) lives
in :mod:`garmin_cli.mcp_tools._shared`.
"""
from __future__ import annotations

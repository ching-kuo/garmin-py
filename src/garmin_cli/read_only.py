"""MCP read-only mode setting shared by ``mcp-server`` and ``doctor``."""
from __future__ import annotations

READ_ONLY_ENV = "GARMIN_MCP_READ_ONLY"
# click's boolean vocabulary for the --read-only flag's environment value;
# doctor checks the variable with the same words.
READ_ONLY_TRUE = frozenset({"1", "true", "t", "yes", "y", "on"})
READ_ONLY_FALSE = frozenset({"", "0", "false", "f", "no", "n", "off"})

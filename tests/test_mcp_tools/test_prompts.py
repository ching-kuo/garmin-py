"""MCP prompt inventory and tool-reference drift tests."""
from __future__ import annotations

import asyncio
import re
from typing import Any

import pytest

pytest.importorskip("mcp", reason="mcp extra not installed")

from garmin_cli.mcp_server import create_mcp_server  # noqa: E402
from tests.test_mcp_tools.support import _config  # noqa: E402

_TOOL_REFERENCE = re.compile(r"`([a-z][a-z0-9_]+)`")


def _prompt_text(server: Any, name: str) -> str:
    result = asyncio.run(server.get_prompt(name, {}))
    return result.messages[0].content.text


def test_server_lists_exactly_four_prompts() -> None:
    server = create_mcp_server(_config())

    prompts = asyncio.run(server.list_prompts())

    assert {prompt.name for prompt in prompts} == {
        "weekly_training_review",
        "recovery_check",
        "compare_recent_activities",
        "plan_next_week",
    }


def test_every_prompt_tool_reference_is_registered() -> None:
    server = create_mcp_server(_config())
    registered = {tool.name for tool in asyncio.run(server.list_tools())}

    for prompt in asyncio.run(server.list_prompts()):
        references = set(_TOOL_REFERENCE.findall(_prompt_text(server, prompt.name)))
        assert references
        assert references <= registered


def test_plan_prompt_requires_confirmation_before_apply() -> None:
    text = _prompt_text(create_mcp_server(_config()), "plan_next_week")

    assert "`training_plan_preview`" in text
    assert "`training_plan_apply`" in text
    assert "explicit human confirmation" in text

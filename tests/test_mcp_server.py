"""Smoke test: all tools register over MCP with sane schemas.

Behavior is tested at the service seam; nothing behavioral goes through the
transport.
"""

import asyncio
from pathlib import Path

from conftest import make_service
from homelore.mcp_server import build_server


def test_tools_register_with_sane_schemas(tmp_path: Path) -> None:
    service, _ = make_service(tmp_path, vectors={})
    server = build_server(service)

    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}

    assert set(tools) == {"remember", "recall", "profile", "upcoming_dates"}
    assert all(tool.description for tool in tools.values())

    remember_schema = tools["remember"].inputSchema
    assert set(remember_schema["required"]) == {"text", "author"}
    assert "event_date" in remember_schema["properties"]

    recall_schema = tools["recall"].inputSchema
    assert "query" in recall_schema["required"]
    assert "limit" in recall_schema["properties"]

    profile = tools["profile"]
    assert "name" in profile.inputSchema["required"]
    # The client model routes on descriptions; "who is" must lead here.
    assert profile.description is not None
    assert "who is" in profile.description.lower()

    upcoming = tools["upcoming_dates"]
    assert "days" in upcoming.inputSchema["properties"]
    assert upcoming.inputSchema.get("required", []) == []
    # Date questions must route here, never to recall.
    assert upcoming.description is not None
    assert "coming up" in upcoming.description.lower()

"""Smoke test: both tools register over MCP with sane schemas.

Behavior is tested at the service seam; nothing behavioral goes through the
transport.
"""

import asyncio
from pathlib import Path

from conftest import make_service
from homelore.mcp_server import build_server


def test_remember_and_recall_register_with_sane_schemas(tmp_path: Path) -> None:
    service, _ = make_service(tmp_path, vectors={})
    server = build_server(service)

    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}

    assert set(tools) == {"remember", "recall"}
    assert all(tool.description for tool in tools.values())

    remember_schema = tools["remember"].inputSchema
    assert set(remember_schema["required"]) == {"text", "author"}
    assert "event_date" in remember_schema["properties"]

    recall_schema = tools["recall"].inputSchema
    assert "query" in recall_schema["required"]
    assert "limit" in recall_schema["properties"]

from datetime import date
from typing import Any

from mcp.server.fastmcp import FastMCP

from homelore.service import HomeloreService


def build_server(service: HomeloreService) -> FastMCP:
    """Expose the application service over MCP. No logic here beyond translation."""
    server = FastMCP("homelore")

    @server.tool()
    def remember(  # pyright: ignore[reportUnusedFunction]
        text: str, author: str, event_date: str | None = None
    ) -> dict[str, Any]:
        """Save a family memory: a fact, moment, preference, or anything worth
        keeping ("Mia moved up to shoe size 32"). Use whenever the user shares
        something about their family worth remembering. Pass the user's name as
        author. If the memory describes a past event ("last summer we…"), pass
        the date it happened as event_date (YYYY-MM-DD); otherwise omit it.
        """
        memory = service.remember(
            text,
            author=author,
            event_date=date.fromisoformat(event_date) if event_date else None,
        )
        return {"saved": True, "date": memory.happened_on.isoformat()}

    @server.tool()
    def recall(  # pyright: ignore[reportUnusedFunction]
        query: str, limit: int = 5
    ) -> list[dict[str, Any]]:
        """Search saved family memories to answer a specific question ("what
        size shoes does Mia wear?"). Returns the most relevant memories, each
        with its text, the date it happened, and who recorded it — cite these
        when answering so the user can judge freshness.
        """
        return [
            {
                "text": result.memory.text,
                "date": result.memory.happened_on.isoformat(),
                "author": result.memory.author,
            }
            for result in service.recall(query, limit=limit)
        ]

    return server

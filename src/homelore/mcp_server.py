from datetime import date
from typing import Any

from mcp.server.fastmcp import FastMCP

from homelore.domain import Memory
from homelore.service import HomeloreService


def _memory_payload(memory: Memory) -> dict[str, Any]:
    return {
        "text": memory.text,
        "date": memory.happened_on.isoformat(),
        "author": memory.author,
    }


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
        result = service.remember(
            text,
            author=author,
            event_date=date.fromisoformat(event_date) if event_date else None,
        )
        payload: dict[str, Any] = {"saved": True, "date": result.memory.happened_on.isoformat()}
        if result.extraction_pending:
            payload["note"] = (
                "The memory is saved, but understanding it (who and what it is"
                " about) failed and will be retried automatically."
            )
        return payload

    @server.tool()
    def recall(  # pyright: ignore[reportUnusedFunction]
        query: str, limit: int = 5
    ) -> list[dict[str, Any]]:
        """Search saved family memories to answer a specific question ("what
        size shoes does Mia wear?"). Returns the most relevant memories, each
        with its text, the date it happened, and who recorded it — cite these
        when answering so the user can judge freshness.
        """
        return [_memory_payload(result.memory) for result in service.recall(query, limit=limit)]

    @server.tool()
    def profile(name: str) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        """Everything known about one person, place, or thing. Use for
        "who is X?", "tell me about X", or catching up on someone. Accepts any
        name or alias the family uses ("Ana", "my wife", "grandma"). Returns
        their known names, their relationships, and the memories behind each
        claim — cite dates and authors so the user can judge freshness.
        """
        result = service.profile(name)
        if result is None:
            return {"found": False, "note": f"Nothing is known yet about {name!r}."}
        return {
            "found": True,
            "name": result.entity.name,
            "aliases": list(result.entity.aliases),
            "relations": [
                {
                    "subject": supported.relation.subject,
                    "label": supported.relation.label,
                    "object": supported.relation.object,
                    "memories": [_memory_payload(memory) for memory in supported.memories],
                }
                for supported in result.relations
            ],
            "memories": [_memory_payload(memory) for memory in result.memories],
        }

    return server

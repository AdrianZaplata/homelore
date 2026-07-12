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
    def upcoming_dates(days: int = 30) -> list[dict[str, Any]]:  # pyright: ignore[reportUnusedFunction]
        """What family dates are coming up: birthdays, anniversaries, and other
        special dates from today through `days` days out (inclusive), soonest
        first. The answer is exact and complete — always use this for date
        questions ("any birthdays soon?"), never recall. `years` is the age
        being turned or the anniversary number, present when the first year is
        known.
        """
        return [
            {
                "entity": upcoming.entity,
                "occasion": upcoming.label,
                "date": upcoming.occurs_on.isoformat(),
                **({"years": upcoming.years} if upcoming.years is not None else {}),
            }
            for upcoming in service.upcoming_dates(days=days)
        ]

    @server.tool()
    def reflect() -> list[dict[str, Any]]:  # pyright: ignore[reportUnusedFunction]
        """Look across the whole family history to answer broad, reflective
        questions no single memory can ("how has our year been?", "what
        themes keep coming up with the kids?"). Returns one summary per
        cluster of family life, each grounded in the underlying memories —
        synthesize your answer from them and nothing else. For a specific
        factual question ("what's Mia's shoe size?") use recall instead; for
        date questions use upcoming_dates.
        """
        return [
            {"about": list(community.entities), "summary": community.summary}
            for community in service.reflect()
        ]

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

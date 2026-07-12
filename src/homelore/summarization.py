from collections.abc import Sequence

import anthropic

from homelore.domain import Memory

MODEL = "claude-haiku-4-5"

_SYSTEM = """\
You write a Community Summary: a short synthesis of one cluster of a family's memories, \
all revolving around the same circle of people, places, and interests.

Describe what these memories say as a whole — the themes, how things changed over time, and \
the moments that stand out. Ground every statement in the memories provided: never invent \
facts, dates, or people, and leave out anything the memories do not say. Write a short \
flowing paragraph, not a list.
"""


class ClaudeSummarizer:
    """Community summaries against Claude Haiku 4.5, plain text output.

    Errors propagate — summaries are derived and rebuildable, so a failed
    refresh costs nothing but the retry on the next reflect.
    """

    def __init__(self) -> None:
        self._client = anthropic.Anthropic()

    def summarize(self, entities: Sequence[str], memories: Sequence[Memory]) -> str:
        response = self._client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=_SYSTEM,
            messages=[{"role": "user", "content": _prompt(entities, memories)}],
        )
        return next(block.text for block in response.content if block.type == "text")


def _prompt(entities: Sequence[str], memories: Sequence[Memory]) -> str:
    lines = "\n".join(
        f"- {memory.happened_on.isoformat()} ({memory.author}): {memory.text}"
        for memory in memories
    )
    return f"This cluster is about: {', '.join(entities)}.\n\nMemories, oldest first:\n{lines}"

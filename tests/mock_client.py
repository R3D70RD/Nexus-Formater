"""A fake LLM backend for exercising the pipeline without a real Ollama
server. Implements the same `.chat(system_prompt, user_prompt) -> str`
interface as OllamaClient so it can be swapped in via dependency injection."""
from __future__ import annotations

import re

from nexus_formatter.ollama_client import OllamaError

NOTE_RE = re.compile(
    r'>>>NOTE_START id=(\d{4}) file="([^"]*)"<<<\n(.*?)\n>>>NOTE_END id=\1<<<',
    re.DOTALL,
)


class MockOllamaClient:
    """Echoes back a plausible atomic note for each note in the prompt.

    drop_ids: note ids to silently omit from the response, simulating a
        model that "forgets" a note in a batch (exercises the fallback
        to individual processing).
    """

    def __init__(self, drop_ids=None):
        self.drop_ids = set(drop_ids or [])
        self.calls = 0

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        out = []
        for m in NOTE_RE.finditer(user_prompt):
            note_id, filename, content = int(m.group(1)), m.group(2), m.group(3)
            if note_id in self.drop_ids:
                continue
            title = filename.rsplit(".", 1)[0]
            out.append(
                f'>>>NOTE_START id={note_id:04d} file="{filename}"<<<\n'
                f'---\n'
                f'type: concept\n'
                f'domain: networking\n'
                f'tags:\n  - {title.lower()}\n'
                f'aliases:\n  - {title}\n'
                f'---\n\n'
                f'# {title}\n\n'
                f'## Purpose\n'
                f'Explains {title}, derived from: {content.strip()[:40]}...\n\n'
                f'## Key Ideas\n- Core point about {title}\n\n'
                f'## Related Concepts\n- [[Networking]]\n\n'
                f'## Search Keywords\n{title}, {title.lower()}\n\n'
                f'>>>QUALITY_RATING<<<\n'
                f'Rating: 8/10\n'
                f'Missing: nothing major.\n'
                f'>>>NOTE_END id={note_id:04d}<<<'
            )
        return "\n\n".join(out)


class AlwaysFailClient:
    """Simulates a fully unreachable / broken Ollama server."""

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        raise OllamaError("server is down")

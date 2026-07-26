"""Dependency-free progress indicator for the terminal."""
from __future__ import annotations

import sys


class Progress:
    def __init__(self, total: int, width: int = 30):
        self.total = max(total, 1)
        self.width = width
        self.count = 0

    def note(self, message: str) -> None:
        sys.stdout.write(f"\n{message}\n")
        self._render()

    def advance(self) -> None:
        self.count += 1
        self._render()

    def _render(self) -> None:
        filled = int(self.width * self.count / self.total)
        bar = "#" * filled + "-" * (self.width - filled)
        pct = int(100 * self.count / self.total)
        sys.stdout.write(f"\r[{bar}] {self.count}/{self.total} ({pct}%)")
        sys.stdout.flush()

    def done(self) -> None:
        sys.stdout.write("\n")
        sys.stdout.flush()

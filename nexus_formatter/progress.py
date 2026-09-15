"""Terminal progress indicator (Rich when the output is a TTY)."""
from __future__ import annotations

import sys

from rich.console import Console
from rich.progress import BarColumn, Progress as RichProgress, TextColumn, TimeElapsedColumn


class Progress:
    def __init__(self, total: int, width: int = 30):
        self.total = max(total, 1)
        self.width = width
        self.count = 0
        self._tty = sys.stderr.isatty()
        self._rich = None
        self._task = None
        if self._tty:
            self._rich = RichProgress(
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("{task.completed}/{task.total}"),
                TimeElapsedColumn(),
                console=Console(stderr=True),
                transient=False,
            )
            self._rich.start()
            self._task = self._rich.add_task("Working", total=self.total)
        else:
            self._render()

    def note(self, message: str) -> None:
        if self._rich is not None:
            self._rich.console.print(message)
            self._rich.update(self._task, description=message[:60])
        else:
            sys.stdout.write(f"\n{message}\n")
            self._render()

    def advance(self) -> None:
        self.count += 1
        if self._rich is not None:
            self._rich.advance(self._task)
        else:
            self._render()

    def _render(self) -> None:
        filled = int(self.width * self.count / self.total)
        bar = "#" * filled + "-" * (self.width - filled)
        pct = int(100 * self.count / self.total)
        sys.stdout.write(f"\r[{bar}] {self.count}/{self.total} ({pct}%)")
        sys.stdout.flush()

    def done(self) -> None:
        if self._rich is not None:
            self._rich.stop()
        else:
            sys.stdout.write("\n")
            sys.stdout.flush()

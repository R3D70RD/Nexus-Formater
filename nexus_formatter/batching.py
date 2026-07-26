"""Greedy batching so tiny notes (TCP.md, UDP.md, DNS.md, ...) get packed
into one LLM request, while large notes are sent alone."""
from __future__ import annotations

from pathlib import Path
from typing import List


def build_batches(files: List[Path], max_notes: int, max_chars: int) -> List[List[Path]]:
    batches: List[List[Path]] = []
    current: List[Path] = []
    current_chars = 0

    for f in files:
        try:
            size = f.stat().st_size
        except OSError:
            size = 0

        over_count = len(current) >= max_notes
        over_chars = bool(current) and (current_chars + size > max_chars)
        if current and (over_count or over_chars):
            batches.append(current)
            current, current_chars = [], 0

        current.append(f)
        current_chars += size

    if current:
        batches.append(current)
    return batches

"""Builds the marker-delimited prompt sent to the LLM, and parses the
marker-delimited response back into per-note content + frontmatter."""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Dict, Optional, Tuple

import yaml

NOTE_RE = re.compile(
    r'>>>NOTE_START\s+id=(\d{4})[^\n<]*<<<(.*?)>>>NOTE_END\s+id=\1<<<',
    re.DOTALL,
)
FRONTMATTER_RE = re.compile(r'^---\s*\n(.*?)\n---\s*\n?(.*)$', re.DOTALL)
FENCED_BLOCK_RE = re.compile(r'^```[^\n]*\n(.*?)\n```\s*$', re.DOTALL)
QUALITY_MARKER = ">>>QUALITY_RATING<<<"
RATING_RE = re.compile(r'Rating:\s*(\d+(?:\.\d+)?)\s*/\s*10', re.IGNORECASE)

# Bump when the output contract in prompt_template.md changes in a way the
# parser needs to know about. Kept here so tests can assert on it.
PROMPT_VERSION = 2


def build_user_prompt(batch: Dict[int, Path]) -> str:
    parts = []
    for note_id, path in batch.items():
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = path.read_text(encoding="utf-8", errors="replace")
        parts.append(
            f'>>>NOTE_START id={note_id:04d} file="{path.name}"<<<\n'
            f'{content.strip()}\n'
            f'>>>NOTE_END id={note_id:04d}<<<'
        )
    return "\n\n".join(parts)


def strip_code_fences(text: str) -> str:
    """Remove a single wrapping ```...``` fence if the whole text is fenced.

    Models frequently wrap their output in a fence despite instructions not
    to. Only unwraps when the fence spans the entire (stripped) text, so
    legitimate fenced code inside a note body is left alone.
    """
    stripped = text.strip()
    m = FENCED_BLOCK_RE.match(stripped)
    if m:
        return m.group(1).strip()
    return stripped


def is_empty_note(text: str) -> bool:
    """True if a note body is empty or whitespace-only (after fence stripping)."""
    return not strip_code_fences(text).strip()


def parse_batch_response(raw: str, batch: Dict[int, Path]) -> Dict[int, str]:
    results = {}
    for m in NOTE_RE.finditer(raw):
        note_id = int(m.group(1))
        if note_id in batch:
            results[note_id] = strip_code_fences(m.group(2))
    return results


def split_quality(note_text: str) -> Tuple[str, str]:
    if QUALITY_MARKER in note_text:
        body, quality = note_text.split(QUALITY_MARKER, 1)
        return body.strip(), quality.strip()
    return note_text.strip(), ""


def extract_rating(quality_text: str) -> Optional[float]:
    m = RATING_RE.search(quality_text)
    return float(m.group(1)) if m else None


def split_frontmatter(note_body: str) -> Tuple[dict, str]:
    note_body = strip_code_fences(note_body)
    m = FRONTMATTER_RE.match(note_body)
    if not m:
        return {}, note_body.strip()
    try:
        fm = yaml.safe_load(m.group(1)) or {}
        if not isinstance(fm, dict):
            fm = {}
    except yaml.YAMLError:
        fm = {}
    return fm, m.group(2).strip()


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def normalize_frontmatter(fm: dict, source_rel_path: str, quality_text: str, parse_ok: bool) -> dict:
    """Merge LLM-provided metadata with script-controlled, trustworthy fields.

    `source` and `created` are set by the script, never trusted from the
    model, so they can't be hallucinated.
    """
    rating = extract_rating(quality_text)
    needs_review = (not parse_ok) or (rating is not None and rating < 6)

    return {
        "type": fm.get("type", "concept"),
        "domain": fm.get("domain", "general"),
        "tags": _as_list(fm.get("tags")),
        "aliases": _as_list(fm.get("aliases")),
        "source": source_rel_path,
        "created": date.today().isoformat(),
        "needs_review": needs_review,
    }


def render_note(frontmatter: dict, body: str) -> str:
    fm_yaml = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True, default_flow_style=False)
    return f"---\n{fm_yaml}---\n\n{body.strip()}\n"

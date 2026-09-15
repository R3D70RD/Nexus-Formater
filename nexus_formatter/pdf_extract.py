"""Faithful PDF → Markdown/text extraction (no LLM).

Text is reconstructed from glyph positions so the output matches the PDF
layout as closely as a copy-paste would, including accented characters
that PDFs often store as a base letter plus a separate overlay mark.
"""
from __future__ import annotations

import logging
import unicodedata
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import pymupdf as fitz

logger = logging.getLogger(__name__)

PDF_FLAGS = fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_MEDIABOX_CLIP
if hasattr(fitz, "TEXT_ACCURATE_BBOXES"):
    PDF_FLAGS |= fitz.TEXT_ACCURATE_BBOXES

# Spacing (non-combining) accents that PDFs often paint on top of a letter.
SPACING_TO_COMBINING = {
    "\u00b4": "\u0301",  # ´ acute
    "\u02ca": "\u0301",
    "\u0060": "\u0300",  # ` grave
    "\u02cb": "\u0300",
    "\u02c6": "\u0302",  # ˆ circumflex
    "\u005e": "\u0302",  # ^
    "\u00a8": "\u0308",  # ¨ diaeresis
    "\u02dc": "\u0303",  # ˜ tilde
    "\u007e": "\u0303",  # ~
    "\u00b8": "\u0327",  # ¸ cedilla
    "\u02d9": "\u0307",  # dot above
    "\u02da": "\u030a",  # ring
    "\u02c7": "\u030c",  # caron
    "\u02d8": "\u0306",  # breve
    "\u00af": "\u0304",  # macron
    "\u02c9": "\u0304",
}

BBox = Tuple[float, float, float, float]


class ExtractError(Exception):
    """Raised when a PDF cannot be opened or extracted."""


def default_output_dir(source: Path) -> Path:
    """Sibling folder next to the original PDF folder, named ``<folder>_extracted``."""
    src = source.expanduser().resolve()
    folder = src.parent if src.is_file() else src
    return folder.parent / f"{folder.name}_extracted"


def discover_pdfs(source: Path) -> Tuple[Path, List[Path]]:
    """Return ``(root, pdfs)``. ``root`` is the directory used for relative paths."""
    src = source.expanduser().resolve()
    if src.is_file():
        if src.suffix.lower() != ".pdf":
            raise ExtractError(f"Not a PDF file: {src}")
        return src.parent, [src]
    if not src.is_dir():
        raise ExtractError(f"Input path does not exist: {src}")
    pdfs = sorted(
        p for p in src.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf"
    )
    return src, pdfs


def output_path_for(pdf: Path, root: Path, output_dir: Path, extension: str) -> Path:
    rel = pdf.relative_to(root)
    return (output_dir / rel).with_suffix(extension)


def extract_pdf(path: Path) -> str:
    """Return the PDF's text, page-for-page, with layout and Unicode preserved."""
    try:
        doc = fitz.open(path)
    except Exception as e:
        raise ExtractError(f"Could not open {path}: {e}") from e

    try:
        if doc.is_encrypted and not doc.authenticate(""):
            raise ExtractError(f"Password-protected PDF (no empty password): {path}")
        pages = [_extract_page(page) for page in doc]
    finally:
        doc.close()

    body = "\n\n---\n\n".join(p for p in pages if p.strip() or p == "")
    return unicodedata.normalize("NFC", body).rstrip() + "\n"


def run_extract(
    source: Path,
    output_dir: Optional[Path] = None,
    extension: str = ".md",
    force: bool = False,
    dry_run: bool = False,
    only: Optional[str] = None,
    on_file=None,
) -> dict:
    """Extract every PDF under ``source`` into ``output_dir``.

    ``on_file(pdf, dest, status)`` is an optional callback. Status is one of
    ``extracted``, ``skipped``, ``failed``, ``would-extract``.
    """
    if not extension.startswith("."):
        extension = f".{extension}"
    if extension not in (".md", ".txt"):
        raise ExtractError(f"Unsupported output extension: {extension}")

    root, pdfs = discover_pdfs(source)
    if only:
        pdfs = [p for p in pdfs if p.name == only or p.stem == only]
    dest_root = (output_dir or default_output_dir(source)).expanduser().resolve()

    stats = {
        "success": 0,
        "failed": 0,
        "skipped": 0,
        "total": len(pdfs),
        "output_dir": dest_root,
        "root": root,
    }

    if not pdfs:
        logger.info("No PDF files found in %s", source)
        return stats

    if not dry_run:
        dest_root.mkdir(parents=True, exist_ok=True)

    for pdf in pdfs:
        dest = output_path_for(pdf, root, dest_root, extension)
        rel = str(pdf.relative_to(root))

        if not force and dest.exists() and dest.stat().st_mtime >= pdf.stat().st_mtime:
            stats["skipped"] += 1
            logger.debug("SKIP  %s (already extracted)", rel)
            if on_file:
                on_file(pdf, dest, "skipped")
            else:
                logger.info("SKIP  %s (already extracted)", rel)
            continue

        if dry_run:
            stats["success"] += 1
            logger.debug("[dry-run] would extract %s -> %s", rel, dest)
            if on_file:
                on_file(pdf, dest, "would-extract")
            else:
                logger.info("[dry-run] would extract %s -> %s", rel, dest)
            continue

        try:
            text = extract_pdf(pdf)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text, encoding="utf-8")
            stats["success"] += 1
            logger.debug("OK    %s -> %s", rel, dest.relative_to(dest_root))
            if on_file:
                on_file(pdf, dest, "extracted")
            else:
                logger.info("OK    %s -> %s", rel, dest.relative_to(dest_root))
        except Exception as e:
            stats["failed"] += 1
            logger.error("FAIL  %s -- %s", rel, e)
            if on_file:
                on_file(pdf, dest, "failed")

    return stats


def _extract_page(page) -> str:
    data = page.get_text("rawdict", flags=PDF_FLAGS, sort=True)
    lines_out: List[str] = []
    prev_y1: Optional[float] = None
    prev_height: float = 12.0

    for block in data.get("blocks") or []:
        if block.get("type") != 0:
            continue
        for line in block.get("lines") or []:
            chars = _line_chars(line)
            if not chars:
                continue
            y0 = min(c["bbox"][1] for c in chars)
            y1 = max(c["bbox"][3] for c in chars)
            height = max(y1 - y0, 1.0)
            if prev_y1 is not None:
                gap = y0 - prev_y1
                if gap > prev_height * 1.6:
                    extra = min(4, max(1, round(gap / prev_height) - 1))
                    lines_out.extend([""] * extra)
            lines_out.append(_reconstruct_line(_merge_diacritics(chars)))
            prev_y1 = y1
            prev_height = height

    return "\n".join(lines_out).rstrip()


def _line_chars(line: dict) -> List[dict]:
    chars: List[dict] = []
    for span in line.get("spans") or []:
        for ch in span.get("chars") or []:
            c = ch.get("c") or ""
            if not c:
                continue
            bbox = tuple(ch["bbox"])
            chars.append({"c": c, "bbox": bbox})
        if not span.get("chars") and span.get("text"):
            bbox = tuple(span["bbox"])
            chars.append({"c": span["text"], "bbox": bbox})
    return chars


def _is_diacritic(ch: str) -> bool:
    if len(ch) != 1:
        return False
    if unicodedata.category(ch) in ("Mn", "Me"):
        return True
    return ch in SPACING_TO_COMBINING


def _as_combining(ch: str) -> str:
    if unicodedata.category(ch) in ("Mn", "Me"):
        return ch
    return SPACING_TO_COMBINING.get(ch, ch)


def _overlap_x(a: BBox, b: BBox) -> bool:
    overlap = min(a[2], b[2]) - max(a[0], b[0])
    width = max(min(a[2] - a[0], b[2] - b[0]), 0.5)
    return overlap > width * 0.15


def _center_x(b: BBox) -> float:
    return (b[0] + b[2]) / 2.0


def _merge_diacritics(chars: Sequence[dict]) -> List[dict]:
    """Attach overlay/combining marks to the letter they sit on, then NFC."""
    bases: List[dict] = []
    marks: List[dict] = []
    for ch in chars:
        if _is_diacritic(ch["c"]):
            marks.append(ch)
        else:
            bases.append(dict(ch))

    if not marks:
        return [dict(ch) for ch in chars]

    if not bases:
        return [dict(ch) for ch in chars]

    for mark in marks:
        mb = mark["bbox"]
        best_i = None
        best_dist = None
        for i, base in enumerate(bases):
            bb = base["bbox"]
            if not _overlap_x(mb, bb):
                continue
            dist = abs(_center_x(mb) - _center_x(bb))
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_i = i
        if best_i is None:
            bases.append({"c": mark["c"], "bbox": mark["bbox"]})
            continue
        combined = unicodedata.normalize("NFC", bases[best_i]["c"] + _as_combining(mark["c"]))
        bases[best_i]["c"] = combined

    bases.sort(key=lambda ch: (ch["bbox"][0], ch["bbox"][1]))
    return bases


def _reconstruct_line(chars: Iterable[dict]) -> str:
    chars = list(chars)
    if not chars:
        return ""
    parts: List[str] = []
    prev = chars[0]
    parts.append(prev["c"])
    for ch in chars[1:]:
        gap = ch["bbox"][0] - prev["bbox"][2]
        prev_w = max(prev["bbox"][2] - prev["bbox"][0], 1.0)
        cur_w = max(ch["bbox"][2] - ch["bbox"][0], 1.0)
        avg_w = max((prev_w + cur_w) / 2.0, 2.0)
        already_space = prev["c"][-1:].isspace() or ch["c"][:1].isspace()
        if not already_space and gap > avg_w * 0.35:
            n = min(24, max(1, round(gap / (avg_w * 0.55))))
            parts.append(" " * n)
        parts.append(ch["c"])
        prev = ch
    return unicodedata.normalize("NFC", "".join(parts)).rstrip()


def extract_format_from_name(name: str) -> str:
    mapping: Dict[str, str] = {"md": ".md", "markdown": ".md", "txt": ".txt", "text": ".txt"}
    key = name.lower().lstrip(".")
    if key not in mapping:
        raise ExtractError(f"Unknown extract format {name!r} (use md or txt)")
    return mapping[key]

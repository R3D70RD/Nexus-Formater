"""PDF extraction: Unicode accents, layout fidelity, sibling output folder."""
from pathlib import Path

import pymupdf as fitz
import pytest

from nexus_formatter.pdf_extract import (
    ExtractError,
    _as_combining,
    _merge_diacritics,
    default_output_dir,
    extract_format_from_name,
    extract_pdf,
    output_path_for,
    run_extract,
)


def _write_pdf(path: Path, lines, overlay=None):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    y = 72
    for line in lines:
        page.insert_text((72, y), line, fontsize=12, fontname="helv")
        y += 18
    if overlay:
        for x, oy, text in overlay:
            page.insert_text((x, oy), text, fontsize=12, fontname="helv")
    doc.save(path)
    doc.close()


def test_default_output_dir_is_sibling_of_original_folder(tmp_path):
    src = tmp_path / "lectures_pdf"
    src.mkdir()
    assert default_output_dir(src) == tmp_path / "lectures_pdf_extracted"

    pdf = src / "chap1.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    assert default_output_dir(pdf) == tmp_path / "lectures_pdf_extracted"


def test_extracts_french_accents_nfc(tmp_path):
    src = tmp_path / "pdfs"
    src.mkdir()
    pdf = src / "accents.pdf"
    sample = "élève café forêt naïve où déjà être français"
    _write_pdf(pdf, [sample, "être / être : ê è é ë"])

    text = extract_pdf(pdf)
    assert "élève" in text
    assert "café" in text
    assert "forêt" in text
    assert "naïve" in text
    assert "où" in text
    assert "déjà" in text
    assert "être" in text
    assert "français" in text
    assert "ê" in text and "è" in text and "é" in text


def test_preserves_separate_lines(tmp_path):
    src = tmp_path / "pdfs"
    src.mkdir()
    pdf = src / "layout.pdf"
    _write_pdf(pdf, ["Titre du cours", "Première ligne", "Deuxième ligne"])

    text = extract_pdf(pdf)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    assert lines[0] == "Titre du cours"
    assert "Première ligne" in lines
    assert "Deuxième ligne" in lines


def test_overlay_acute_merges_onto_letter():
    # e at x=100, spacing acute overlapping the same glyph box
    base = {"c": "e", "bbox": (100.0, 200.0, 108.0, 212.0)}
    acute = {"c": "\u00b4", "bbox": (101.0, 196.0, 107.0, 204.0)}
    merged = _merge_diacritics([base, acute])
    assert len(merged) == 1
    assert merged[0]["c"] == "é"
    assert _as_combining("\u00b4") == "\u0301"


def test_run_extract_writes_sibling_markdown(tmp_path):
    src = tmp_path / "vault_pdfs"
    src.mkdir()
    nested = src / "week1"
    nested.mkdir()
    _write_pdf(nested / "chap.pdf", ["Café"])

    stats = run_extract(src, extension=".md")
    out = tmp_path / "vault_pdfs_extracted" / "week1" / "chap.md"
    assert stats["success"] == 1
    assert stats["output_dir"] == tmp_path / "vault_pdfs_extracted"
    assert out.exists()
    assert "Café" in out.read_text(encoding="utf-8")


def test_run_extract_skips_up_to_date_unless_force(tmp_path):
    src = tmp_path / "pdfs"
    src.mkdir()
    pdf = src / "a.pdf"
    _write_pdf(pdf, ["Hello"])

    first = run_extract(src)
    assert first["success"] == 1
    second = run_extract(src)
    assert second["skipped"] == 1
    assert second["success"] == 0
    forced = run_extract(src, force=True)
    assert forced["success"] == 1


def test_output_path_and_format_helpers(tmp_path):
    root = tmp_path / "in"
    pdf = root / "sub" / "note.pdf"
    dest = output_path_for(pdf, root, tmp_path / "out", ".txt")
    assert dest == tmp_path / "out" / "sub" / "note.txt"
    assert extract_format_from_name("markdown") == ".md"
    assert extract_format_from_name("txt") == ".txt"
    with pytest.raises(ExtractError):
        extract_format_from_name("pdf")

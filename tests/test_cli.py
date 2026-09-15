"""CLI argument parsing and extract command wiring."""
from pathlib import Path

import pymupdf as fitz

from nexus_formatter.cli import main, parse_args


def _write_pdf(path: Path, text: str) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text, fontsize=12, fontname="helv")
    doc.save(path)
    doc.close()


def test_parse_extract_and_format_subcommands():
    extract = parse_args(["extract", "./pdfs", "--format", "txt", "--dry-run"])
    assert extract.command == "extract"
    assert extract.extract_format == "txt"
    assert extract.dry_run is True

    fmt = parse_args(["format", "--input", "./notes", "--verbose"])
    assert fmt.command == "format"
    assert fmt.input == "./notes"
    assert fmt.verbose is True


def test_legacy_flags_still_map_to_format():
    args = parse_args(["--dry-run", "--only", "TCP.md"])
    assert args.command == "format"
    assert args.dry_run is True
    assert args.only == "TCP.md"


def test_extract_cli_writes_sibling_folder(tmp_path):
    src = tmp_path / "cours"
    src.mkdir()
    _write_pdf(src / "intro.pdf", "Éléments de forêt")

    code = main(["extract", str(src), "--log-dir", str(tmp_path / "logs")])
    assert code == 0
    out = tmp_path / "cours_extracted" / "intro.md"
    assert out.exists()
    body = out.read_text(encoding="utf-8")
    assert "forêt" in body
    assert "Éléments" in body

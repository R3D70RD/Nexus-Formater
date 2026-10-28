"""Command-line interface for extract (PDF → text) and format (LLM notes)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from nexus_formatter.config import build_config
from nexus_formatter.logging_setup import setup_logging
from nexus_formatter.pdf_extract import (
    ExtractError,
    default_output_dir,
    extract_format_from_name,
    run_extract,
)
from nexus_formatter.processor import run as run_format

console = Console()


def parse_args(argv=None) -> argparse.Namespace:
    argv = _normalize_argv(sys.argv[1:] if argv is None else list(argv))

    parser = argparse.ArgumentParser(
        prog="main.py",
        description=(
            "Extract PDF lecture notes 1:1 to Markdown/text, then optionally "
            "reformat those notes with a local LLM (Ollama)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python main.py extract ./lectures_pdf\n"
            "  python main.py extract ./lectures_pdf --format txt --dry-run\n"
            "  python main.py format --input ./lectures_pdf_extracted --dry-run\n"
            "  python main.py format --only TCP.md --verbose\n"
            "  python main.py run ./lectures_pdf\n"
            "  python main.py run ./lectures_pdf --json\n"
        ),
    )
    parser.add_argument("--version", action="store_true", help="Print version and exit")

    sub = parser.add_subparsers(dest="command")

    extract = sub.add_parser(
        "extract",
        help="Copy PDF text 1:1 into Markdown or text (no LLM, preserves accents)",
        description=(
            "Read PDFs and write a faithful text copy (layout + Unicode) into a "
            "folder next to the original, named <folder>_extracted. The LLM is "
            "not used; nothing is simplified or rewritten."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python main.py extract ./vault_pdfs\n"
            "  python main.py extract ./vault_pdfs/chapitre1.pdf -o ./notes_raw\n"
        ),
    )
    extract.add_argument(
        "input",
        help="PDF file or folder of PDFs",
    )
    extract.add_argument(
        "-o",
        "--output",
        help="Output folder (default: <original-folder>_extracted, next to it)",
    )
    extract.add_argument(
        "--format",
        dest="extract_format",
        choices=("md", "txt"),
        default="md",
        help="Output file type (default: md)",
    )
    extract.add_argument("--force", action="store_true", help="Overwrite existing extracts")
    extract.add_argument("--dry-run", action="store_true", help="Show the plan without writing files")
    extract.add_argument("--only", help="Extract a single file by name (e.g. chapitre1.pdf)")
    extract.add_argument("--log-dir", default="logs", help="Folder for extract run logs (default: logs)")
    extract.add_argument("--json", action="store_true", help="Emit machine-readable JSON to stdout")
    extract.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")

    fmt = sub.add_parser(
        "format",
        help="Reformat extracted Markdown notes with a local LLM",
        description="Batch-reformat Obsidian notes into atomic knowledge notes via Ollama.",
    )
    _add_format_flags(fmt)

    run = sub.add_parser(
        "run",
        help="One-shot: extract PDFs, then LLM-format the result",
        description=(
            "Extract PDFs into a staging folder, then run the LLM formatter on "
            "that staging folder. Output goes to config.output_dir."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python main.py run ./vault_pdfs\n"
            "  python main.py run ./vault_pdfs --dry-run\n"
            "  python main.py run ./vault_pdfs --json\n"
        ),
    )
    run.add_argument("input", help="PDF file or folder of PDFs")
    run.add_argument(
        "--staging-dir",
        help="Where extracted Markdown is written before formatting "
        "(default: <input-folder>_extracted)",
    )
    run.add_argument(
        "--extract-format",
        choices=("md", "txt"),
        default="md",
        help="Intermediate extract format (default: md)",
    )
    _add_format_flags(run, include_io=False)

    args = parser.parse_args(argv)
    args._parser = parser
    return args


def _add_format_flags(p: argparse.ArgumentParser, include_io: bool = True) -> None:
    p.add_argument("--config", help="Path to config.yaml (default: ./config.yaml if present)")
    if include_io:
        p.add_argument("--input", help="Folder of raw notes to read")
        p.add_argument("--output", help="Folder to write processed notes to")
        p.add_argument("--review", help="Folder for diffs / quality reports")
    p.add_argument("--log-dir", help="Folder for logs")
    p.add_argument("--state-dir", help="Folder for the manifest/skip-tracking state")
    p.add_argument("--prompt-template", help="Path to the system prompt template file")
    p.add_argument("--model", help="Ollama model name")
    p.add_argument("--base-url", help="Ollama server URL")
    p.add_argument("--temperature", type=float, help="Sampling temperature")
    p.add_argument("--timeout", type=int, help="Per-request timeout in seconds")
    p.add_argument("--retries", type=int, help="Max retry attempts per request")
    p.add_argument("--batch-size", type=int, help="Max notes per LLM request")
    p.add_argument("--max-chars", type=int, help="Max combined characters per batch")
    p.add_argument("--force", action="store_true", help="Reprocess even if already up to date")
    p.add_argument("--dry-run", action="store_true", help="Show the plan without calling the LLM")
    p.add_argument("--only", help="Process a single file by name (e.g. TCP.md)")
    p.add_argument("--json", action="store_true", help="Emit machine-readable JSON to stdout")
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose console/log output")


def _normalize_argv(argv: list) -> list:
    """Bare flags still run `format`, so older invocations keep working."""
    if not argv:
        return argv
    if argv[0] in ("extract", "format", "run", "-h", "--help", "--version"):
        return argv
    if argv[0].startswith("-"):
        return ["format"] + argv
    return argv


def main(argv=None) -> int:
    args = parse_args(argv)

    if args.version:
        from nexus_formatter import __version__

        console.print(f"nexus-formatter {__version__}")
        return 0

    if not args.command:
        args._parser.print_help()
        return 0

    if args.command == "extract":
        return _cmd_extract(args)
    if args.command == "format":
        return _cmd_format(args)
    if args.command == "run":
        return _cmd_run(args)
    args._parser.print_help()
    return 1


def _cmd_extract(args) -> int:
    source = Path(args.input)
    try:
        extension = extract_format_from_name(args.extract_format)
        dest = Path(args.output) if args.output else default_output_dir(source)
    except ExtractError as e:
        console.print(f"[red]ERROR[/red] {e}")
        return 1

    if not source.exists():
        console.print(f"[red]ERROR[/red] input does not exist: {source}")
        return 1

    setup_logging(Path(args.log_dir), verbose=args.verbose)
    _print_extract_banner(source, dest, extension, args.dry_run)

    try:
        stats = run_extract(
            source=source,
            output_dir=dest,
            extension=extension,
            force=args.force,
            dry_run=args.dry_run,
            only=args.only,
            on_file=lambda pdf, out, status: _print_extract_row(pdf, out, status, dest),
        )
    except ExtractError as e:
        console.print(f"[red]ERROR[/red] {e}")
        return 1
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        return 130

    _print_extract_summary(stats, dest, args.dry_run)
    return 1 if stats["failed"] else 0


def _print_extract_banner(source: Path, dest: Path, extension: str, dry_run: bool) -> None:
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="dim")
    table.add_column()
    table.add_row("Source", str(source.expanduser().resolve()) if source.exists() else str(source))
    table.add_row("Output", str(dest))
    table.add_row("Format", f"{extension.lstrip('.')} (1:1 copy, no LLM rewrite)")
    if dry_run:
        table.add_row("Mode", "[yellow]dry-run[/yellow]")
    title = Text("NEXUS  ·  extract", style="bold cyan")
    console.print(Panel(table, title=title, border_style="cyan"))


def _print_extract_row(pdf: Path, dest: Path, status: str, dest_root: Path) -> None:
    colors = {
        "extracted": "green",
        "would-extract": "cyan",
        "skipped": "dim",
        "failed": "red",
    }
    style = colors.get(status, "white")
    try:
        dest_label = dest.relative_to(dest_root)
    except ValueError:
        dest_label = dest
    console.print(f"  [{style}]{status:13}[/{style}] {pdf.name}  →  {dest_label}")


def _print_extract_summary(stats: dict, dest: Path, dry_run: bool) -> None:
    verb = "would extract" if dry_run else "extracted"
    console.print()
    console.print(
        f"[bold]Done.[/bold] {stats['success']} {verb}, "
        f"{stats['failed']} failed, {stats['skipped']} skipped "
        f"(of {stats['total']} PDF(s))."
    )
    if stats["success"] and not dry_run:
        console.print(
            f"Next: [bold]python main.py format --input {dest}[/bold]  "
            "(optional — only if you want the LLM to rewrite the notes)"
        )


def _cmd_format(args) -> int:
    config = build_config(args)

    if not config.input_dir.exists():
        console.print(f"[red]ERROR[/red] input folder does not exist: {config.input_dir}")
        return 1

    setup_logging(config.log_dir, verbose=config.verbose)
    _print_format_banner(config)

    try:
        stats = run_format(config)
    except KeyboardInterrupt:
        console.print(
            "\n[yellow]Interrupted.[/yellow] Progress was saved to the manifest; re-run to resume."
        )
        return 130

    console.print()
    console.print(
        f"[bold]Done.[/bold] {stats['success']} succeeded, "
        f"{stats['failed']} failed, {stats['skipped']} skipped "
        f"(of {stats['total']} total)."
    )
    return 1 if stats["failed"] else 0


def _cmd_run(args) -> int:
    source = Path(args.input)
    if not source.exists():
        console.print(f"[red]ERROR[/red] input does not exist: {source}")
        return 1

    try:
        extension = extract_format_from_name(args.extract_format)
        staging = Path(args.staging_dir) if args.staging_dir else default_output_dir(source)
    except ExtractError as e:
        console.print(f"[red]ERROR[/red] {e}")
        return 1

    setup_logging(Path(args.log_dir or "logs"), verbose=args.verbose)

    if not args.json:
        _print_run_banner(source, staging, extension, args.dry_run)

    try:
        extract_stats = run_extract(
            source=source,
            output_dir=staging,
            extension=extension,
            force=args.force,
            dry_run=args.dry_run,
            only=args.only,
            on_file=None if args.json else (
                lambda pdf, out, status: _print_extract_row(pdf, out, status, staging)
            ),
        )
    except ExtractError as e:
        console.print(f"[red]ERROR[/red] {e}")
        return 1
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        return 130

    # Format reads from staging; output_dir comes from config/CLI.
    args.input = str(staging)
    config = build_config(args)
    config.input_dir = staging

    if not args.json:
        _print_format_banner(config)

    try:
        format_stats = run_format(config)
    except KeyboardInterrupt:
        console.print(
            "\n[yellow]Interrupted.[/yellow] Progress was saved to the manifest; re-run to resume."
        )
        return 130

    if args.json:
        import json as _json

        payload = {
            "extract": extract_stats,
            "format": format_stats,
            "staging_dir": str(staging),
            "output_dir": str(config.output_dir),
            "dry_run": bool(args.dry_run),
        }
        print(_json.dumps(payload, indent=2))
    else:
        console.print()
        console.print(
            f"[bold]Done.[/bold] extract: {extract_stats['success']} ok / "
            f"{extract_stats['failed']} failed / {extract_stats['skipped']} skipped; "
            f"format: {format_stats['success']} ok / "
            f"{format_stats['failed']} failed / {format_stats['skipped']} skipped."
        )

    return 1 if (extract_stats["failed"] or format_stats["failed"]) else 0


def _print_run_banner(source: Path, staging: Path, extension: str, dry_run: bool) -> None:
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="dim")
    table.add_column()
    table.add_row("Source", str(source.expanduser().resolve()) if source.exists() else str(source))
    table.add_row("Staging", str(staging))
    table.add_row("Format", f"{extension.lstrip('.')} (1:1 copy, no LLM rewrite)")
    if dry_run:
        table.add_row("Mode", "[yellow]dry-run[/yellow]")
    title = Text("NEXUS  ·  run", style="bold green")
    console.print(Panel(table, title=title, border_style="green"))


def _print_format_banner(config) -> None:
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="dim")
    table.add_column()
    table.add_row("Input", str(config.input_dir))
    table.add_row("Output", str(config.output_dir))
    table.add_row("Review", str(config.review_dir))
    table.add_row("Model", config.model)
    table.add_row("Ollama", config.base_url)
    if config.dry_run:
        table.add_row("Mode", "[yellow]dry-run[/yellow]")
    if config.force:
        table.add_row("Force", "yes")
    title = Text("NEXUS  ·  format", style="bold magenta")
    console.print(Panel(table, title=title, border_style="magenta"))

#!/usr/bin/env python3
"""NEXUS Note Formatter -- CLI entrypoint.

Turns raw, messy Obsidian notes into atomic, RAG-friendly knowledge notes
using a local LLM served by Ollama. Run with --help for all options, or see
config.example.yaml for a persistent config file.
"""
from __future__ import annotations

import argparse
import sys

from nexus_formatter.config import build_config
from nexus_formatter.logging_setup import setup_logging
from nexus_formatter.processor import run


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Batch-reformat Obsidian notes into atomic knowledge notes via a local LLM."
    )
    p.add_argument("--config", help="Path to config.yaml (default: ./config.yaml if present)")
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
    p.add_argument("--verbose", action="store_true", help="Verbose console/log output")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    config = build_config(args)

    if not config.input_dir.exists():
        print(f"ERROR: input folder does not exist: {config.input_dir}", file=sys.stderr)
        return 1

    setup_logging(config.log_dir, verbose=config.verbose)

    try:
        run(config)
    except KeyboardInterrupt:
        print("\nInterrupted. Progress so far was saved to the manifest; re-run to resume.")
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

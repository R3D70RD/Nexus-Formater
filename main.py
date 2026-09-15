#!/usr/bin/env python3
"""NEXUS Note Formatter -- CLI entrypoint.

Extract PDFs 1:1 to Markdown/text, then optionally reformat notes with a
local LLM served by Ollama. Run with --help for commands and options.
"""
from __future__ import annotations

from nexus_formatter.cli import main


if __name__ == "__main__":
    raise SystemExit(main())

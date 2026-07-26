# NEXUS Note Formatter

Batch-converts messy, copy-pasted Obsidian notes into atomic, RAG-friendly
knowledge notes using a local LLM (via [Ollama](https://ollama.com)).

```
Input Folder ──▶ read note.md ──▶ batch with other small notes ──▶ send to LLM
                                                                       │
Output Folder ◀── write .md (+ frontmatter) ◀── parse response ◀──────┘
     │
     └──▶ Review Folder: diff vs. original + quality report
```

Originals are **never modified**. Already-processed, unchanged notes are
**skipped** on the next run. Failed notes are **retried automatically**
(both at the network level, and again on the next run of the script).

## Why this exists

Manually reformatting PDF-copied lecture notes into clean Obsidian notes is
slow. This script automates the reformatting step: point it at a folder of
raw `.md` notes, and it sends them to your local model with a fixed prompt
that turns each one into an atomic note with structured sections, YAML
frontmatter, and wikilinks — the way Obsidian (and a RAG pipeline reading
your vault) actually wants them.

## Features

- **Batching** — small notes (e.g. `TCP.md`, `UDP.md`, `DNS.md`) are packed
  into a single LLM request instead of one call per file; large notes are
  sent alone. Controlled by `max_notes_per_batch` / `max_chars_per_batch`.
- **Skip already-processed notes** — a manifest tracks a hash of each source
  file. Unchanged notes with a successful prior run are skipped; edited
  notes are automatically reprocessed; previously-failed notes are
  automatically retried on the next run.
- **Automatic retry on API failure** — transient Ollama errors (connection
  drop, 5xx, empty response) are retried with exponential backoff. A missing
  model (404) fails fast with a `ollama pull <model>` hint instead of
  retrying pointlessly.
- **Batch fallback** — if the model drops a note from a batched response,
  that note is automatically retried on its own instead of being silently
  lost.
- **Rich frontmatter** — `type`, `domain`, `tags`, `aliases` come from the
  model; `source`, `created`, and `needs_review` are set by the script
  itself (never trusted from the model), so they can't be hallucinated.
- **Review workflow** — every processed note gets a unified diff against the
  original in the review folder, plus an aggregated `quality_report.md`
  (built from the model's own self-rating) so you can see at a glance which
  notes are worth double-checking. Notes with a low self-rating, or where
  parsing failed, are flagged `needs_review: true` in their frontmatter —
  useful as an Obsidian/Dataview filter.
- **Progress + logging** — a live progress bar, a timestamped run log, and
  persistent `success.csv` / `failed.csv` audit trails that accumulate
  across runs.
- **Crash-resilient** — the manifest is saved after every batch, so an
  interrupted run resumes where it left off rather than starting over.

## Requirements

- Python 3.9+
- [Ollama](https://ollama.com) installed and running (`ollama serve`), with
  a model pulled (e.g. `ollama pull llama3.1`)

## Install

```bash
git clone <this-repo>
cd nexus-note-formatter
pip install -r requirements.txt
cp config.example.yaml config.yaml
```

Edit `config.yaml`: at minimum, set `input_dir` to the folder of raw notes
you want to convert, and `model` to whatever you pulled in Ollama.

## Usage

```bash
# See what would happen without calling the LLM
python main.py --dry-run

# Run for real
python main.py

# Reprocess everything, ignoring the skip-cache
python main.py --force

# Iterate on the prompt against a single note
python main.py --only TCP.md --verbose
```

Every setting in `config.yaml` can be overridden on the command line, e.g.
`python main.py --model mistral --batch-size 1` (useful for weaker local
models that struggle to follow the multi-note batching format reliably —
see Limitations below).

Run `python main.py --help` for the full flag list.

## Output layout

```
vault_raw/            your original notes (never touched)
  Networking/TCP.md

vault_processed/       atomic notes, ready to drop into Obsidian
  Networking/TCP.md
  .nexus_state/manifest.json     (skip/resume tracking -- safe to delete to force a full reprocess)

vault_review/          for spot-checking the AI's work
  Networking/TCP.diff            (unified diff: original vs. processed)
  quality_report.md              (model's own self-rating for every note)

logs/
  run_2026xxxx_xxxxxx.log        (detailed log for this run)
  success.csv / failed.csv       (persistent audit trail across all runs)
```

Each processed note looks like:

```markdown
---
type: concept
domain: networking
tags:
  - tcp
aliases:
  - Transmission Control Protocol
source: Networking/TCP.md
created: '2026-07-24'
needs_review: false
---

# TCP
## Purpose
...
## Key Ideas
...
## Related Concepts
- [[UDP]]
- [[OSI Model]]
```

## Customizing the prompt

The actual instructions sent to the model live in `prompt_template.md`, not
in the code — edit it freely. The one thing to preserve is the **output
contract** section at the bottom (the `>>>NOTE_START ... <<<` /
`>>>QUALITY_RATING<<<` markers): the script's parser depends on the model
echoing those markers back exactly, regardless of how you change the note
structure/rules above it.

## Batching tradeoffs

Batching multiple notes into one request is faster and cheaper, but it asks
more of the model's instruction-following (it has to keep several notes
straight and repeat exact markers). If you're using a small/weak local
model and see a lot of `needs_review: true` or entries in `failed.csv`, set
`max_notes_per_batch: 1` in `config.yaml` (or `--batch-size 1`) to send one
note per request.

## Running the tests

The pipeline is tested against a mock LLM backend, so you can verify the
batching/skip/retry logic without a running Ollama server:

```bash
pip install pytest
pytest
```

## Roadmap / not yet built

This first version handles **Markdown in → Markdown out**. Ideas from the
original design discussion that are deliberately out of scope for now:

- PDF/other-source text extraction (today you still need your notes in
  `.md` form as input)
- Automatic vector DB indexing after generation
- AI-suggested links validated against your existing vault (today
  `Related Concepts` links are the model's best guess and may point to
  notes that don't exist yet)

## Known limitations

- Batch parsing depends on the model reliably echoing the marker format.
  The fallback logic catches dropped notes, but a model that ignores
  instructions entirely will just produce `needs_review: true` notes or
  failures — check `vault_review/quality_report.md` and `logs/failed.csv`
  after your first run against a new model.
- `source` paths in frontmatter use OS-native path separators; this is only
  a cosmetic concern if you run the tool from both Windows and macOS/Linux
  against the same vault.

## License

MIT — see `LICENSE`.

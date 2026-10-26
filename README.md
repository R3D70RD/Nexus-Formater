# NEXUS Note Formatter

Extract PDF lecture notes **1:1** (layout and accents preserved, no LLM
rewrite), then optionally batch-convert those notes into atomic,
RAG-friendly Obsidian notes using a local LLM (via [Ollama](https://ollama.com)).

```
PDF folder ──▶ extract (PyMuPDF, Unicode) ──▶ <folder>_extracted/*.md
                                                    │
                                                    ▼
                              format (optional LLM rewrite) ──▶ vault_processed
                                                              └── vault_review
```

Originals are **never modified**. Already-processed, unchanged notes are
**skipped** on the next run. Failed notes are **retried automatically**
(both at the network level, and again on the next run of the script).

## Why this exists

Manually copy-pasting PDFs (and losing accents like é / ê / è) then
reformatting lecture notes is slow. `extract` dumps each PDF into a sibling
`*_extracted` folder as faithful Markdown/text. `format` is a separate,
optional step that sends already-extracted `.md` notes to your local model.

## Features

- **PDF extract (1:1)** — copies PDF text the way a careful copy-paste
  would: Unicode NFC, overlay accents merged onto letters, line/paragraph
  breaks kept. The LLM is **not** used and does **not** simplify the page.
  Output lands in `<original-folder>_extracted` next to the PDF folder.
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
- For `extract`: [PyMuPDF](https://pymupdf.readthedocs.io/) (installed via
  `requirements.txt`)
- For `format`: [Ollama](https://ollama.com) running (`ollama serve`), with
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
python main.py --help
python main.py extract --help
python main.py format --help

# 1:1 PDF → markdown in a sibling folder (no LLM)
python main.py extract ./lectures_pdf
# writes ./lectures_pdf_extracted/*.md  (nested PDFs keep their subfolders)

python main.py extract ./lectures_pdf --dry-run
python main.py extract ./lectures_pdf --format txt --force
python main.py extract ./lectures_pdf/chap1.pdf -o ./notes_raw

# Optional: LLM rewrite of already-extracted notes
python main.py format --input ./lectures_pdf_extracted --dry-run
python main.py format --input ./lectures_pdf_extracted
python main.py format --force
python main.py format --only TCP.md --verbose
```

Bare flags (`python main.py --dry-run`) still run `format` for compatibility.
Every setting in `config.yaml` can be overridden on the command line, e.g.
`python main.py format --model mistral --batch-size 1` (useful for weaker
local models that struggle to follow the multi-note batching format reliably —
see Limitations below).

## Output layout

```
lectures_pdf/                 originals (never touched)
  week1/chap1.pdf

lectures_pdf_extracted/       sibling folder written by `extract`
  week1/chap1.md              1:1 text, UTF-8, page breaks as ---

vault_raw/                    your original notes (never touched)
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
python -m pytest tests/test_pipeline.py -q
python -m pytest -q
```

## Roadmap / not yet built

Ideas from the original design discussion that are still out of scope:

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
- Scanned image-only PDFs have no text layer; this extractor cannot OCR them.

## License

MIT — see `LICENSE`.

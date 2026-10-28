"""Orchestrates the full pipeline: discover notes, skip up-to-date ones,
batch the rest, call the LLM, parse the response, write outputs + diffs,
and keep the manifest/log up to date as it goes (so a crash mid-run loses
at most the current batch, not previous progress)."""
from __future__ import annotations

import difflib
import logging
from pathlib import Path
from typing import List, Optional

from .batching import build_batches
from .config import Config
from .logging_setup import record_result
from .manifest import load_manifest, mark_failed, mark_success, needs_processing, save_manifest
from .ollama_client import OllamaClient, OllamaError, OllamaTruncatedError
from .parsing import (
    build_user_prompt,
    find_unterminated_ids,
    is_empty_note,
    normalize_frontmatter,
    parse_batch_response,
    render_note,
    split_frontmatter,
    split_quality,
)
from .progress import Progress

logger = logging.getLogger(__name__)


def discover_notes(config: Config) -> List[Path]:
    files = sorted(config.input_dir.rglob("*.md"))
    if config.only:
        files = [f for f in files if f.name == config.only]
    return files


def _is_empty_file(path: Path) -> bool:
    try:
        return is_empty_note(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return False


def run(config: Config, client: Optional[object] = None) -> dict:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    config.review_dir.mkdir(parents=True, exist_ok=True)
    config.state_dir.mkdir(parents=True, exist_ok=True)

    all_files = discover_notes(config)
    if not all_files:
        logger.info("No markdown files found in %s", config.input_dir)
        return {"success": 0, "failed": 0, "skipped": 0, "total": 0}

    manifest = load_manifest(config.manifest_path)

    def rel(f: Path) -> str:
        return str(f.relative_to(config.input_dir))

    pending = [f for f in all_files if needs_processing(rel(f), f, manifest, config.output_dir, config.force)]

    # Drop empty/whitespace-only notes before they reach the LLM: there is
    # nothing to transform, and sending them wastes a batch slot and risks
    # the model inventing content.
    empty = [f for f in pending if _is_empty_file(f)]
    if empty:
        for f in empty:
            logger.info("SKIP  %s (empty note)", f.relative_to(config.input_dir))
        pending = [f for f in pending if f not in empty]

    skipped = len(all_files) - len(pending)
    logger.info("Found %d note(s): %d to process, %d already up to date or empty.",
                len(all_files), len(pending), skipped)

    if config.dry_run:
        batches = build_batches(pending, config.max_notes_per_batch, config.max_chars_per_batch)
        logger.info("[dry-run] Would send %d batch(es):", len(batches))
        for i, batch in enumerate(batches, 1):
            logger.info("  Batch %d (%d note(s)): %s", i, len(batch), ", ".join(f.name for f in batch))
        return {"success": 0, "failed": 0, "skipped": skipped, "total": len(all_files)}

    if not pending:
        logger.info("Nothing to do. Use --force to reprocess everything.")
        return {"success": 0, "failed": 0, "skipped": skipped, "total": len(all_files)}

    if client is None:
        client = OllamaClient(
            base_url=config.base_url,
            model=config.model,
            temperature=config.temperature,
            timeout=config.timeout,
            max_retries=config.max_retries,
            backoff_base=config.backoff_base,
        )

    batches = build_batches(pending, config.max_notes_per_batch, config.max_chars_per_batch)
    stats = {"success": 0, "failed": 0, "skipped": skipped, "total": len(all_files)}
    progress = Progress(total=len(pending))

    try:
        for batch in batches:
            _process_batch(batch, client, config, manifest, stats, progress)
            save_manifest(manifest, config.manifest_path)  # persist after every batch
    finally:
        progress.done()
    logger.info("Done. %d succeeded, %d failed, %d skipped (of %d total).",
                stats["success"], stats["failed"], stats["skipped"], stats["total"])
    return stats


def _process_batch(batch, client, config: Config, manifest, stats, progress, _retry=False):
    ids = {i + 1: f for i, f in enumerate(batch)}
    names = ", ".join(f.name for f in batch)
    progress.note(f"Sending {'retry ' if _retry else ''}batch of {len(batch)}: {names}")

    try:
        raw = client.chat(config.system_prompt, build_user_prompt(ids))
    except OllamaTruncatedError as e:
        # Retrying the same prompt will truncate again; fail the whole batch
        # with a diagnosable message instead.
        logger.error("Batch truncated [%s]: %s", names, e)
        for f in batch:
            _record_failure(f, config, manifest, stats, progress, str(e))
        return
    except OllamaError as e:
        logger.error("Batch failed [%s]: %s", names, e)
        for f in batch:
            _record_failure(f, config, manifest, stats, progress, str(e))
        return

    parsed = parse_batch_response(raw, ids)
    missing = [i for i in ids if i not in parsed]

    # Detect truncation: a >>>NOTE_START<<< with no matching >>>NOTE_END<<<
    # means the model was cut off mid-note. Don't retry those individually.
    unterminated = find_unterminated_ids(raw, ids)
    if unterminated:
        done_reason = getattr(client, "last_done_reason", None) or "unknown"
        msg = (
            f"Model output truncated (done_reason={done_reason}, "
            f"{len(raw)} chars, unterminated note id(s)={unterminated}). "
            f"Increase num_ctx or reduce batch size."
        )
        logger.error("Batch truncated [%s]: %s", names, msg)
        for i in unterminated:
            _record_failure(ids[i], config, manifest, stats, progress, msg)
        # Only retry notes that were cleanly omitted (not cut off).
        missing = [i for i in missing if i not in unterminated]

    if missing and len(batch) > 1:
        logger.warning("Batch response incomplete (%d/%d parsed); retrying missing note(s) individually.",
                        len(parsed), len(batch))
        for i in missing:
            _process_batch([ids[i]], client, config, manifest, stats, progress, _retry=True)

    for i, note_text in parsed.items():
        f = ids[i]
        try:
            _save_note(f, note_text, config, manifest)
            stats["success"] += 1
            record_result(config.log_dir, str(f.relative_to(config.input_dir)), True)
            logger.info("OK    %s", f.relative_to(config.input_dir))
        except Exception as e:  # keep going even if one note is malformed
            logger.exception("Failed to save %s", f)
            _record_failure(f, config, manifest, stats, progress, str(e))
        progress.advance()

    if missing and len(batch) == 1:
        # A lone note that still didn't parse: don't lose the model's
        # output, save it for manual inspection instead.
        f = batch[0]
        raw_path = config.review_dir / f.relative_to(config.input_dir).with_suffix(".raw_response.txt")
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(raw, encoding="utf-8")
        done_reason = getattr(client, "last_done_reason", None) or "unknown"
        _record_failure(f, config, manifest, stats, progress,
                         f"Could not parse model response (done_reason={done_reason}, "
                         f"{len(raw)} chars); raw output saved to review folder.")


def _record_failure(f: Path, config: Config, manifest, stats, progress, error: str) -> None:
    rel_path = str(f.relative_to(config.input_dir))
    mark_failed(manifest, rel_path, f, error)
    stats["failed"] += 1
    record_result(config.log_dir, rel_path, False, error)
    logger.error("FAIL  %s -- %s", rel_path, error)
    progress.advance()


def _save_note(f: Path, note_text: str, config: Config, manifest) -> None:
    rel_path = str(f.relative_to(config.input_dir))
    note_body, quality = split_quality(note_text)
    fm, body = split_frontmatter(note_body)
    parse_ok = bool(fm) or note_body.startswith("#")

    frontmatter = normalize_frontmatter(fm, rel_path, quality, parse_ok)
    final_content = render_note(frontmatter, body)

    out_path = config.output_dir / rel_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(final_content, encoding="utf-8")

    _write_review(f, final_content, quality, config, rel_path)
    mark_success(manifest, rel_path, f)


def _write_review(original: Path, final_content: str, quality: str, config: Config, rel_path: str) -> None:
    original_text = original.read_text(encoding="utf-8", errors="replace")
    diff = difflib.unified_diff(
        original_text.splitlines(keepends=True),
        final_content.splitlines(keepends=True),
        fromfile=f"original/{rel_path}",
        tofile=f"processed/{rel_path}",
    )
    diff_path = (config.review_dir / rel_path).with_suffix(".diff")
    diff_path.parent.mkdir(parents=True, exist_ok=True)
    diff_path.write_text("".join(diff) or "(no textual diff)\n", encoding="utf-8")

    if quality:
        report_path = config.review_dir / "quality_report.md"
        is_new = not report_path.exists()
        with report_path.open("a", encoding="utf-8") as fh:
            if is_new:
                fh.write("# Quality report\n\n| Note | Quality assessment |\n|---|---|\n")
            fh.write(f"| {rel_path} | {' '.join(quality.split())} |\n")

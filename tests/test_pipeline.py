"""End-to-end tests for the processing pipeline, using a mock LLM backend
so no real Ollama server is required."""
from pathlib import Path

from nexus_formatter.config import Config
from nexus_formatter.parsing import PROMPT_VERSION, parse_batch_response, strip_code_fences
from nexus_formatter.processor import run
from tests.mock_client import AlwaysFailClient, MockOllamaClient

PROMPT = "(test system prompt)"


def make_config(tmp_path, **overrides):
    input_dir = tmp_path / "raw"
    input_dir.mkdir()
    defaults = dict(
        input_dir=input_dir,
        output_dir=tmp_path / "processed",
        review_dir=tmp_path / "review",
        log_dir=tmp_path / "logs",
        state_dir=tmp_path / "processed" / ".nexus_state",
        prompt_template_path=Path("prompt_template.md"),
        system_prompt=PROMPT,
        model="mock-model",
        base_url="http://localhost:11434",
        temperature=0.2,
        timeout=30,
        max_retries=3,
        backoff_base=0.01,
        max_notes_per_batch=5,
        max_chars_per_batch=6000,
        force=False,
        dry_run=False,
        only=None,
        verbose=False,
    )
    defaults.update(overrides)
    return Config(**defaults), input_dir


def write_note(input_dir, name, content):
    (input_dir / name).write_text(content, encoding="utf-8")


def test_batches_small_notes_and_writes_frontmatter(tmp_path):
    config, input_dir = make_config(tmp_path, max_notes_per_batch=3)
    write_note(input_dir, "TCP.md", "TCP is a reliable transport protocol...")
    write_note(input_dir, "UDP.md", "UDP is a connectionless transport protocol...")
    write_note(input_dir, "DNS.md", "DNS resolves names to IP addresses...")

    client = MockOllamaClient()
    stats = run(config, client=client)

    assert stats == {"success": 3, "failed": 0, "skipped": 0, "total": 3}
    assert client.calls == 1  # all 3 tiny notes fit in a single batch

    tcp_out = (config.output_dir / "TCP.md").read_text(encoding="utf-8")
    assert tcp_out.startswith("---\n")
    assert "type: concept" in tcp_out
    assert "source: TCP.md" in tcp_out
    assert "# TCP" in tcp_out

    original = (input_dir / "TCP.md").read_text(encoding="utf-8")
    assert "TCP is a reliable transport protocol" in original  # original untouched

    diff_path = config.review_dir / "TCP.diff"
    assert diff_path.exists()
    quality_report = (config.review_dir / "quality_report.md").read_text(encoding="utf-8")
    assert "TCP.md" in quality_report


def test_second_run_skips_unchanged_notes(tmp_path):
    config, input_dir = make_config(tmp_path)
    write_note(input_dir, "TCP.md", "TCP content")
    client = MockOllamaClient()

    run(config, client=client)
    assert client.calls == 1

    stats = run(config, client=client)
    assert client.calls == 1  # no new call made
    assert stats["skipped"] == 1
    assert stats["success"] == 0


def test_changed_note_is_reprocessed(tmp_path):
    config, input_dir = make_config(tmp_path)
    write_note(input_dir, "TCP.md", "v1 content")
    client = MockOllamaClient()
    run(config, client=client)

    write_note(input_dir, "TCP.md", "v2 content, quite different now")
    stats = run(config, client=client)
    assert client.calls == 2
    assert stats["success"] == 1


def test_dropped_note_in_batch_falls_back_to_individual_retry(tmp_path):
    config, input_dir = make_config(tmp_path, max_notes_per_batch=3)
    write_note(input_dir, "TCP.md", "TCP content")
    write_note(input_dir, "UDP.md", "UDP content")

    client = MockOllamaClient(drop_ids={2})  # model "forgets" the 2nd note once
    stats = run(config, client=client)

    assert stats["success"] == 2
    assert client.calls == 2  # 1 batch call + 1 fallback call for the dropped note
    assert (config.output_dir / "UDP.md").exists()


def test_truncated_batch_fails_without_individual_retry(tmp_path):
    config, input_dir = make_config(tmp_path, max_notes_per_batch=3)
    write_note(input_dir, "TCP.md", "TCP content")
    write_note(input_dir, "UDP.md", "UDP content")

    client = MockOllamaClient(truncate_ids={2})
    stats = run(config, client=client)

    # Only the truncated note fails; the clean one still succeeds.
    assert stats["success"] == 1
    assert stats["failed"] == 1
    # No pointless individual retry for the truncated note.
    assert client.calls == 1
    assert not (config.output_dir / "UDP.md").exists()
    failed_csv = (config.log_dir / "failed.csv").read_text(encoding="utf-8")
    assert "UDP.md" in failed_csv
    assert "done_reason=length" in failed_csv


def test_force_reprocesses_even_when_unchanged(tmp_path):
    config, input_dir = make_config(tmp_path)
    write_note(input_dir, "TCP.md", "TCP content")
    client = MockOllamaClient()
    run(config, client=client)

    config.force = True
    stats = run(config, client=client)
    assert client.calls == 2
    assert stats["success"] == 1


def test_api_failure_marks_notes_as_failed(tmp_path):
    config, input_dir = make_config(tmp_path)
    write_note(input_dir, "TCP.md", "TCP content")

    stats = run(config, client=AlwaysFailClient())
    assert stats["failed"] == 1
    assert not (config.output_dir / "TCP.md").exists()
    failed_csv = (config.log_dir / "failed.csv").read_text(encoding="utf-8")
    assert "TCP.md" in failed_csv


def test_empty_notes_are_skipped_without_calling_llm(tmp_path):
    config, input_dir = make_config(tmp_path)
    write_note(input_dir, "EMPTY.md", "   \n\n\t\n")
    write_note(input_dir, "TCP.md", "TCP content")

    client = MockOllamaClient()
    stats = run(config, client=client)

    assert client.calls == 1  # only the non-empty note was sent
    assert stats["success"] == 1
    assert stats["skipped"] == 1
    assert not (config.output_dir / "EMPTY.md").exists()


def test_parse_batch_response_tolerates_code_fences(tmp_path):
    batch = {1: tmp_path / "a.md"}
    raw = (
        '>>>NOTE_START id=0001 file="a.md"<<<\n'
        "```markdown\n"
        "---\ntype: concept\n---\n# A\n"
        "```\n"
        ">>>NOTE_END id=0001<<<"
    )
    parsed = parse_batch_response(raw, batch)
    assert 1 in parsed
    assert parsed[1].startswith("---")
    assert "```" not in parsed[1]


def test_parse_batch_response_ignores_prose_outside_markers(tmp_path):
    batch = {1: tmp_path / "a.md"}
    raw = (
        "Sure, here is the note you asked for:\n\n"
        '>>>NOTE_START id=0001 file="a.md"<<<\n'
        "---\ntype: concept\n---\n# A\n"
        ">>>NOTE_END id=0001<<<\n\n"
        "Let me know if you need anything else!"
    )
    parsed = parse_batch_response(raw, batch)
    assert parsed[1].startswith("---")
    assert "Sure" not in parsed[1]
    assert "Let me know" not in parsed[1]


def test_strip_code_fences_only_unwraps_whole_text():
    assert strip_code_fences("```\nhello\n```") == "hello"
    # A fence in the middle of a body must be preserved.
    body = "intro\n```python\nprint(1)\n```\noutro"
    assert strip_code_fences(body) == body


def test_prompt_version_is_defined():
    assert isinstance(PROMPT_VERSION, int) and PROMPT_VERSION >= 1

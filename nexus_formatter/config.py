"""Configuration loading for NEXUS Note Formatter.

Priority (lowest to highest): built-in DEFAULTS -> config.yaml -> CLI flags.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

DEFAULTS = {
    "input_dir": "vault_raw",
    "output_dir": "vault_processed",
    "review_dir": "vault_review",
    "log_dir": "logs",
    "state_dir": None,  # computed from output_dir if not set
    "prompt_template": "prompt_template.md",
    "model": "llama3.1",
    "base_url": "http://localhost:11434",
    "temperature": 0.2,
    "timeout": 180,
    "max_retries": 3,
    "backoff_base": 2,
    "max_notes_per_batch": 5,
    "max_chars_per_batch": 6000,
}


@dataclass
class Config:
    input_dir: Path
    output_dir: Path
    review_dir: Path
    log_dir: Path
    state_dir: Path
    prompt_template_path: Path
    system_prompt: str
    model: str
    base_url: str
    temperature: float
    timeout: int
    max_retries: int
    backoff_base: float
    max_notes_per_batch: int
    max_chars_per_batch: int
    force: bool = False
    dry_run: bool = False
    only: Optional[str] = None
    verbose: bool = False

    @property
    def manifest_path(self) -> Path:
        return self.state_dir / "manifest.json"


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file {path} must contain a YAML mapping.")
    return data


def build_config(cli_args) -> Config:
    """Merge defaults, config.yaml and CLI args into a single Config object."""
    config_path = Path(cli_args.config) if cli_args.config else Path("config.yaml")
    file_cfg = _load_yaml(config_path)

    def pick(key, cli_value=None):
        if cli_value is not None:
            return cli_value
        if key in file_cfg and file_cfg[key] is not None:
            return file_cfg[key]
        return DEFAULTS[key]

    input_dir = Path(pick("input_dir", cli_args.input))
    output_dir = Path(pick("output_dir", cli_args.output))
    review_dir = Path(pick("review_dir", cli_args.review))
    log_dir = Path(pick("log_dir", cli_args.log_dir))

    state_dir_val = pick("state_dir", cli_args.state_dir)
    state_dir = Path(state_dir_val) if state_dir_val else output_dir / ".nexus_state"

    prompt_template_path = Path(pick("prompt_template", cli_args.prompt_template))
    if not prompt_template_path.exists():
        print(f"ERROR: prompt template not found: {prompt_template_path}", file=sys.stderr)
        sys.exit(1)
    system_prompt = prompt_template_path.read_text(encoding="utf-8")

    # Safety net: never let output/review live inside input_dir, or the next
    # run would try to "atomic-ify" its own generated notes.
    for name, d in (("output_dir", output_dir), ("review_dir", review_dir)):
        try:
            d.resolve().relative_to(input_dir.resolve())
        except ValueError:
            continue  # not nested under input_dir -- good
        print(
            f"ERROR: {name} ({d}) is inside input_dir ({input_dir}). "
            "Choose a separate folder so generated notes are never re-ingested.",
            file=sys.stderr,
        )
        sys.exit(1)

    return Config(
        input_dir=input_dir,
        output_dir=output_dir,
        review_dir=review_dir,
        log_dir=log_dir,
        state_dir=state_dir,
        prompt_template_path=prompt_template_path,
        system_prompt=system_prompt,
        model=pick("model", cli_args.model),
        base_url=pick("base_url", cli_args.base_url),
        temperature=float(pick("temperature", cli_args.temperature)),
        timeout=int(pick("timeout", cli_args.timeout)),
        max_retries=int(pick("max_retries", cli_args.retries)),
        backoff_base=float(pick("backoff_base", None)),
        max_notes_per_batch=int(pick("max_notes_per_batch", cli_args.batch_size)),
        max_chars_per_batch=int(pick("max_chars_per_batch", cli_args.max_chars)),
        force=cli_args.force,
        dry_run=cli_args.dry_run,
        only=cli_args.only,
        verbose=cli_args.verbose,
    )

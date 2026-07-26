"""Tracks per-note state (hash + status) so re-runs skip notes that are
already processed and unchanged, and automatically retry ones that failed."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_manifest(manifest_path: Path) -> Dict[str, dict]:
    if not manifest_path.exists():
        return {}
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # A corrupt manifest shouldn't crash the run -- start fresh, but
        # keep the broken file around in case it's needed for debugging.
        manifest_path.replace(manifest_path.with_suffix(".json.corrupt"))
        return {}


def save_manifest(manifest: Dict[str, dict], manifest_path: Path) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = manifest_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(manifest_path)


def needs_processing(rel_path: str, path: Path, manifest: Dict[str, dict],
                      output_dir: Path, force: bool) -> bool:
    if force:
        return True
    entry = manifest.get(rel_path)
    if entry is None:
        return True
    if entry.get("status") != "success":
        return True  # previously failed -> retry automatically next run
    if entry.get("hash") != file_hash(path):
        return True  # source note changed since last run
    if not (output_dir / rel_path).exists():
        return True  # output was deleted/moved by hand
    return False


def mark_success(manifest: Dict[str, dict], rel_path: str, path: Path) -> None:
    manifest[rel_path] = {"hash": file_hash(path), "status": "success", "error": None}


def mark_failed(manifest: Dict[str, dict], rel_path: str, path: Path, error: str) -> None:
    manifest[rel_path] = {"hash": file_hash(path), "status": "failed", "error": error}

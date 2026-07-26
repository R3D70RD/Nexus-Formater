"""Logging configuration: console output, a timestamped run log, and a
persistent success/failed CSV audit trail that accumulates across runs."""
from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path


def setup_logging(log_dir: Path, verbose: bool = False) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_log_path = log_dir / f"run_{timestamp}.log"

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()

    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(console)

    file_handler = logging.FileHandler(run_log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    root.addHandler(file_handler)

    return run_log_path


def record_result(log_dir: Path, relative_path: str, success: bool, error: str = "") -> None:
    """Append one row to the persistent success.csv / failed.csv audit trail."""
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / ("success.csv" if success else "failed.csv")
    is_new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if is_new:
            writer.writerow(["timestamp", "file"] if success else ["timestamp", "file", "error"])
        row = [datetime.now().isoformat(timespec="seconds"), relative_path]
        if not success:
            row.append(error)
        writer.writerow(row)

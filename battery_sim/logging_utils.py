# ============================================================
# Battery Dataset Simulation Platform v0.1
# Lightweight logging helpers (no external dependency)
# ============================================================

from __future__ import annotations

import sys
from datetime import datetime, timezone


def timestamp_utc() -> str:
    """ISO-8601 UTC timestamp for run_metadata.json."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def banner(title: str, width: int = 70, char: str = "=") -> None:
    """Print a section banner to stdout."""
    print(char * width)
    print(title)
    print(char * width)


def kv(key: str, value) -> None:
    """Print one aligned key-value line."""
    print(f"{key:<15}: {value}")


def ok(msg: str) -> None:
    print(f"[OK] {msg}")


def warn(msg: str) -> None:
    print(f"[WARNING] {msg}", file=sys.stderr)


def fail(msg: str) -> None:
    print(f"[FAILED] {msg}", file=sys.stderr)

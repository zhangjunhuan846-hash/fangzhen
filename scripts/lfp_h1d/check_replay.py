"""H1-D0: check_replay.py - list sha256 of every file under forward_baseline/.

Run twice around a fresh re-run of run_forward_baseline.py and diff the outputs
to demonstrate Gate 7 (fresh replay deterministic, byte-identical).
Writes nothing; prints "<relpath>  <sha256>" lines to stdout.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from h1d0_spec import OUT_DIR  # noqa: E402


def main() -> int:
    if not OUT_DIR.exists():
        print(f"missing output dir: {OUT_DIR}")
        return 2
    files = sorted(p for p in OUT_DIR.rglob("*") if p.is_file())
    if not files:
        print(f"no files under {OUT_DIR}")
        return 2
    for p in files:
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        rel = p.relative_to(OUT_DIR).as_posix()
        print(f"{rel}  {h}")
    print(f"TOTAL_FILES {len(files)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

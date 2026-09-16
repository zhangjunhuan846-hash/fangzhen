"""Repair control characters that a Python heredoc injected into STATUS.md.

Writing LaTeX inside a non-raw Python string in an earlier edit turned
    \tau    -> TAB
    \rm     -> CR
    \approx -> BEL
so the file carries control bytes where math should be.  Repair by byte
pattern, then assert the damage is gone.
"""

from __future__ import annotations

import pathlib
import sys

TAB, CR, BEL = chr(9), chr(13), chr(7)

PAIRS = [
    (TAB + "au_d", "\\tau_d"),
    (BEL + "pprox", "\\approx"),
    (CR + "m pulse}", "\\rm pulse}"),
]


def main() -> int:
    p = pathlib.Path("STATUS.md")
    t = p.read_text(encoding="utf-8", newline="")

    for old, new in PAIRS:
        n = t.count(old)
        print(f"  {old!r} -> {new!r} : {n} occurrence(s)")
        if n:
            t = t.replace(old, new)

    p.write_text(t, encoding="utf-8", newline="")

    raw = p.read_bytes()
    left = {c: raw.count(c.encode()) for c in (TAB, CR, BEL)}
    print(f"\nafter write, control bytes remaining: {left}")

    # TAB may legitimately appear nowhere in this file; CR and BEL must not.
    if left[CR] or left[BEL]:
        print("FAIL: CR/BEL still present")
        return 1
    print("OK: no CR, no BEL")
    return 0


if __name__ == "__main__":
    sys.exit(main())

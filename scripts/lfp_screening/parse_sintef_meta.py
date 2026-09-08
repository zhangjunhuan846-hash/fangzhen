"""Parse SINTEF metadata.csv for LFP rows (H1-A screening evidence)."""
import csv
import sys

P = (
    r"C:\Users\24330\WorkBuddy\仿真模拟\data\raw\LIB\LFP_LiMetal"
    r"\SINTEF_R2032\meta\metadata.csv"
)

with open(P, newline="", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))

cols = list(rows[0].keys())
print("n columns:", len(cols))
print("columns:", cols)
print("n rows:", len(rows))
print()

lfp = [r for r in rows if "lfp" in (r.get("BDF names") or "").lower()]
print("LFP rows:", len(lfp))
for r in lfp:
    print("=" * 78)
    for k in cols:
        v = (r.get(k) or "").strip()
        if v:
            print(f"  {k:<44} {v}")

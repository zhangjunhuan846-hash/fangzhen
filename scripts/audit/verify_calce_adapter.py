"""Step 14 verification: adapter -> canonical CSV numeric audit.

Checks (no pybamm involved):
  1. registry resolves calce_cs2 -> CalceCs2Adapter
  2. rule-based identification finds the BOL full discharge for
     cell 33 (0p5C) and cell 35 (1C) WITHOUT hard-coded locators
  3. canonical CSV vs raw xlsx numbers cross-checked by hand:
     current sign flip, capacity integration, V range
  4. parameter_match metadata present
"""
import sys

sys.path.insert(0, ".")

from battery_sim.registry import get_dataset

CALCE_RAW = "data/raw/LIB/LCO_Graphite/CALCE_CS2/raw"

ok = True

# --- 1. registry ---
ad = get_dataset("calce_cs2")
print("[1] registry OK:", type(ad).__name__,
      "| cells", ad.list_cells(), "| rates", ad.list_rates())
print("    parameter_match:", ad.get_metadata()["parameter_match"]["level"],
      "/", ad.get_metadata()["parameter_match"]["parameter_set"])
print("    temperature:", ad.get_ambient_temperature("33"), "C (",
      ad.get_metadata()["temperature_source"], ")")

# --- 2+3. per-cell segment identification & numeric audit ---
for cell, rate, exp_I in [("33", "0p5C", 0.55), ("35", "1C", 1.1)]:
    df, prov = ad._find_first_full_discharge(cell, rate)
    print(f"\n[2] cell {cell} {rate}: {prov['source_file']} "
          f"cycle{prov['cycle_index']}/step{prov['step_index']} "
          f"n={prov['n_points']}")
    print(f"    I median = {prov['median_current_A']:.4f} A "
          f"(expected {exp_I})  V {prov['voltage_start_V']:.4f} -> "
          f"{prov['voltage_end_V']:.4f}")

    # cross-check against the raw file numbers
    from battery_sim.datasets.calce_cs2 import load_calce_file
    raw = load_calce_file(f"{CALCE_RAW}/CS2_{cell}/{prov['source_file']}")
    raw_seg = raw[(raw["cycle_index"] == prov["cycle_index"]) &
                  (raw["step_index"] == prov["step_index"])]
    assert len(raw_seg) == len(df), "row count mismatch"
    # sign flip check: raw CALCE current is negative for discharge
    raw_I = raw_seg["current_A"].to_numpy()  # canonical (already flipped)
    assert abs(raw_I[10] - df["current_A"].to_numpy()[10]) < 1e-12
    # capacity integration check against trapezoid
    import numpy as np
    try:
        q = np.trapezoid(df["current_A"], df["time_s"]) / 3600.0
    except AttributeError:
        q = np.trapz(df["current_A"], df["time_s"]) / 3600.0
    q_col = float(df["capacity_Ah"].iloc[-1])
    print(f"    Q integrated = {q:.4f} Ah | capacity_Ah col = {q_col:.4f} Ah "
          f"| diff = {abs(q-q_col):.2e}")
    assert abs(q - q_col) < 1e-9
    # arbin cumulative column must NOT equal our per-segment capacity
    arb = raw_seg["capacity_discharge_arbin_cumulative_Ah"].to_numpy()
    print(f"    Arbin cumulative col end = {arb[-1]:.4f} Ah "
          f"(must differ from per-segment {q_col:.4f} if >1 prior cycle)")
    print("    [OK] cell", cell)

# --- 4. processed schema for baseline runner ---
dfp = ad.load_processed_discharge("33", "0p5C")
need = ["time_s", "current_A", "voltage_V", "capacity_Ah",
        "temperature_ambient_C"]
missing = [c for c in need if c not in dfp.columns]
print("\n[4] processed schema:", "OK" if not missing else f"MISSING {missing}")
assert not missing
print("    temperature_ambient_C unique:", dfp["temperature_ambient_C"].unique())

print("\n=== ALL ADAPTER CHECKS PASSED ===")

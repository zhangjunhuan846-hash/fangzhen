# ============================================================
# Half-cell pilot H7 - adapter probe (pre-flight to the first
# platform replay).  Loads the C/10 canonical window through the
# registry + adapter exactly as the baseline runner will, and
# prints the provenance / initialisation blocks.
# ============================================================
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from battery_sim.registry import get_dataset  # noqa: E402

adapter = get_dataset("birmingham_ncm920305")

info = adapter.rate_info("Cover10")
print("rate_info Cover10:", {k: info[k] for k in ("c_rate", "rate_label",
                                                  "rate_slug", "source_rate",
                                                  "legacy_rate")})

df = adapter.load_processed_discharge("2mAhcm2", "Cover10")
prov = df.attrs["provenance"]
init = df.attrs["initialisation"]

print(f"\nwindow: n={len(df)}  dur_s={df['time_s'].iloc[-1]:.1f}")
print(f"cols: {list(df.columns)}")
print(f"I: med={df['current_A'].median():.6f} A  min={df['current_A'].min():.6f}  "
      f"max={df['current_A'].max():.6f}")
print(f"V: start={df['voltage_V'].iloc[0]:.4f}  end={df['voltage_V'].iloc[-1]:.4f}")
print(f"Q_end_Ah={df['capacity_Ah'].iloc[-1]:.6f}  T_amb={df['temperature_ambient_C'].iloc[0]:.2f} C")

for k in ("source_file", "file_sha256", "rest_ocv_V",
          "initial_stoichiometry_from_ocp", "voltage_start_V",
          "voltage_end_V", "median_current_A",
          "measured_temperature_median_K", "temperature_matches_298.15K"):
    print(f"prov.{k} = {prov[k]}")

print("\ninitialisation block:")
for k, v in init.items():
    print(f"  {k} = {v}")

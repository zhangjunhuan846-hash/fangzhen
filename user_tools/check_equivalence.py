#!/usr/bin/env python3
# ============================================================
# S8 importer equivalence gate
#
#   known raw data  ->  user importer  ->  canonical
#                                            |
#   known raw data  ->  原 dataset adapter ->  canonical
#                                            |
#                       比较 t / I / V（浮点误差内应一致）
#
# 这是"generic importer 与原有专用 adapter 等价"的证据。
# 比较对象是 adapter 的 _load_raw_file（列映射+单位+符号那一层），
# 因为窗口选择（_find_window）是 dataset-specific 逻辑，
# 不属于 generic importer 的职责。
#
# 运行：python -m user_tools.check_equivalence
# ============================================================

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from user_tools.import_dataset import USER_OUT_ROOT, _safe_name  # noqa: E402
from user_tools.spec import OUT_MANIFEST  # noqa: E402

TOL_T = 1e-6      # s
TOL_I = 1e-12     # A
TOL_V = 1e-9      # V

# demo 数据是从这个已验证的原始数据文件复制来的
REFERENCE_SOURCE = (
    "data/raw/LIB/NMC_LiMetal/Birmingham_NCM920305/raw"
    "/RateCapability_Cover5_2mAhcm_2_NCM920305.csv"
)


def main() -> int:
    manifest_path = USER_OUT_ROOT / "demo_birmingham_cover5" / OUT_MANIFEST
    if not manifest_path.is_file():
        print("[错误] 先运行 make_demo 与 import_dataset")
        return 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    user_csv = ROOT / manifest["canonical_path"]
    df_user = pd.read_csv(user_csv)
    t0 = float(manifest["conversion"]["time_offset_s"])

    # ---- 原 adapter 的同一份数据 ------------------------------------
    # 参考源是已知的、已验证的原始数据文件（不是 demo 副本的文件名）
    from battery_sim.registry import get_dataset

    adapter = get_dataset("birmingham_ncm920305")
    src = ROOT / REFERENCE_SOURCE
    if not src.is_file():
        print(f"[错误] 找不到参考原始数据：{src}")
        return 2
    df_ref = adapter._load_raw_file(src)

    print("=" * 60)
    print("  importer equivalence gate")
    print("=" * 60)
    print(f"  源数据      : {manifest['source_file']}")
    print(f"  参考 adapter : birmingham_ncm920305._load_raw_file")
    print(f"  importer     : user_tools generic importer")
    print(f"  行数 ref/user: {len(df_ref)} / {len(df_user)}")
    print()

    t_ref = df_ref["time_s"].to_numpy(float)
    I_ref = df_ref["current_A"].to_numpy(float)
    V_ref = df_ref["voltage_V"].to_numpy(float)

    t_u = df_user["time_s"].to_numpy(float) + t0
    I_u = df_user["current_A"].to_numpy(float)
    V_u = df_user["voltage_V"].to_numpy(float)

    if len(t_ref) == len(t_u):
        dt = float(np.max(np.abs(t_ref - t_u)))
        di = float(np.max(np.abs(I_ref - I_u)))
        dv = float(np.max(np.abs(V_ref - V_u)))
        method = "elementwise"
    else:
        # 行数不同（去重/清洗差异）时按时间插值比较
        tq = t_u
        di = float(np.max(np.abs(np.interp(tq, t_ref, I_ref) - I_u)))
        dv = float(np.max(np.abs(np.interp(tq, t_ref, V_ref) - V_u)))
        dt = float("nan")   # 行数不同时逐点时间差没有意义
        method = "interpolated (row counts differ)"

    print(f"  比较方式    : {method}")
    print(f"  max |Δt|    : {dt:.3e} s   (tol {TOL_T:.0e})")
    print(f"  max |ΔI|    : {di:.3e} A   (tol {TOL_I:.0e})")
    print(f"  max |ΔV|    : {dv:.3e} V   (tol {TOL_V:.0e})")
    print()

    ok = (dt <= TOL_T) and (di <= TOL_I) and (dv <= TOL_V)
    print("  结论        : " + ("EQUIVALENT ✓" if ok else "NOT EQUIVALENT ✗"))
    print("=" * 60)

    out = {
        "gate": "importer_equivalence",
        "source_file": manifest["source_file"],
        "reference": "birmingham_ncm920305._load_raw_file",
        "n_rows_reference": int(len(df_ref)),
        "n_rows_importer": int(len(df_user)),
        "method": method,
        "max_abs_dt_s": dt,
        "max_abs_dI_A": di,
        "max_abs_dV_V": dv,
        "tolerances": {"t_s": TOL_T, "I_A": TOL_I, "V_V": TOL_V},
        "equivalent": bool(ok),
    }
    dest = USER_OUT_ROOT / "demo_birmingham_cover5" / "equivalence_gate.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  已写入：{dest.relative_to(ROOT)}")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

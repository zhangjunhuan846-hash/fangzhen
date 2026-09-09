#!/usr/bin/env python3
# ============================================================
# S8 demonstration package
#
# 把已验证过的 Birmingham NCM920305 C/5 数据复制一份到
# user_dataset_template/raw/，并预填 dataset_info.xlsx，
# 伪装成"用户上传数据"，走完整 importer -> canonical -> platform 流程。
#
# 运行：python -m user_tools.make_demo
# ============================================================

from __future__ import annotations

import shutil
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]

SRC = (
    ROOT / "data/raw/LIB/NMC_LiMetal/Birmingham_NCM920305/raw"
    / "RateCapability_Cover5_2mAhcm_2_NCM920305.csv"
)
TEMPLATE = ROOT / "user_dataset_template"
DEMO_NAME = "demo_birmingham_cover5.csv"

EXP_VALUES = {
    "dataset_name": "demo_birmingham_cover5",
    "sample_id": "NCM920305_demo",
    "chemistry": "NMC",
    "cell_configuration": "half_cell",
    "working_electrode": "positive",
    "counter_electrode": "lithium_metal",
    "nominal_capacity": 0.003112,
    "active_material_loading": 2.0,
    "electrode_area": 1.72,
    "electrolyte": "LiPF6 (Celgard 2325)",
    "voltage_lower": 2.5,
    "voltage_upper": 4.2,
    "temperature": 25,
    "protocol": "CC_Cover5",
    "current_sign": "discharge_negative",
    "initial_soc": "",
}

MAPPING_VALUES = {
    "time": ("Time [s]", "s"),
    "current": ("Current [mA]", "mA"),
    "voltage": ("Voltage [V]", "V"),
    "capacity": ("Capacity [mAh]", "mAh"),
    "cycle": ("", ""),
    "step": ("", ""),
    "temperature": ("Temperature [K]", "K"),
}


def main() -> int:
    if not SRC.is_file():
        print(f"[错误] 找不到 demo 源数据：{SRC}", file=__import__("sys").stderr)
        return 2

    raw_dir = TEMPLATE / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    dst = raw_dir / DEMO_NAME
    shutil.copyfile(SRC, dst)
    print(f"已复制 demo 数据：{dst.relative_to(ROOT)}")

    xlsx = TEMPLATE / "dataset_info.xlsx"
    if not xlsx.is_file():
        print("[错误] 请先运行 python -m user_tools.make_template")
        return 2

    wb = load_workbook(xlsx)

    ws = wb["experiment"]
    for r in range(2, ws.max_row + 1):
        field = ws.cell(row=r, column=1).value
        if field in EXP_VALUES:
            ws.cell(row=r, column=3).value = EXP_VALUES[field]

    ws2 = wb["column_mapping"]
    for r in range(2, ws2.max_row + 1):
        field = ws2.cell(row=r, column=1).value
        if field in MAPPING_VALUES:
            col, unit = MAPPING_VALUES[field]
            ws2.cell(row=r, column=3).value = col
            ws2.cell(row=r, column=4).value = unit

    wb.save(xlsx)
    print(f"已预填：{xlsx.relative_to(ROOT)}")
    print("\n现在可以双击「导入并检查数据.bat」查看效果。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

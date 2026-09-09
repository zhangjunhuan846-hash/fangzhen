#!/usr/bin/env python3
# ============================================================
# 运行仿真 —— 命令行入口（被「运行仿真.bat」调用）
#
# 用法：
#   python -m user_tools.run_baseline --package user_dataset_template
#          [--model DFN] [--models DFN SPMe]
#
# 只做 zero-fit baseline：
#   * 不拟合任何参数
#   * 用平台现有的 run_baseline_cell()（科学逻辑零改动）
#   * 参数集由 S6 兼容门决定；不支持时明确 SIMULATION = NOT AVAILABLE
# ============================================================

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from user_tools.import_dataset import USER_OUT_ROOT, _safe_name  # noqa: E402
from user_tools.spec import OUT_MANIFEST  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", default="user_dataset_template")
    ap.add_argument(
        "--models",
        nargs="+",
        default=["DFN"],
        help="要跑的模型，默认 DFN",
    )
    args = ap.parse_args(argv)

    pkg = Path(args.package)
    if not pkg.is_absolute():
        pkg = ROOT / pkg

    # 先读 experiment 表拿到 dataset_name
    try:
        from user_tools import importer
        exp, _ = importer.read_dataset_info(pkg / "dataset_info.xlsx")
    except importer.UserInputError as e:
        print("\n[错误] " + str(e), file=sys.stderr)
        return 2

    out_dir = USER_OUT_ROOT / _safe_name(str(exp.get("dataset_name", "")))
    manifest_path = out_dir / OUT_MANIFEST

    if not manifest_path.is_file():
        print(
            "\n[错误] 还没有导入结果。\n"
            "请先双击「导入并检查数据.bat」，成功后再运行仿真。",
            file=sys.stderr,
        )
        return 2

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    if manifest["validation"]["import_status"] != "PASS":
        print(
            "\n[错误] 上一次导入未通过（存在严重错误）。\n"
            "请打开 validation_report.html 修正数据或 Excel 后重新导入。",
            file=sys.stderr,
        )
        return 1

    gate = manifest["parameter_gate"]
    if not gate["available"]:
        print("\n" + "=" * 56)
        print("  DATA IMPORT = PASS")
        print("  SIMULATION  = NOT AVAILABLE")
        print("=" * 56)
        print("  原因：没有可用的参数集。本工具不会为了能跑而")
        print("        换一个不匹配的参数集。")
        for b in gate.get("blockers", []):
            print(f"   - {b}")
        print(f"  说明：{gate['reason']}")
        return 0

    # ---- 延迟导入 pybamm（只有真正要跑时才导入）----
    from battery_sim.simulation.baseline import run_baseline_cell
    from user_tools.adapter import UserDatasetAdapter

    canonical_csv = ROOT / manifest["canonical_path"]
    dataset_id = "user_" + _safe_name(str(exp.get("dataset_name", "")))

    adapter = UserDatasetAdapter(
        canonical_csv=canonical_csv,
        exp=exp,
        gate=gate,
        dataset_id=dataset_id,
    )

    print("\n" + "=" * 56)
    print(f"  数据集    ：{manifest['dataset_name']}（{manifest['sample_id']}）")
    print(f"  参数集    ：{gate['parameter_set']}  (grade {gate['grade']})")
    print(f"  匹配等级  ：{gate['level']}")
    prov = gate.get("provenance") or {}
    if prov.get("provenance"):
        print(f"  溯源      ：{prov.get('provenance')}"
              f" / electrode={prov.get('electrode_design')}"
              f" / exec_reprod={prov.get('executable_reproduction')}")
    print(f"  是否拟合  ：{'是' if gate['fitted_to_dataset'] else '否（zero-fit）'}")
    print(f"  环境温度  ：{adapter.get_ambient_temperature(None):.2f} C "
          f"（来源：{adapter.ambient_source}）")
    print("=" * 56 + "\n")

    all_rows = []
    for model in args.models:
        print(f"---- {model.upper()} ----")
        res = run_baseline_cell(
            adapter,
            model_name=model.upper(),
            cell=str(exp.get("sample_id", "") or "user"),
            rate="as_provided",
            parameter_set=gate["parameter_set"],
            plot=True,
            quiet=False,
        )
        m = res["metrics"]
        all_rows.append(m)
        print(f"  输出目录：{res['output_dir']}")

    combined = pd.concat(all_rows, ignore_index=True)
    summary_path = out_dir / "baseline_metrics.csv"
    combined.to_csv(summary_path, index=False, encoding="utf-8-sig")

    note = {
        "dataset_name": manifest["dataset_name"],
        "parameter_set": gate["parameter_set"],
        "parameter_match_level": gate["level"],
        "parameter_match_grade": gate["grade"],
        "parameter_match_provenance": gate.get("provenance") or {},
        "fitted_to_dataset": False,
        "models": [m.upper() for m in args.models],
        "rmse_time_aligned_mV": {
            str(r["model"]): float(r["rmse_time_aligned_mV"])
            for _, r in combined.iterrows()
        },
        "warning": (
            "Zero-fit baseline only. 参数集未经你的数据标定；"
            "RMSE 用于描述差异大小，不代表模型已被验证，"
            "也不代表误差来源于某个具体参数。"
        ),
    }
    (out_dir / "baseline_note.json").write_text(
        json.dumps(note, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n" + "=" * 56)
    print("  baseline 完成（zero-fit，未做任何拟合）")
    print(f"  指标表：{summary_path.name}")
    print("=" * 56)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

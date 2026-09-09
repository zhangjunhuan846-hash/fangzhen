#!/usr/bin/env python3
# ============================================================
# 导入并检查数据 —— 命令行入口（被「导入并检查数据.bat」调用）
#
# 用法：
#   python -m user_tools.import_dataset --package user_dataset_template
#
# 行为：
#   1. 读 dataset_info.xlsx（experiment + column_mapping）
#   2. 读 raw/ 下的 csv/xls/xlsx
#   3. 按显式映射 + 单位 + 符号声明 -> canonical
#   4. 跑 S4 validation gate
#   5. 跑 S6 parameter compatibility gate
#   6. 输出 validation_report.html / issues.csv /
#      canonical_preview.csv / voltage_capacity_preview.png /
#      dataset_manifest.json / canonical_data.csv
#
# 不做任何拟合、不做参数辨识。
# ============================================================

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from user_tools import importer, report, validate  # noqa: E402
from user_tools.spec import (  # noqa: E402
    OUT_CANONICAL_FULL,
    OUT_CANONICAL_PREVIEW,
    OUT_ISSUES,
    OUT_MANIFEST,
    OUT_PREVIEW_PNG,
    OUT_VALIDATION_REPORT,
    parameter_gate,
)

USER_OUT_ROOT = ROOT / "outputs" / "user_datasets"


def _safe_name(s: str) -> str:
    s = str(s).strip()
    s = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", s)
    return s.strip("_") or "user_dataset"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--package",
        default="user_dataset_template",
        help="用户数据包文件夹（默认 user_dataset_template）",
    )
    args = ap.parse_args(argv)

    pkg = Path(args.package)
    if not pkg.is_absolute():
        pkg = ROOT / pkg

    try:
        info_path = pkg / "dataset_info.xlsx"
        exp, mapping = importer.read_dataset_info(info_path)
        files = importer.find_raw_files(pkg / "raw")
    except importer.UserInputError as e:
        print("\n[错误] " + str(e), file=sys.stderr)
        return 2

    src = files[0]
    ignored = [p.name for p in files[1:]]

    print(f"[1/6] 读取实验信息：{info_path.name}")
    print(f"[2/6] 读取数据文件：{src.name}")
    if ignored:
        print(f"      注意：raw 里还有 {ignored}，第一版只处理 {src.name}")

    raw = importer.read_any(src)
    df, conv_log = importer.to_canonical(raw, mapping, exp, src.name)
    df, n_dup = importer.drop_duplicate_timestamps(df)
    conv_log["n_duplicate_timestamps_dropped"] = n_dup

    print(f"[3/6] 转换为 canonical：{len(df)} 行")

    issues = validate.validate(df, exp, conv_log)

    # ---- protocol 解释：把"原始数据标签"与"平台算出的实际倍率"分开 -----
    # source_protocol_label：用户在 experiment.protocol 里填的原始标签（如 "CC_Cover5"）
    # effective_c_rate      ：max|I| / nominal_capacity（平台口径，恒以 A 计）
    # 二者不必相等（Cover5 是 cycler 的档位名；实际放电约 0.22 C）。
    source_protocol_label = str(exp.get("protocol", "")).strip() or "as_provided"
    effective_c_rate = None
    if df["current_A"].dropna().size:
        imax = float(np.nanmax(np.abs(df["current_A"].to_numpy(float))))
        nom = exp.get("nominal_capacity")
        if nom:
            try:
                effective_c_rate = imax / float(nom)
            except (TypeError, ValueError):
                effective_c_rate = None
    protocol_interpretation = {
        "source_protocol_label": source_protocol_label,
        "effective_c_rate": effective_c_rate,
        "note": (
            "source_protocol_label 是你在 experiment.protocol 里填写的原始档位/协议名；"
            "effective_c_rate = max|I| / nominal_capacity 是平台换算出的实际倍率。"
            "两者分开记录，勿把原始标签读成精确倍率。"
        ),
    }

    # 温度来源说明
    if exp.get("temperature") is None:
        has_t = (
            "cell_temperature_C" in df.columns
            and df["cell_temperature_C"].dropna().size > 0
        )
        issues.append(
            {
                "code": "AMBIENT_TEMPERATURE",
                "severity": "WARN",
                "message": (
                    "未填写环境温度。仿真将"
                    + (
                        "使用数据里温度列的中位数"
                        if has_t
                        else f"按平台默认 {25.0:g} C 假设"
                    )
                    + "（已记录为假设值，不是实测值）"
                ),
                "evidence": "temperature field empty in dataset_info.xlsx",
            }
        )
    else:
        issues.append(
            {
                "code": "AMBIENT_TEMPERATURE",
                "severity": "PASS",
                "message": f"使用你填写的环境温度 {float(exp['temperature']):g} C",
                "evidence": "user declared",
            }
        )

    summary = validate.summarize(issues)

    print(
        f"[4/6] 校验完成：{summary['n_checks']} 项，"
        f"严重 {summary['n_fail']}，警告 {summary['n_warn']}"
    )

    gate = parameter_gate(exp)
    print(
        f"[5/6] 参数集匹配："
        + (
            f"{gate['parameter_set']} (grade {gate['grade']})"
            if gate["available"]
            else "NOT AVAILABLE"
        )
    )

    out_dir = USER_OUT_ROOT / _safe_name(str(exp.get("dataset_name", "")))
    out_dir.mkdir(parents=True, exist_ok=True)

    canonical_path = out_dir / OUT_CANONICAL_FULL
    df.to_csv(canonical_path, index=False)

    pd.DataFrame(issues).to_csv(out_dir / OUT_ISSUES, index=False, encoding="utf-8-sig")
    df.head(200).to_csv(
        out_dir / OUT_CANONICAL_PREVIEW, index=False, encoding="utf-8-sig"
    )
    report.make_preview_png(df, out_dir / OUT_PREVIEW_PNG)
    report.make_validation_html(
        out_dir / OUT_VALIDATION_REPORT,
        exp,
        issues,
        summary,
        gate,
        conv_log,
        OUT_PREVIEW_PNG,
        canonical_rows=len(df),
        protocol_interpretation=protocol_interpretation,
    )

    manifest = {
        "dataset_name": str(exp.get("dataset_name", "")),
        "sample_id": str(exp.get("sample_id", "")),
        "experiment": {k: v for k, v in exp.items()},
        "source_file": src.name,
        "ignored_files": ignored,
        "canonical_path": str(canonical_path.relative_to(ROOT)).replace("\\", "/"),
        "n_rows": int(len(df)),
        "conversion": conv_log,
        "validation": summary,
        "protocol_interpretation": protocol_interpretation,
        "issues": issues,
        "parameter_gate": gate,
        "fitted_to_dataset": False,
        "note": (
            "Self-Service Data Onboarding Layer. "
            "Zero-fit baseline only: no fitting, no parameter identification."
        ),
    }
    (out_dir / OUT_MANIFEST).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    print(f"[6/6] 输出目录：{out_dir.relative_to(ROOT)}")
    print()
    print("=" * 56)
    print(f"  数据导入：{summary['import_status']}")
    if gate["available"]:
        print(f"  仿真：AVAILABLE  ->  {gate['parameter_set']} (grade {gate['grade']})")
    else:
        print("  仿真：NOT AVAILABLE")
        for b in gate.get("blockers", []):
            print(f"         原因：{b}")
    print("=" * 56)
    print(f"  报告：{(out_dir / OUT_VALIDATION_REPORT).name}")
    print("=" * 56)

    if summary["import_status"] == "FAIL":
        print("\n存在严重错误，已阻止仿真。请打开 validation_report.html 查看。")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

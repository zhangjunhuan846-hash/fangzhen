#!/usr/bin/env python3
# ============================================================
# 把石墨线的派生参数集导出成可归档的 JSON 清单
#
# 之前"参数集"只存在于进程内存里（运行时只读注入），没有文件。
# 这个脚本把每一套派生集写成 outputs/analysis/graphite_phaseB16/
# parameter_sets/<set_id>.json，包含：
#   scalars   数值条目快照
#   inputs    输入文件 + sha256 指纹（OCP 表 / D_s 表 / 元数据）
#   recipe    用什么函数、什么参数重建
#   non_scalars 函数条目（只记录，不序列化——诚实边界）
#
# 导出后立刻做一次闭环自检：重新加载 → 校验输入指纹 → 比对标量。
#
#   python scripts/export_graphite_parameter_sets.py
# ============================================================

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from parameters.export_parameter_set import (  # noqa: E402
    export_parameter_set,
    load_parameter_set,
    scalar_diff,
    summarise,
    verify_inputs,
)
from parameters.sintef_graphite_ds import (  # noqa: E402
    DS_GRADE,
    DS_PARAMETER_SET_IDS,
    build_ds_variant,
)

OUT_DIR = ROOT / "outputs" / "analysis" / "graphite_phaseB16" / "parameter_sets"
OCP_DIR = ROOT / "outputs" / "analysis" / "graphite_phaseB06" / "graphite_ocp_v2"
B16_DIR = ROOT / "outputs" / "analysis" / "graphite_phaseB16"
POCV_CELL = "4ccc47"          # the cell whose metadata/geometry the base uses
METADATA_CSV = ROOT / "data" / "metadata.csv"

DS_DIRS = {"b16v1": B16_DIR / "v1", "b16v2": B16_DIR / "v2"}
BRANCHES = ("lithiation", "delithiation")


def _inputs_for(ds_dir: Path) -> list:
    return [
        (OCP_DIR / "graphite_ocp_lithiation.csv", "OCP lithiation branch (B0.6)"),
        (OCP_DIR / "graphite_ocp_delithiation.csv",
         "OCP delithiation branch (B0.6)"),
        (OCP_DIR / "ocp_extraction_provenance.json", "OCP extraction provenance"),
        (ds_dir / "graphite_Ds_app.csv", "apparent D_s(SOC) table"),
        (ds_dir / "gitt_ds_app_provenance.json", "D_s extraction provenance"),
        (METADATA_CSV, "cell geometry / loading metadata"),
    ]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    args = ap.parse_args(argv)

    out_dir = Path(args.out_dir)
    index = []

    for suffix, ds_dir in DS_DIRS.items():
        for branch in BRANCHES:
            set_id = DS_PARAMETER_SET_IDS[branch] + f"_{suffix}"
            _base, pv, info = build_ds_variant(
                branch, POCV_CELL, ocp_dir=OCP_DIR, ds_dir=ds_dir,
            )
            path = export_parameter_set(
                pv,
                out_dir / f"{set_id}.json",
                set_id=set_id,
                provenance={
                    "grade": DS_GRADE,
                    "branch": branch,
                    "d_s_cm2_s_range": [
                        float(info["table"]["Ds_app_cm2_s"].min()),
                        float(info["table"]["Ds_app_cm2_s"].max()),
                    ],
                    "quantity": (
                        "APPARENT/effective solid-state diffusivity from GITT "
                        "under the Weppner-Huggins single-particle model - NOT "
                        "an intrinsic material coefficient, NOT validation"
                    ),
                    "fit_form": ("quadratic (equilibrium drift separated)"
                                 if suffix == "b16v2"
                                 else "first order V = a + m*sqrt(t)"),
                },
                inputs=_inputs_for(ds_dir),
                recipe={
                    "module": "parameters.sintef_graphite_ds",
                    "function": "build_ds_variant",
                    "kwargs": {
                        "branch": branch,
                        "cell": POCV_CELL,
                        "ocp_dir": str(OCP_DIR.relative_to(ROOT)),
                        "ds_dir": str(ds_dir.relative_to(ROOT)),
                    },
                    "note": (
                        "函数条目（实测 OCP、D_s 插值器）由这个 recipe 重建；"
                        "inputs 的 sha256 保证重建用的是同一批输入。"
                    ),
                },
                metadata={"cell": POCV_CELL, "phase": "B1.6"},
            )

            # ---- 闭环自检：加载 -> 校验指纹 -> 比对标量 ----
            loaded = load_parameter_set(path)
            verify_inputs(loaded, strict=True)
            diff = scalar_diff(pv, loaded)
            if diff:
                raise SystemExit(
                    f"{set_id}: 导出的标量与活着的参数集不一致："
                    f"{list(diff)[:5]}"
                )
            s = summarise(loaded)
            index.append({"set_id": set_id, "file": path.name, **s})
            print(f"  {set_id:<38} scalars={s['n_scalars']:<4} "
                  f"callables={s['n_non_scalars']:<3} "
                  f"inputs={s['n_inputs']}  -> {path.name}")

    index_path = out_dir / "parameter_sets_index.json"
    index_path.write_text(
        json.dumps({"sets": index,
                    "note": ("每套派生集的 JSON 清单；inputs 里带 sha256，"
                             "recipe 说明重建方式。函数条目不入文件。")},
                   indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\n参数集清单：{index_path.relative_to(ROOT)}  （{len(index)} 套）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

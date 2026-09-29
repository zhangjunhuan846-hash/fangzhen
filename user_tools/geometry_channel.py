#!/usr/bin/env python3
# ============================================================
# 几何通路自检 —— 命令行入口（缺口 1 的可用形态）
#
# 为什么需要一个入口，而不只是一个模块
#   实测值到模型没有通路这件事，卡点不是"不会写代码"，而是
#   **数据到手那天没人知道该填哪四个数、填完长什么样**。
#   所以入口做三件事：
#     ① 报缺哪几项（不是"失败"，是"还没做实验"）
#     ② 填齐了就给出**可直接用的** parameter_overrides + 逐键来源
#     ③ 打印报告行（本轮用的是哪个 R）—— 不打印就等于把粒径变化
#        读成扩散变化（D ∝ R²）
#
# 用法
#   # 单个样品
#   python -m user_tools.geometry_channel \
#       --metadata templates/commercial_graphite_ht/metadata/CG-AR.yaml
#
#   # 整条梯度（目录），一眼看出谁填齐了
#   python -m user_tools.geometry_channel \
#       --series templates/commercial_graphite_ht/metadata
#
#   # 写成分散可引用的 JSON（run_record 的 geometry_source 从这里取）
#   python -m user_tools.geometry_channel \
#       --metadata .../CG-AR.yaml --out outputs/geometry/CG-AR.json
#
# 退出码
#   0 = 全部完整；1 = 有样品不完整（**不是错误**：那是"数据还没到"）；
#   2 = 参数/文件错误（该修的修）。
# ============================================================

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from governance.geometry_channel import (  # noqa: E402
    CHANNEL_KEYS,
    REQUIRED_MEASUREMENTS,
    SCALE_ALIGNMENT_KNOBS,
    geometry_channel_conflicts,
    geometry_override_channel,
    radius_report_line,
)

OUT_ROOT = ROOT / "outputs" / "geometry"


def _one(path: Path, *, require_complete: bool) -> tuple[dict, bool]:
    rec = geometry_override_channel(path, require_complete=require_complete)
    print(f"== {rec['sample_id'] or path.stem}  ({path.name})")
    if rec["incomplete"]:
        print("   状态：**不完整** —— 缺：")
        for m in rec["missing"]:
            print(f"     - {m}")
        print("   （不部分覆盖：R_p 与涂层厚度同时进 tau = D·t/R²；")
        print("     只换一部分会得到一个既不是参数集几何、也不是实测几何的混合态）")
        print()
        return rec, False

    print("   状态：完整")
    for key in CHANNEL_KEYS:
        val = rec["parameter_overrides"][key]
        src = rec["parameter_override_sources"][key]
        print(f"   - {key}")
        print(f"       {val:.6g}   ← {src['origin']}")
        print(f"       公式：{src['formula']}")
    print(f"   {radius_report_line(rec)}")
    print(f"   未覆盖（本通路不猜）：{list(rec['not_covered'])}")
    print()
    return rec, True


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="几何实测值 → 模型参数通路（缺口 1）"
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--metadata", help="单个材料元数据 yaml")
    src.add_argument("--series", help="一个目录（其下所有 *.yaml）")
    p.add_argument(
        "--require-complete", action="store_true",
        help="缺任一项即报错退出（默认只报告，因为数据可能还没到）",
    )
    p.add_argument("--out", default=None,
                   help="把完整样品的覆盖写成一个 JSON（不完整的不写，避免半成品外流）")
    p.add_argument(
        "--scale-alignment", default="check",
        choices=("check", "align", "assume"),
        help="预先声明这次要配的尺度对齐模式，用于冲突检查（默认 check）",
    )
    args = p.parse_args(argv)

    if args.metadata:
        paths = [Path(args.metadata)]
    else:
        d = Path(args.series)
        if not d.is_dir():
            print(f"不是目录：{d}", file=sys.stderr)
            return 2
        paths = sorted(d.glob("*.yaml")) + sorted(d.glob("*.yml"))
        if not paths:
            print(f"{d}: 下没有 yaml", file=sys.stderr)
            return 2

    # 先做冲突检查（早于读文件 —— 冲突是配置问题，不是数据问题）
    conflicts = geometry_channel_conflicts(scale_alignment_mode=args.scale_alignment)
    if conflicts:
        print(f"⚠️ 与尺度对齐模式 '{args.scale_alignment}' 冲突：", file=sys.stderr)
        for c in conflicts:
            print(f"  - {c}", file=sys.stderr)
        print(
            "\n二者只能取一：几何通路改 R_p/厚度，尺度对齐门改 footprint 尺寸。"
            "同时生效 = 容量被缩放两次。",
            file=sys.stderr,
        )
        return 2

    results = []
    all_complete = True
    for path in paths:
        try:
            rec, ok = _one(path, require_complete=args.require_complete)
        except Exception as exc:  # noqa: BLE001 — 元数据本身坏了要走"该修"那条退出码
            print(f"== {path.name}: 读取/校验失败：{type(exc).__name__}: {exc}",
                  file=sys.stderr)
            return 2
        results.append(rec)
        all_complete = all_complete and ok

    n_ok = sum(1 for r in results if r["complete"])
    print(f"—— 合计 {len(results)} 份，完整 {n_ok}，不完整 {len(results) - n_ok}")
    print(f"—— 需要的四个实测量：{list(REQUIRED_MEASUREMENTS)}")
    print(f"—— 本通路覆盖的键：{list(CHANNEL_KEYS)}")
    print(f"—— 尺度对齐门用的键（与本通路互斥）：{list(SCALE_ALIGNMENT_KNOBS)}")

    if args.out:
        complete = [r for r in results if r["complete"]]
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {
                    "channel_keys": list(CHANNEL_KEYS),
                    "required_measurements": list(REQUIRED_MEASUREMENTS),
                    "samples": [
                        {
                            "sample_id": r["sample_id"],
                            "metadata_path": r["metadata_path"],
                            "parameter_overrides": r["parameter_overrides"],
                            "parameter_override_sources": r["parameter_override_sources"],
                            "radius_used_m": r["radius_used_m"],
                            "report_line": radius_report_line(r),
                        }
                        for r in complete
                    ],
                    "incomplete": [
                        {"sample_id": r["sample_id"], "missing": r["missing"]}
                        for r in results if not r["complete"]
                    ],
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"—— 已写出：{out}（只含完整样品 {len(complete)} 份）")

    return 0 if all_complete else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# ============================================================
# sigma_noise 标定 —— 命令行入口（Step 0 就能跑）
#
# 为什么现在就要有这个入口
#   预注册的 N1 判据（零激励窗口代价面**精确平坦**）与"静置是否够长"
#   都依赖噪声底；没有它，这两条判据是**空的**。
#   而标定它**不需要任何样品、任何设备到货** —— 空跑 30 min 静置即可。
#   所以在整条链里，这是**今天就能做完、且卡着别人**的一步。
#
# 用法
#   # 1) 从仪器导出的 CSV 标定（列名可指定）
#   python -m user_tools.sigma_noise \
#       --csv step0_rest.csv --t-col time_s --v-col voltage_V \
#       --out outputs/noise_floor/step0_rest.md --k 3
#
#   # 2) 先看清 CSV 长什么样（不确定列名时用这个）
#   python -m user_tools.sigma_noise --csv step0_rest.csv --inspect
#
#   # 3) 不给 k：只标定 sigma，不给判据阈值
#   python -m user_tools.sigma_noise --csv step0_rest.csv
#
# 输出（都是 additive，不碰 outputs/platform/ 下的任何东西）
#   outputs/noise_floor/<名字>.md    人类可读报告（直接贴进方案）
#   outputs/noise_floor/<名字>.json  机器可读（run_record 的 sigma_noise_mV 从这里取）
#
# 纪律
#   · **不做任何平滑**。平滑会把噪声一起抹掉，标出来的 sigma 偏小，
#     而 N1 会因此被一个"看起来很小"的噪声底满足掉。
#   · 时间列必须单调递增；非递增直接报错（平台在 canonical 校验里
#     对同一件事也这么做，理由一致：插值会静默吃掉重复点）。
#   · 单位：输入电压按 **V** 读（与平台 canonical 一致），报告里写成 mV。
#     如果你的记录是 mV，请用 --v-unit mV —— 猜单位正是这个平台
#     已经拦过的那类静默错误。
# ============================================================

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from governance.noise_floor import (  # noqa: E402
    DEFAULT_REST_WINDOW_S,
    K_PREREGISTRATION_RELPATH,
    NoiseFloorUnavailable,
    calibrate_noise_floor,
    load_preregistered_k,
    render_noise_floor_report,
)

OUT_ROOT = ROOT / "outputs" / "noise_floor"

#: 列名候选（按优先级）。只在 --t-col/--v-col 没给时才用，且**报出用了哪个**
#: —— 静默挑一列是这一类脚本最常见的错。
T_CANDIDATES = ("time_s", "time", "t", "test_time_s", "time/s", "Time")
V_CANDIDATES = ("voltage_V", "voltage", "v", "ewe_v", "Ewe/V", "Voltage")


def _read_csv(path: Path, t_col: str | None, v_col: str | None,
              v_unit: str) -> tuple[list[float], list[float], str, str]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        if not rows:
            raise ValueError(f"{path}: 没有任何数据行")
        fields = list(rows[0].keys())

    def pick(explicit: str | None, candidates, what: str) -> str:
        if explicit:
            if explicit not in fields:
                raise ValueError(
                    f"{path}: 指定的 {what} 列 {explicit!r} 不在文件里。"
                    f"可用列：{fields}"
                )
            return explicit
        hits = [c for c in candidates if c in fields]
        if len(hits) == 1:
            return hits[0]
        if not hits:
            raise ValueError(
                f"{path}: 认不出{what}列。请用 --t-col / --v-col 指定。"
                f"可用列：{fields}"
            )
        raise ValueError(
            f"{path}: {what}列有多个候选 {hits}，不替你挑 —— "
            f"请用 --t-col / --v-col 指定其中一个。"
        )

    tc = pick(t_col, T_CANDIDATES, "时间")
    vc = pick(v_col, V_CANDIDATES, "电压")

    t: list[float] = []
    v: list[float] = []
    for i, row in enumerate(rows, start=2):  # 2 = 表头后第一行
        try:
            tv = float(row[tc])
            vv = float(row[vc])
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{path}:{i}: 列 {tc!r}/{vc!r} 不是数字（{exc}）"
            ) from exc
        t.append(tv)
        v.append(vv)

    if v_unit == "mV":
        v = [x / 1000.0 for x in v]
    elif v_unit != "V":
        raise ValueError(f"--v-unit 只能是 V 或 mV，得到 {v_unit!r}")

    return t, v, tc, vc


def _inspect(path: Path) -> int:
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    if not rows:
        print(f"{path}: 空文件")
        return 1
    fields = list(rows[0].keys())
    print(f"文件：{path}")
    print(f"行数：{len(rows)}")
    print("列名：")
    for c in fields:
        vals = [r.get(c, "") for r in rows[:3]]
        print(f"  - {c!r}  前 3 个值：{vals}")
    print("\n时间列候选：", [c for c in T_CANDIDATES if c in fields] or "无")
    print("电压列候选：", [c for c in V_CANDIDATES if c in fields] or "无")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="空跑静置段 → sigma_noise 标定（预注册 N1 判据的输入）"
    )
    parser.add_argument("--csv", required=True, help="空跑静置记录（CSV）")
    parser.add_argument("--t-col", default=None, help="时间列名（秒）")
    parser.add_argument("--v-col", default=None, help="电压列名")
    parser.add_argument(
        "--v-unit", default="V", choices=("V", "mV"),
        help="电压单位（默认 V，与平台 canonical 一致）",
    )
    parser.add_argument(
        "--rest-window-s", type=float, default=DEFAULT_REST_WINDOW_S,
        help=f"只取最后这段时间（默认 {DEFAULT_REST_WINDOW_S:g} s = 30 min）",
    )
    parser.add_argument(
        "--estimator", default="mad", choices=("mad", "std"),
        help="尺度估计量（默认 mad，稳健；std 只做对照）",
    )
    parser.add_argument(
        "--k", type=float, default=None,
        help="判据倍数：max|dV| <= k * sigma_noise。**优先用预注册文件**，"
             "此参数只在临时覆盖时用（k 来源会记进产物）",
    )
    parser.add_argument(
        "--prereg", default=None,
        help=f"预注册 k 的文件路径（默认 {K_PREREGISTRATION_RELPATH}）",
    )
    parser.add_argument(
        "--voltage-range-V", type=float, default=5.0,
        help="仪器量程，用于算分辨率下限；给 0 跳过该检查",
    )
    parser.add_argument("--name", default=None, help="产物名（默认取 CSV 文件名）")
    parser.add_argument("--out", default=None, help="报告路径（.md）")
    parser.add_argument("--inspect", action="store_true",
                        help="只打印列名与候选，不标定")
    args = parser.parse_args(argv)

    csv_path = Path(args.csv)
    if not csv_path.is_file():
        print(f"找不到文件：{csv_path}", file=sys.stderr)
        return 2

    if args.inspect:
        return _inspect(csv_path)

    try:
        t, v, tc, vc = _read_csv(csv_path, args.t_col, args.v_col, args.v_unit)
    except ValueError as exc:
        print(f"读取出错：{exc}", file=sys.stderr)
        return 2

    # 单调性：与平台 canonical 校验同一口径（插值会静默吃掉重复点）
    bad = [i for i in range(1, len(t)) if t[i] <= t[i - 1]]
    if bad:
        print(
            f"时间列不是严格递增（{len(bad)} 处，首个在第 {bad[0] + 1} 行）。"
            f"平台在 canonical 校验里同样拒绝 —— 插值会静默吃掉重复时间点。",
            file=sys.stderr,
        )
        return 2

    try:
        floor = calibrate_noise_floor(
            t, v,
            rest_window_s=args.rest_window_s,
            voltage_range_V=(args.voltage_range_V or None),
            estimator=args.estimator,
        )
    except NoiseFloorUnavailable as exc:
        print(f"无法标定：{exc}", file=sys.stderr)
        return 3

    name = args.name or csv_path.stem
    out_md = Path(args.out) if args.out else OUT_ROOT / f"{name}.md"
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json = out_md.with_suffix(".json")

    # ---- k 的三种来源，优先级：命令行 > 预注册文件 > 无 ----
    # 关键：**报告与 JSON 必须用同一个 k**。早先的实现里报告按 k=3 渲染、
    # JSON 却写 "k": null，两份产物自相矛盾 —— 引用哪一份都会出错。
    k_source = "none"
    k_value = None
    if args.k is not None:
        k_value = float(args.k)
        k_source = "cli"
    else:
        k_value = load_preregistered_k(args.prereg)
        if k_value is not None:
            k_source = "prereg_file"

    lines = [
        f"# sigma_noise 标定 —— {name}",
        "",
        f"- 源文件：`{csv_path}`",
        f"- 用列：`{tc}` / `{vc}`（单位 {args.v_unit}）",
        f"- 参数：rest_window={args.rest_window_s:g} s，"
        f"estimator={args.estimator}，量程={args.voltage_range_V} V",
        f"- k 来源：{k_source}",
        "",
    ]
    lines.append(render_noise_floor_report(floor, k=k_value))
    if k_source == "none":
        lines.append("")
        lines.append(
            f"> ⚠️ 没有可用的 `k`（命令行没给 `--k`，也没有 "
            f"`{args.prereg or K_PREREGISTRATION_RELPATH}`）。"
            f"**上面那个阈值不是判据**，只是示例占位；"
            f"JSON 里的 `criterion` 字段因此**不存在**。"
            f"把 k 写进预注册文件或传 `--k` 后重跑。"
        )

    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    payload = {
        "source_csv": str(csv_path),
        "columns": {"time": tc, "voltage": vc},
        "voltage_unit_input": args.v_unit,
        "params": {
            "rest_window_s": args.rest_window_s,
            "estimator": args.estimator,
            "voltage_range_V": args.voltage_range_V,
        },
        "k": k_value,
        "k_source": k_source,
        **floor.as_dict(),
    }
    # criterion 只在**真的有 k** 时出现。没有 k 就不写这个键 ——
    # 写一个 example-k 的阈值出来，下游会当成判据引用。
    if k_value is not None:
        payload["criterion"] = floor.calibrated_threshold_mV(k_value)
    else:
        payload["criterion"] = None
        payload["criterion_unavailable_reason"] = (
            "k 未预注册：命令行未给 --k，且 "
            f"{args.prereg or K_PREREGISTRATION_RELPATH} 不存在或 k 为空"
        )
        payload["prereg_path"] = str(args.prereg or K_PREREGISTRATION_RELPATH)
    out_json.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"sigma_noise = {floor.sigma_mV:.4f} mV")
    print(f"  n={floor.n_points} 点 / {floor.window_s:.0f} s，"
          f"漂移 {floor.drift_mV_per_h:+.4f} mV/h")
    if floor.resolution_limited:
        print(f"  ⚠️ 受分辨率限制（下限 {floor.resolution_floor_mV:.4f} mV）"
              f"—— 报出的是仪器分辨率，不是噪声")
    if k_value is None:
        print("  ⚠️ k 未预注册 —— 报告与 JSON 里都**没有**可引用的判据阈值")
    else:
        print(f"  判据：max|ΔV| <= {k_value:g} x sigma_noise = "
              f"{k_value * floor.sigma_mV:.3f} mV（k 来源：{k_source}）")
    print(f"报告：{out_md}")
    print(f"JSON：{out_json}")
    print()
    print("把 sigma_noise_mV 填进 run_record.yaml 的 sigma_noise_mV；")
    print("N1 判据写成 max|ΔV| <= k * sigma_noise，并给出 k。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

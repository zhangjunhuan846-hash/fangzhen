# ============================================================
# 参数辨识报告生成器（自动报告）
#
# 为什么要有它
#   接上真实数据以后，每一步都会产出不同类型的产物（回放指标 CSV、逐窗口
#   带宽表、参数覆盖记录）。把这些东西手抄成"结论"是本平台最容易出错的一步：
#     · 手抄会把 not measured 写成"不显著"，把 bounded 写成"是 X"
#     · 手抄会漏掉判据（水平、上限、扫描范围、分辨率），而带宽离开这几样没法读
#     · 手抄会在真实材料上沿用 benchmark 的句子（"恢复误差 0.000"）
#   所以报告由代码从产物直接生成，判定词由 governance.analysis_mode 给出，
#   且 material 模式下 benchmark 专属字段**进不来**。
#
# 用法
#   # 1) 从 G6.1c 的逐窗口地图生成（真实数据路径）
#   python -m identification.parameter_report \
#       --windows outputs/fitting/g6.1c/g6_1c_window_map_charge.csv \
#       --dataset dlr_gitt --cell Hydra.0b \
#       --level-mV 1.0 --limit-dex 0.30 --scan-half-dex 1.0 \
#       --mode material --out outputs/reports/dlr_gitt_charge.md
#
#   # 2) benchmark 模式（合成真值存在）才允许带上 recovery 列
#   ... --mode benchmark --include-recovery
#   而 --mode material --include-recovery 会**直接报错**（这是设计）
#
# 输入契约
#   ``--windows`` 指向 G6.1c 的逐窗口表，需要这些列（缺了就报缺哪列，不猜）：
#       protocol_id, applicable, band_width_dex, band_left_dex, band_right_dex,
#       band_truncated, band_resolution_dex
#   可选的列（有就写进报告，没有就留空）：
#       soc_lithiation_fraction, v_pre_V, measured_abs_dv_pulse_mV,
#       n_unreachable, pulse_c_rate
# ============================================================

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from governance.analysis_mode import (
    MODE_BENCHMARK,
    MODE_MATERIAL,
    VERDICT_BOUNDED,
    VERDICT_GLOSS,
    VERDICT_IDENTIFIABLE,
    VERDICT_NOT_MEASURED,
    assert_benchmark_only,
    check_payload,
    classify_band,
    normalise_mode,
    party_role_caution,
)

ROOT = Path(__file__).resolve().parents[1]

#: 扫描半宽（dex）。必须与产生这张表的运行一致，否则"截断"判错。
DEFAULT_SCAN_HALF_DEX = 1.0

#: 把一侧距离判成"撞到扫描边界"的容差。
EDGE_TOLERANCE_DEX = 1e-6

#: G6.1c 地图里必须有的列
REQUIRED_WINDOW_COLUMNS = (
    "protocol_id", "applicable", "band_width_dex", "band_left_dex",
    "band_right_dex", "band_truncated", "band_resolution_dex",
)

#: 每个参数需要什么证据才能给判定。没有证据 = not_measured，不许编结论。
PARAMETER_EVIDENCE: Dict[str, Tuple[str, ...]] = {
    "Ds": ("GITT",),
    "k0": ("EIS",),
    "Rct": ("EIS",),
}


class ReportInputError(ValueError):
    """输入产物不满足报告契约。"""


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in ("true", "1", "yes", "y", "t")


def _finite(value: Any) -> Optional[float]:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if np.isfinite(num) else None


@dataclass(frozen=True)
class ParameterProbe:
    """一个参数的判定（含依据、来源、必须一起引用的说明）。"""

    parameter: str
    verdict: str
    protocol_id: str = ""
    band: Optional[Dict[str, Any]] = None
    rationale: str = ""
    evidence: Tuple[str, ...] = ()
    source: str = "not_measured"
    note: str = ""

    def as_payload(self) -> Dict[str, Any]:
        """只带报告要渲染的字段。

        刻意**不**把上游 CSV 的行原样带进来：G6.1c 的表里有
        ``cost_at_truth_mV2`` 之类 benchmark 专属列，带进来会被
        ``check_payload`` 拦下 —— 拦得对，因为真实材料分析里没有 truth。
        """
        return {
            "parameter": self.parameter,
            "verdict": self.verdict,
            "protocol_id": self.protocol_id,
            "band_width_dex": (self.band or {}).get("width_dex"),
            "band_resolution_dex": (self.band or {}).get("resolution_dex"),
            "truncated_left": (self.band or {}).get("truncated_left"),
            "truncated_right": (self.band or {}).get("truncated_right"),
            "evidence": list(self.evidence),
            "source": self.source,
        }


# ------------------------------------------------------------------
# 从逐窗口表重建带宽测量
# ------------------------------------------------------------------
def band_from_window_row(
    row: Dict[str, Any],
    *,
    scan_half_dex: float = DEFAULT_SCAN_HALF_DEX,
    tolerance: float = EDGE_TOLERANCE_DEX,
) -> Optional[Dict[str, Any]]:
    """把地图表的一行重建成 :func:`classify_band` 认识的带宽 dict。

    **单侧截断是从距离推的**（表里只存了"有没有截断"，没存哪一侧）：
    估计器在撞界时会把带边缘**吸附到扫描边界**，所以
    ``left_dex ≈ scan_half_dex`` 就等价于左侧截断。容差是 1e-6 dex，
    远小于 0.05 dex 的网格 —— 吸附是精确的，不是近似的。

    推不出来（既不截断、两侧也不贴边）时返回 ``truncated_left=right=True``，
    让判定落到最保守的 unconstrained，而不是猜一个方向。
    """
    width = _finite(row.get("band_width_dex"))
    if width is None:
        return None
    left = _finite(row.get("band_left_dex"))
    right = _finite(row.get("band_right_dex"))
    any_trunc = _as_bool(row.get("band_truncated"))
    resolution = _finite(row.get("band_resolution_dex"))

    if not any_trunc:
        trunc_l = trunc_r = False
    else:
        left_at_edge = left is not None and left >= scan_half_dex - tolerance
        right_at_edge = right is not None and right >= scan_half_dex - tolerance
        if left_at_edge or right_at_edge:
            trunc_l, trunc_r = left_at_edge, right_at_edge
        else:
            # 表里说截断了但两侧都不贴边：信息不足 → 按最保守处理
            trunc_l = trunc_r = True

    return {
        "width_dex": width,
        "left_dex": left,
        "right_dex": right,
        "truncated_left": bool(trunc_l),
        "truncated_right": bool(trunc_r),
        "resolution_dex": resolution,
    }


def best_window_probe(
    windows: pd.DataFrame,
    *,
    parameter: str = "Ds",
    protocol_prefix: str = "",
    level_mV: float = 1.0,
    limit_dex: float = 0.30,
    scan_half_dex: float = DEFAULT_SCAN_HALF_DEX,
    evidence: Sequence[str] = ("GITT",),
) -> Tuple[ParameterProbe, Dict[str, Any]]:
    """在逐窗口表里挑"最能把该参数定下来"的窗口，并给出判定。

    选择规则（先声明再跑）：**未截断优先**，同组内取带宽最小；若一个未截断的
    都没有，退而取带宽最小者并在说明里写明它被截断。
    """
    missing = [c for c in REQUIRED_WINDOW_COLUMNS if c not in windows.columns]
    if missing:
        raise ReportInputError(
            f"逐窗口表缺少列 {missing}；现有列 {list(windows.columns)}"
        )

    df = windows
    if protocol_prefix:
        df = df[df["protocol_id"].astype(str).str.startswith(protocol_prefix)]
    if df.empty:
        return (
            ParameterProbe(
                parameter=parameter, verdict=VERDICT_NOT_MEASURED,
                rationale=f"没有匹配协议前缀 '{protocol_prefix}' 的窗口",
                evidence=tuple(evidence),
            ),
            {"n_rows": 0},
        )

    applicable = df[df["applicable"].map(_as_bool)]
    rows: List[Dict[str, Any]] = []
    for _, row in applicable.iterrows():
        band = band_from_window_row(row.to_dict(), scan_half_dex=scan_half_dex)
        if band is None:
            continue
        rows.append({"band": band, "row": row.to_dict()})

    summary = {
        "n_rows": int(len(df)),
        "n_applicable": int(len(applicable)),
        "n_with_band": int(len(rows)),
        "n_never_reaching_level": int(len(applicable) - len(rows)),
        "level_mV": float(level_mV),
        "limit_dex": float(limit_dex),
        "scan_half_dex": float(scan_half_dex),
    }
    if not rows:
        return (
            ParameterProbe(
                parameter=parameter, verdict=VERDICT_NOT_MEASURED,
                rationale=(
                    f"{len(applicable)} 个可回放窗口里没有一个能在 "
                    f"±{scan_half_dex:g} dex 内把观测推到 {level_mV:g} mV"
                ),
                evidence=tuple(evidence),
            ),
            summary,
        )

    closed = [r for r in rows if not r["band"]["truncated_left"]
              and not r["band"]["truncated_right"]]
    pool = closed if closed else rows
    best = min(pool, key=lambda r: r["band"]["width_dex"])
    summary["n_untruncated"] = int(len(closed))
    summary["n_within_limit"] = int(sum(
        1 for r in closed if r["band"]["width_dex"] <= limit_dex
    ))
    summary["best_protocol_id"] = str(best["row"]["protocol_id"])
    summary["best_width_dex"] = float(best["band"]["width_dex"])
    summary["best_is_closed"] = best in closed

    verdict = classify_band(
        best["band"], level_mV=level_mV, limit_dex=limit_dex,
        scan_range_dex=2.0 * scan_half_dex,
    )
    notes = []
    if not summary["best_is_closed"]:
        notes.append("最佳窗口自身被扫描边界截断，判定按最保守口径给出")
    n_unreach = _finite(best["row"].get("n_unreachable"))
    if n_unreach:
        notes.append(f"该窗口有 {int(n_unreach)} 个探针点不可达（模型有效域边缘）")
    soc = _finite(best["row"].get("soc_lithiation_fraction"))
    if soc is not None:
        notes.append(f"x0 = {soc:.4f}")
    dvp = _finite(best["row"].get("measured_abs_dv_pulse_mV"))
    if dvp is not None:
        notes.append(f"实测脉冲 |dV| = {dvp:.1f} mV")

    return (
        ParameterProbe(
            parameter=parameter,
            verdict=verdict["verdict"],
            protocol_id=str(best["row"]["protocol_id"]),
            band=best["band"],
            rationale=verdict["reason"],
            evidence=tuple(evidence),
            source="gitt_fitting" if parameter == "Ds" else "inferred",
            note="；".join(notes),
        ),
        summary,
    )


def unmeasured_probes(
    parameters: Sequence[str] = ("k0", "Rct"),
    *,
    available_techniques: Sequence[str] = (),
) -> List[ParameterProbe]:
    """没有相应激励的参数：写 not_measured，并说明缺什么。

    这是本模块存在的理由之一：**不许把"没测"写成"不显著"**。
    """
    out = []
    have = {str(t).strip() for t in available_techniques}
    for name in parameters:
        needed = PARAMETER_EVIDENCE.get(name, ())
        missing = [t for t in needed if t not in have]
        if needed and not missing:
            # **第三种状态**：数据在手，但平台没有从这个激励拟合该参数的通路。
            # 沿用"没有 EIS 测量"那句话在有 EIS 时是**假的**，而下一批实验
            # 就会带 EIS 进来 —— 报告会当场说谎。所以分开写；判定词仍然是
            # not_measured（没有估计值就是没有），但理由必须指向通路而不是数据。
            rationale = (
                f"{'/'.join(needed)} 已测，但平台当前没有从它拟合 {name} 的通路"
                f"⇒ 这与「没测」是两件事，但同样**不能**给判定；"
                f"要出 {name} 必须先把通路建起来"
            )
            note = "measured_but_no_fitting_pathway"
        else:
            rationale = (
                f"本数据集没有 {'/'.join(needed)} 测量"
                + (f"（缺 {'/'.join(missing)}）" if missing else "")
                if needed else "本数据集没有该参数所需激励"
            )
            note = ""
        out.append(ParameterProbe(
            parameter=name,
            verdict=VERDICT_NOT_MEASURED,
            rationale=rationale,
            evidence=tuple(needed),
            source="not_measured",
            note=note,
        ))
    return out


# ------------------------------------------------------------------
# 渲染
# ------------------------------------------------------------------
def render_report(
    probes: Sequence[ParameterProbe],
    *,
    dataset: str,
    cell: str = "",
    analysis_mode: str = MODE_MATERIAL,
    level_mV: float = 1.0,
    limit_dex: float = 0.30,
    scan_half_dex: float = DEFAULT_SCAN_HALF_DEX,
    dataset_role: Optional[str] = None,
    material_meta: Optional[Dict[str, Any]] = None,
    windows_path: Optional[str] = None,
    summary: Optional[Dict[str, Any]] = None,
    extra_caveats: Sequence[str] = (),
    include_recovery: bool = False,
) -> str:
    """生成 markdown 报告。material 模式下 truth/recovery 字段进不来。"""
    mode = normalise_mode(analysis_mode)
    if include_recovery:
        assert_benchmark_only(
            mode, "include_recovery（synthetic truth 恢复列）",
            context=f"{dataset}/{cell}",
        )

    # 先过治理门：载荷里出现 benchmark 专属字段就会在这里炸
    check_payload(mode, [p.as_payload() for p in probes], where="probes")

    lines: List[str] = []
    head = f"{dataset}" + (f"/{cell}" if cell else "")
    lines.append(f"# 参数可辨识性报告 — {head}")
    lines.append("")
    lines.append(f"- 分析模式：`{mode}` —— "
                 f"{'允许 synthetic truth / truth recovery' if mode == MODE_BENCHMARK else '真实材料分析，禁止 synthetic truth / truth recovery'}")
    lines.append(f"- 判据：**{level_mV:g} mV** 水平上的带宽上限 "
                 f"**{limit_dex:.3f} dex**；扫描 ±{scan_half_dex:g} dex"
                 f"（共 {2 * scan_half_dex:.1f} dex）")
    lines.append(f"- 输入产物：`{windows_path}`" if windows_path else "")
    if dataset_role:
        lines.append(f"- `dataset_role`: `{dataset_role}`")

    if summary:
        lines.append("")
        lines.append("## 扫描概况")
        lines.append("")
        lines.append(
            f"- 窗口 {summary.get('n_rows', '?')} 个，其中可回放 "
            f"{summary.get('n_applicable', '?')} 个；"
            f"{summary.get('n_never_reaching_level', '?')} 个在整个扫描区间内"
            f"连 {level_mV:g} mV 都推不到"
        )
        if "n_untruncated" in summary:
            lines.append(
                f"- 未截断 {summary['n_untruncated']} 个；其中带宽低于判据的 "
                f"**{summary.get('n_within_limit', 0)} 个**"
            )

    lines.append("")
    lines.append("## 判定")
    lines.append("")
    lines.append("| 参数 | 判定 | 依据协议 | 带宽 (dex) | 分辨率 (dex) | 证据 | 说明 |")
    lines.append("|---|---|---|---|---|---|---|")
    for probe in probes:
        band = probe.band or {}
        width = band.get("width_dex")
        res = band.get("resolution_dex")
        lines.append(
            f"| `{probe.parameter}` | **{probe.verdict}** | "
            f"{('`' + probe.protocol_id + '`') if probe.protocol_id else '—'} | "
            f"{('%.4f' % width) if width is not None else '—'} | "
            f"{('%.3f' % res) if res is not None else '—'} | "
            f"{'/'.join(probe.evidence) if probe.evidence else '—'} | "
            f"{(probe.rationale or '').replace('|', chr(92) + '|')}"
            f"{('；' + probe.note).replace('|', chr(92) + '|') if probe.note else ''} |"
        )

    lines.append("")
    lines.append("## 一句话汇总")
    lines.append("")
    lines.append(f"```text")
    lines.append(f"{head}")
    for probe in probes:
        lines.append(f"  {probe.parameter:<4s}: {probe.verdict}"
                     + (f"  ({probe.protocol_id})" if probe.protocol_id else "")
                     + (f"  [{VERDICT_GLOSS.get(probe.verdict, '')}]"
                        if probe.verdict != VERDICT_IDENTIFIABLE else ""))
    lines.append("```")

    bounded = [p for p in probes if p.verdict == VERDICT_BOUNDED]
    if bounded:
        names = ", ".join(f"`{p.parameter}`" for p in bounded)
        lines.append("")
        lines.append(f"> 措辞要求：{names} 的判定是 **bounded**。"
                     f"对应的规范表述是 —— "
                     f"*the tested excitation constrained the parameter only "
                     f"within a one-sided sensitivity region, providing bounds "
                     f"rather than point estimates*. **不要**写成"
                     f"\"无法辨识\"（那个激励确实在一个方向上约束了它），"
                     f"也**不要**报点估计。")

    if material_meta is not None:
        from battery_sim.datasets.material_metadata import render as render_meta

        lines.append("")
        lines.append("## 材料元数据")
        lines.append("")
        lines.append("```text")
        lines.append(render_meta(material_meta))
        lines.append("```")

    caution = party_role_caution(mode, dataset_role)
    caveats: List[str] = []
    if caution:
        caveats.append(caution)
    caveats.append(
        "带宽是 **model-to-model** 量：观测由同一个模型在同尺度下产生，"
        "没有实验噪声、也没有模型形式差异 ⇒ 这是**理想条件下的最好情况**。"
    )
    caveats.append(
        f"判据 {limit_dex:.3f} dex 与水平 {level_mV:g} mV 都是**声明**值，"
        f"不是数据的噪声水平（本条记录里没有噪声模型）。"
    )
    caveats.extend(extra_caveats)
    lines.append("")
    lines.append("## 边界（引用结论时必须一起引用）")
    lines.append("")
    for item in caveats:
        lines.append(f"- {item}")

    return "\n".join(line for line in lines if line is not None) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m identification.parameter_report",
        description="从产物生成参数可辨识性报告（material 模式禁止 synthetic truth）",
    )
    parser.add_argument("--windows", required=True,
                        help="G6.1c 逐窗口表 CSV")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--cell", default="")
    parser.add_argument("--protocol-prefix", default="",
                        help="只看协议 id 以此开头的窗口，例如 GITT-charge")
    parser.add_argument("--level-mV", type=float, default=1.0)
    parser.add_argument("--limit-dex", type=float, default=0.30)
    parser.add_argument("--scan-half-dex", type=float, default=DEFAULT_SCAN_HALF_DEX)
    parser.add_argument("--mode", default=MODE_MATERIAL,
                        choices=(MODE_BENCHMARK, MODE_MATERIAL))
    parser.add_argument("--techniques", default="GITT",
                        help="本数据集实际测了哪些电化学（逗号分隔）")
    parser.add_argument("--material-metadata", default="",
                        help="材料元数据 yaml（有就写进报告）")
    parser.add_argument("--dataset-role", default="",
                        help="留空则从 configs/datasets.yaml 自动读")
    parser.add_argument("--include-recovery", action="store_true",
                        help="带 synthetic truth 恢复列（仅 benchmark 模式允许）")
    parser.add_argument("--out", default="", help="输出 markdown 路径")
    args = parser.parse_args(argv)

    path = Path(args.windows)
    if not path.is_file():
        print(f"FAIL  找不到 {path}")
        return 1
    windows = pd.read_csv(path)

    try:
        probe, summary = best_window_probe(
            windows, parameter="Ds", protocol_prefix=args.protocol_prefix,
            level_mV=args.level_mV, limit_dex=args.limit_dex,
            scan_half_dex=args.scan_half_dex,
        )
    except ReportInputError as exc:
        print(f"FAIL  {exc}")
        return 1

    techniques = [t.strip() for t in args.techniques.split(",") if t.strip()]
    probes = [probe]
    probes.extend(unmeasured_probes(("k0", "Rct"),
                                    available_techniques=techniques))

    role = args.dataset_role or None
    if role is None:
        try:
            from governance.dataset_roles import resolve_role
            role = resolve_role(args.dataset)
        except Exception:
            role = None

    meta = None
    if args.material_metadata:
        from battery_sim.datasets.material_metadata import load_metadata
        meta = load_metadata(args.material_metadata)

    try:
        report = render_report(
            probes, dataset=args.dataset, cell=args.cell, analysis_mode=args.mode,
            level_mV=args.level_mV, limit_dex=args.limit_dex,
            scan_half_dex=args.scan_half_dex, dataset_role=role,
            material_meta=meta, windows_path=str(args.windows),
            summary=summary, include_recovery=args.include_recovery,
        )
    except Exception as exc:
        print(f"FAIL  {type(exc).__name__}: {exc}")
        return 1

    if args.out:
        out = Path(args.out)
        if not out.is_absolute():
            out = ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8", newline="")
        print(f"wrote {out}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "DEFAULT_SCAN_HALF_DEX",
    "PARAMETER_EVIDENCE",
    "ParameterProbe",
    "REQUIRED_WINDOW_COLUMNS",
    "ReportInputError",
    "band_from_window_row",
    "best_window_probe",
    "main",
    "render_report",
    "unmeasured_probes",
]

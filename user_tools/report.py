# ============================================================
# 报告生成（S4）
#   validation_report.html
#   voltage_capacity_preview.png
# ============================================================

from __future__ import annotations

import html
from pathlib import Path
from typing import List, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402


def make_preview_png(df, out_path: Path) -> None:
    """电压-时间 与 电流-时间（或容量）双面板预览图。"""
    t = df["time_s"].to_numpy(dtype=float)
    V = df["voltage_V"].to_numpy(dtype=float)
    I = df["current_A"].to_numpy(dtype=float)

    has_cap = (
        "capacity_Ah" in df.columns
        and np.isfinite(pd_cap := df["capacity_Ah"].to_numpy(dtype=float)).sum() > 10
    )

    fig, axes = plt.subplots(2, 1, figsize=(8.0, 6.0), sharex=True)
    ax1, ax2 = axes

    ax1.plot(t / 3600.0, V, color="#1f4e79", lw=1.2)
    ax1.set_ylabel("Voltage [V]")
    ax1.set_title("Preview: voltage / current vs time")
    ax1.grid(alpha=0.3)

    if has_cap:
        ax2.plot(t / 3600.0, pd_cap * 1000.0, color="#8c5a00", lw=1.2)
        ax2.set_ylabel("Capacity [mAh]")
    else:
        ax2.plot(t / 3600.0, I * 1000.0, color="#2e7d32", lw=1.0)
        ax2.set_ylabel("Current [mA]  (discharge +)")

    ax2.set_xlabel("Time [h]")
    ax2.grid(alpha=0.3)

    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)


def make_validation_html(
    out_path: Path,
    exp: dict,
    issues: List[dict],
    summary: dict,
    gate: dict,
    conv_log: dict,
    preview_png_name: str,
    canonical_rows: int,
    protocol_interpretation: Optional[dict] = None,
) -> None:
    sev_color = {"FAIL": "#c62828", "WARN": "#ef6c00", "PASS": "#2e7d32"}

    def row(i):
        c = sev_color.get(i["severity"], "#333")
        return (
            f"<tr><td style='color:{c};font-weight:700'>{i['severity']}</td>"
            f"<td>{html.escape(str(i['code']))}</td>"
            f"<td>{html.escape(str(i['message']))}</td>"
            f"<td style='font-family:monospace;font-size:12px'>"
            f"{html.escape(str(i['evidence']))}</td></tr>"
        )

    status = summary["import_status"]
    status_color = "#c62828" if status == "FAIL" else "#2e7d32"

    sim_txt = "可以运行" if summary["simulation_allowed"] else "不运行（存在严重错误）"
    sim_color = "#2e7d32" if summary["simulation_allowed"] else "#c62828"

    if gate["available"]:
        prov = gate.get("provenance") or {}
        prov_txt = (
            f"provenance={prov.get('provenance')}"
            f" · electrode_design={prov.get('electrode_design')}"
            f" · fitted_to_user_dataset={prov.get('fitted_to_user_dataset')}"
            f" · executable_reproduction={prov.get('executable_reproduction')}"
            if prov
            else ""
        )
        param_block = (
            f"<b>参数集</b>：{html.escape(str(gate['parameter_set']))}<br>"
            f"<b>匹配等级</b>：{html.escape(str(gate['level']))} "
            f"(grade {html.escape(str(gate['grade']))})<br>"
            f"<b>结构化溯源</b>：{html.escape(prov_txt)}<br>"
            f"<b>是否用你的数据标定过</b>："
            f"{'是' if gate['fitted_to_dataset'] else '否（zero-fit）'}<br>"
            f"<b>说明</b>：{html.escape(str(gate['reason']))}"
        )
        sim_avail = "<span style='color:#2e7d32;font-weight:700'>SIMULATION = AVAILABLE</span>"
    else:
        blockers = "<br>".join(
            "• " + html.escape(str(b)) for b in gate.get("blockers", [])
        )
        param_block = (
            f"<b>没有可用的参数集</b>。<br>{html.escape(str(gate['reason']))}"
            + (f"<br>{blockers}" if blockers else "")
        )
        sim_avail = (
            "<span style='color:#c62828;font-weight:700'>"
            "SIMULATION = NOT AVAILABLE</span>"
        )

    def kv_table(d):
        return "".join(
            f"<tr><td style='font-family:monospace'>{html.escape(str(k))}</td>"
            f"<td>{html.escape(str(v if v not in (None, '') else '（未填）'))}</td></tr>"
            for k, v in d.items()
        )

    conv_rows = "".join(
        f"<tr><td>{html.escape(str(k))}</td>"
        f"<td>{html.escape(str(v.get('source_column', '')))}</td>"
        f"<td>{html.escape(str(v.get('source_unit', '')))}</td>"
        f"<td>{html.escape(str(conv_log.get('current_sign_transform', '')) if k == 'current' else '')}</td></tr>"
        for k, v in conv_log.get("columns", {}).items()
    )

    doc = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>数据导入检查报告</title>
<style>
 body{{font-family:"Microsoft YaHei",-apple-system,Segoe UI,sans-serif;
       margin:28px;color:#222;background:#fff;line-height:1.55}}
 h1{{font-size:22px;margin:0 0 4px}}
 h2{{font-size:17px;margin:26px 0 8px;border-left:4px solid #1f4e79;padding-left:8px}}
 table{{border-collapse:collapse;width:100%;font-size:13px;margin-top:6px}}
 th,td{{border:1px solid #d8d8d8;padding:6px 8px;text-align:left;vertical-align:top}}
 th{{background:#f2f5f8}}
 .box{{border:1px solid #d8d8d8;border-radius:6px;padding:12px 14px;background:#fafbfc}}
 .big{{font-size:16px}}
 img{{max-width:100%;border:1px solid #d8d8d8;border-radius:4px;margin-top:8px}}
 .note{{background:#fff8e1;border-left:4px solid #f9a825;padding:8px 12px;margin-top:10px}}
</style></head><body>

<h1>数据导入检查报告</h1>
<div style="color:#666">Self-Service Data Onboarding Layer · zero-fit baseline 前置检查</div>

<h2>1. 结论</h2>
<div class="box big">
  数据导入：<span style="color:{status_color};font-weight:700">{status}</span><br>
  仿真：{sim_avail} —— {sim_txt}<br>
  检查项：{summary['n_checks']} 条（严重 {summary['n_fail']} 条，警告 {summary['n_warn']} 条）<br>
  有效数据行：{canonical_rows}
</div>
<div class="note">
  本层只做“数据检查 + zero-fit baseline”。<b>不做任何拟合、不做参数辨识</b>。
  即使仿真可用，结果也不代表模型已被验证。
</div>

{f"<h2>2. 协议 / 倍率解释</h2><div class='box'>" 
 if protocol_interpretation else ""}
{f"原始数据标签 source_protocol_label = <b>{html.escape(str(protocol_interpretation.get('source_protocol_label')))}</b>"
 f"（你在 experiment.protocol 填的名字，如 cycler 档位名）<br>"
 f"平台换算出的实际倍率 effective_c_rate = <b>"
 f"{html.escape(format(protocol_interpretation['effective_c_rate'], '.3f')) if protocol_interpretation.get('effective_c_rate') is not None else '未填 nominal_capacity 无法换算'} C</b>"
 f"（= max|I| / nominal_capacity）<br>"
 f"<span style='color:#777'>{html.escape(str(protocol_interpretation.get('note','')))}</span>"
 f"</div>" if protocol_interpretation else ""}

<h2>{"3" if protocol_interpretation else "2"}. 参数集匹配（S6）</h2>
<div class="box">{param_block}</div>

<h2>{"4" if protocol_interpretation else "3"}. 你填写的实验信息</h2>
<table><tr><th>字段</th><th>取值</th></tr>{kv_table(exp)}</table>

<h2>{"5" if protocol_interpretation else "4"}. 列映射与单位换算</h2>
<table>
<tr><th>canonical 字段</th><th>你的原始列名</th><th>你填的单位</th><th>符号处理</th></tr>
{conv_rows}
</table>
<div style="margin-top:6px;color:#555">
  电流已统一为平台约定：<b>放电 = 正</b>。
</div>

<h2>{"6" if protocol_interpretation else "5"}. 检查明细</h2>
<table>
<tr><th style="width:70px">级别</th><th style="width:190px">检查项</th><th>说明</th><th style="width:260px">证据</th></tr>
{''.join(row(i) for i in issues)}
</table>

<h2>{"7" if protocol_interpretation else "6"}. 数据预览</h2>
<img src="{html.escape(preview_png_name)}" alt="preview">

</body></html>"""

    out_path.write_text(doc, encoding="utf-8")

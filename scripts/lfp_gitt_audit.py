#!/usr/bin/env python3
# ============================================================
# LFP/graphite (Pozzato 2022, CC + GITT + EV profiles) 数据审计
#
#   0 pybamm。只读数据 -> 审计表 + canonical 预览 + 图。
#   平台 battery_sim/ 零改动。
#
# README 事实（审计基准）：
#   - const_current_data: charge I<0 / discharge I>0, [A]; V [V]; soc [-]; t [s]
#   - real_world_data:    I>0 discharge, I<0 charge; soc_start 标量
#   - GITT_data:          同 CC 约定; C/6, C/3, C/2, 1C @ 25C
#   - C-rate 标签: 0_08C=C/12, 0_17C=C/6, 0_33C=C/3, 0_5C=C/2
# 输出: outputs/analysis/lfp_gitt_audit/
# ============================================================

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.io as sio
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/LIB/LFP_Graphite/LFP4graphite_CC_GITT_EV"
_subs = [p for p in RAW.iterdir() if p.is_dir()]
assert len(_subs) == 1, f"expected single top-level dir, got {[p.name for p in _subs]}"
BASE = _subs[0]
OUT = ROOT / "outputs/analysis/lfp_gitt_audit"
OUT_CANON = OUT / "canonical_preview"
OUT.mkdir(parents=True, exist_ok=True)
OUT_CANON.mkdir(exist_ok=True)

RATE_LABEL = {"0_08": "C/12", "0_17": "C/6", "0_33": "C/3", "0_5": "C/2", "1C": "1C"}


def parse_group(mat_path: Path):
    """返回 legs: [{leg, I, V, soc, soc_start, t}]。

    实测结构（与 README 措辞略有出入，以实际为准）：
      GITT_data/*.mat            : 顶层 charge/discharge 子结构，各含
                                   current/voltage/soc/time（soc 为向量）
      const_current_data/*.mat   : 顶层 charge/discharge 子结构，各含
                                   current/voltage/soc_start/time（标量！）
      real_world_data/*.mat      : 顶层平铺 current/voltage/time/soc_start
    """
    m = sio.loadmat(mat_path, struct_as_record=False, squeeze_me=True)
    legs = []
    if "charge" in m and "discharge" in m:
        for sub in ("charge", "discharge"):
            g = m[sub]
            soc_v = getattr(g, "soc", None)
            soc = (
                np.atleast_1d(np.asarray(soc_v, float))
                if soc_v is not None
                else np.array([])
            )
            ss = getattr(g, "soc_start", None)
            soc_start = (
                float(np.asarray(ss).reshape(-1)[0]) if ss is not None else float("nan")
            )
            legs.append(
                dict(
                    leg=sub,
                    I=np.atleast_1d(np.asarray(g.current, float)),
                    V=np.atleast_1d(np.asarray(g.voltage, float)),
                    soc=soc,
                    soc_start=soc_start,
                    t=np.atleast_1d(np.asarray(g.time, float)),
                )
            )
    elif all(k in m for k in ("current", "voltage", "time")):
        ss = np.asarray(m["soc_start"]).reshape(-1)[0]
        legs.append(
            dict(
                leg="profile",
                I=np.atleast_1d(np.asarray(m["current"], float)),
                V=np.atleast_1d(np.asarray(m["voltage"], float)),
                soc=np.array([]),
                soc_start=float(ss),
                t=np.atleast_1d(np.asarray(m["time"], float)),
            )
        )
    else:
        raise ValueError(f"unrecognised layout in {mat_path.name}: {list(m.keys())}")
    return legs


MAX_PREVIEW_POINTS = 200_000


def audit_leg(group: str, fname: str, rate: str, leg: dict) -> dict:
    I, V, t = leg["I"], leg["V"], leg["t"]
    dt = np.diff(t)
    dur = float(t[-1] - t[0])
    q_dis_Ah = float(np.trapezoid(np.clip(I, 0, None), t) / 3600.0)
    q_chg_Ah = float(np.trapezoid(np.clip(-I, 0, None), t) / 3600.0)
    soc = leg["soc"]
    return dict(
        group=group,
        file=fname,
        rate_label=rate,
        leg=leg["leg"],
        n_points=int(t.size),
        duration_h=dur / 3600.0,
        dt_median_s=float(np.median(dt)),
        dt_min_s=float(dt.min()),
        dt_max_s=float(dt.max()),
        n_time_backsteps=int((dt <= 0).sum()),
        I_max_A=float(np.nanmax(I)),
        I_min_A=float(np.nanmin(I)),
        V_min=float(np.nanmin(V)),
        V_max=float(np.nanmax(V)),
        soc_min=float(np.nanmin(soc)) if soc.size else float("nan"),
        soc_max=float(np.nanmax(soc)) if soc.size else float("nan"),
        soc_start=leg["soc_start"],
        Q_discharge_Ah=q_dis_Ah,
        Q_charge_Ah=q_chg_Ah,
    )


def canonicalize(group, fname, rate, leg) -> pd.DataFrame:
    t, I, V = leg["t"], leg["I"], leg["V"]
    n = t.size
    stride = max(int(np.ceil(n / MAX_PREVIEW_POINTS)), 1)
    idx = np.arange(0, n, stride)
    df = pd.DataFrame(
        {
            "time_s": t[idx] - t[0],
            "current_A": I[idx],   # 平台约定：discharge = +（README 原生一致，无需翻转）
            "voltage_V": V[idx],
            "soc": leg["soc"][idx] if leg["soc"].size == n else np.nan,
            "capacity_Ah": np.concatenate(
                [[0.0], np.cumsum(np.abs(I[:-1]) * np.diff(t)) / 3600.0]
            )[idx],
        }
    )
    df.attrs.update(
        source_file=fname, rate_label=rate, leg=leg["leg"], group=group,
        soc_start=leg["soc_start"], downsample_stride=stride,
    )
    return df


# ------------------------------------------------------------------
rows, canon_paths = [], []
mat_files = sorted(BASE.rglob("*.mat"))
assert len(mat_files) == 13, len(mat_files)
for mp in mat_files:
    rel = mp.relative_to(BASE)
    group = rel.parts[0]
    fname = mp.name
    rate = next((v for k, v in RATE_LABEL.items() if k in fname), "")
    key, legs = None, parse_group(mp)
    for leg in legs:
        rows.append(audit_leg(group, fname, rate, leg))
        df = canonicalize(group, fname, rate, leg)
        slug = f"{group.split('_')[0]}_{fname.replace('.mat','')}_{leg['leg']}".replace("/", "-")
        p = OUT_CANON / f"{slug}.csv"
        df.to_csv(p, index=False)
        canon_paths.append(p)

audit = pd.DataFrame(rows)
audit.to_csv(OUT / "audit_per_leg.csv", index=False)

# ------------------------------------------------------------------
# 隐含标称容量一致性：|I| = Q_nom * rate
# ------------------------------------------------------------------
imp = []
for _, r in audit.iterrows():
    if not r["rate_label"]:
        continue
    frac = eval(r["rate_label"].replace("C", "").replace("/", "/")) if False else None
    # rate_label -> 数值（如 C/6 -> 1/6）
    lbl = r["rate_label"]
    num = 1.0 / float(lbl.split("/")[1]) if "/" in lbl else float(lbl[:-1])
    for side, imax in (("discharge", r["I_max_A"]), ("charge", -r["I_min_A"])):
        # 噪声/泄漏电流（相对本 leg 主电流 <2%）不算 CC 水平，跳过
        i_scale = max(abs(r["I_max_A"]), abs(r["I_min_A"]))
        if imax > 1e-4 and imax >= 0.02 * i_scale:
            imp.append(
                dict(file=r["file"], rate=lbl, leg=r["leg"], side=side,
                     Q_nom_implied_Ah=imax / num)
            )
imp_df = pd.DataFrame(imp)
imp_df.to_csv(OUT / "implied_nominal_capacity.csv", index=False)

# ------------------------------------------------------------------
# GITT 脉冲结构审计
# ------------------------------------------------------------------
gitt_rows = []
for mp in sorted((BASE / "GITT_data").glob("*.mat")):
    rate = next((v for k, v in RATE_LABEL.items() if k in mp.name), "")
    legs = parse_group(mp)
    for leg in legs:
        I, t = leg["I"], leg["t"]
        # 脉冲 = 相邻符号段
        sign = np.sign(np.round(I, 6))
        seg_id = np.r_[0, np.cumsum(np.diff(sign) != 0)]
        n_seg = int(seg_id[-1] + 1)
        pulse = 0
        rests = []
        for s in range(n_seg):
            m = seg_id == s
            if sign[m][0] == 0:
                rests.append(float(t[m][-1] - t[m][0]))
            elif sign[m][0] > 0:
                pulse += 1
        gitt_rows.append(
            dict(file=mp.name, rate=rate, leg=leg["leg"], n_sign_segments=n_seg,
                 n_discharge_pulses=pulse,
                 n_rest_segments=len(rests),
                 rest_total_h=sum(rests) / 3600.0,
                 rest_median_s=float(np.median(rests)) if rests else float("nan"))
        )
gitt_df = pd.DataFrame(gitt_rows)
gitt_df.to_csv(OUT / "gitt_pulse_audit.csv", index=False)

# ------------------------------------------------------------------
# 预览图 1：CC + GITT 全 leg V vs capacity
# ------------------------------------------------------------------
fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), sharey=True)
for _, r in audit[audit.group != "real_world_data"].iterrows():
    slug = f"{r['group'].split('_')[0]}_{r['file'].replace('.mat','')}_{r['leg']}"
    p = OUT_CANON / f"{slug}.csv"
    df = pd.read_csv(p)
    ax = axes[0] if r["group"] == "const_current_data" else axes[1]
    lbl = f"{r['rate_label'] or ''} {r['leg']}".strip()
    ax.plot(df["capacity_Ah"] * 1000.0, df["voltage_V"], lw=1.1, label=lbl)
axes[0].set_title("const_current_data")
axes[1].set_title("GITT_data")
for ax in axes:
    ax.set_xlabel("capacity throughput [mAh]")
    ax.grid(alpha=0.3)
axes[0].set_ylabel("V [V]")
axes[0].legend(fontsize=7, ncol=2)
axes[1].legend(fontsize=7, ncol=2)
fig.suptitle("LFP/graphite CC & GITT legs (discharge=+)")
fig.tight_layout()
fig.savefig(OUT / "fig_cc_gitt_preview.png", dpi=130)
plt.close(fig)

# ------------------------------------------------------------------
# 预览图 2：7 条实况 profile
# ------------------------------------------------------------------
fig, axes = plt.subplots(2, 1, figsize=(11, 6), sharex=True)
for mp in sorted((BASE / "real_world_data").glob("*.mat")):
    legs = parse_group(mp)
    leg = legs[0]
    t = leg["t"] - leg["t"][0]
    axes[0].plot(t / 3600.0, leg["I"], lw=0.7, label=mp.stem)
    axes[1].plot(t / 3600.0, leg["V"], lw=0.7)
axes[0].set_ylabel("I [A]  (discharge +)")
axes[1].set_ylabel("V [V]")
axes[1].set_xlabel("t [h]")
axes[0].legend(fontsize=7, ncol=4)
for ax in axes:
    ax.grid(alpha=0.3)
fig.suptitle("EV real-driving profiles")
fig.tight_layout()
fig.savefig(OUT / "fig_profiles_preview.png", dpi=130)
plt.close(fig)

# ------------------------------------------------------------------
# summary json
# ------------------------------------------------------------------
summary = dict(
    dataset="LFP4graphite_CC_GITT_EV (Pozzato 2022, Zenodo)",
    readme_facts=dict(
        creator="Gabriele Pozzato (README last modified 2022-08-16)",
        sign_convention="discharge = +current, charge = -current (native, matches platform)",
        units="current [A], voltage [V], soc [-], time [s]",
        cc_rates=dict.fromkeys(["C/12", "C/6"]),
        gitt_rates=["C/6", "C/3", "C/2", "1C"] + [" @ 25C"],
        real_world="7 EV profiles, soc_start scalar",
    ),
    n_mat_files=len(mat_files),
    n_legs=int(len(audit)),
    n_canonical_previews=len(canon_paths),
    time_monotonic_all=bool((audit["n_time_backsteps"] == 0).all()),
    V_window_all=f"[{audit.V_min.min():.3f}, {audit.V_max.max():.3f}] V",
    Q_nom_implied_spread_Ah=(
        f"[{imp_df.Q_nom_implied_Ah.min():.3f}, {imp_df.Q_nom_implied_Ah.max():.3f}]"
    ),
    audit_csv="audit_per_leg.csv",
)
(OUT / "audit_summary.json").write_text(
    json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
)

print(audit.to_string(index=False))
print()
print("implied Q_nom spread:", summary["Q_nom_implied_spread_Ah"])
print("GITT pulse audit:")
print(gitt_df.to_string(index=False))
print("\noutputs ->", OUT.relative_to(ROOT))

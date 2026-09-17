# ============================================================
# Validation gate（S4）
#
# 导入后必须通过的检查。严重错误 = FAIL，不允许继续 simulation。
# 每一项都输出可读的中文说明 + 证据数字。
# ============================================================

from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from battery_sim.datasets.chemistry_windows import (
    check_declared_window as _check_declared_window,
    check_measured_window as _check_measured_window,
    resolve_system as _resolve_window_system,
)
from user_tools.spec import is_pulse_protocol, protocol_type_of


# ------------------------------------------------------------------
# 协议结构解析（脉冲型协议判据要用的最小工具）
#
# 只做一件事：把 |I| 的过零结构切成"活动段/静置段"。
# 不猜协议、不猜方向：段就是段，方向由电流符号自己带着。
# ------------------------------------------------------------------
def _runs(mask: np.ndarray) -> List[Tuple[int, int, bool]]:
    """把布尔序列切成 (start, stop, value) 的连续段（stop 为开区间）。"""
    out: List[Tuple[int, int, bool]] = []
    if mask.size == 0:
        return out
    start = 0
    cur = bool(mask[0])
    for k in range(1, mask.size):
        v = bool(mask[k])
        if v != cur:
            out.append((start, k, cur))
            start, cur = k, v
    out.append((start, mask.size, cur))
    return out


def _pulse_segments(
    t: np.ndarray, I: np.ndarray, *, active_frac: float = 0.05
) -> Tuple[List[Tuple[float, float]], List[Tuple[float, float]]]:
    """返回 (脉冲段, 静置段)，元素为 ``(t_start, t_stop)``。

    判"活动"只用阈值 ``active_frac * max|I|``：GITT 的脉冲幅度通常远大于
    噪声，这个阈值足够稳；把阈值写进 evidence，避免"看起来像但其实不是"。
    最后一个采样点按平台网格补一个 ``median(dt)``，否则每段会短一个采样间隔
    （对 600 s 脉冲是 0.17 %，对 1 s 采样的小脉冲就是 100 %）。
    """
    if t.size < 3:
        return [], []
    amp = float(np.nanmax(np.abs(I)))
    if not np.isfinite(amp) or amp <= 0:
        return [], []
    mask = np.abs(I) > active_frac * amp
    dt_med = float(np.median(np.diff(t))) if t.size > 1 else 0.0
    pulses: List[Tuple[float, float]] = []
    rests: List[Tuple[float, float]] = []
    for start, stop, value in _runs(mask):
        lo = float(t[start])
        hi = float(t[stop - 1]) + dt_med
        (pulses if value else rests).append((lo, hi))
    return pulses, rests


def _durations(segments: List[Tuple[float, float]]) -> np.ndarray:
    return np.array([b - a for a, b in segments], dtype=float)


def _duration_summary(durations: np.ndarray) -> dict:
    """中位/最小/最大/离散度。离散度用 ``std/median``（无量纲）。"""
    if durations.size == 0:
        return {"n": 0, "median_s": float("nan"), "min_s": float("nan"),
                "max_s": float("nan"), "spread": float("nan")}
    med = float(np.median(durations))
    return {
        "n": int(durations.size),
        "median_s": med,
        "min_s": float(durations.min()),
        "max_s": float(durations.max()),
        "spread": float(durations.std(ddof=0) / med) if med > 0 else float("inf"),
    }


def _relative_gap(measured: float, declared: float) -> Optional[float]:
    """相对偏差；任一不是有限正数则返回 None（表示"没法比"）。"""
    if not (np.isfinite(measured) and np.isfinite(declared)):
        return None
    if measured <= 0 or declared <= 0:
        return None
    return abs(measured - declared) / declared

FAIL = "FAIL"
WARN = "WARN"
PASS = "PASS"


def _add(issues: List[dict], code: str, severity: str, message: str,
         evidence: str = "") -> None:
    issues.append(
        {
            "code": code,
            "severity": severity,
            "message": message,
            "evidence": evidence,
        }
    )


def _discharge_mask(t: np.ndarray, I: np.ndarray, V: np.ndarray) -> np.ndarray:
    """
    判定"放电段"的证据：电压随时间下降 且 电流非零。
    只用于校验用户声明的符号，不用于猜测符号。
    """
    dV = np.diff(V, prepend=V[0])
    declining = dV <= 0
    active = np.abs(I) > 0.05 * float(np.nanmax(np.abs(I)) + 1e-30)
    return declining & active


def validate(df: pd.DataFrame, exp: dict, log: dict) -> List[dict]:
    """返回 issues 列表（每行一条）。FAIL 存在 -> simulation 阻断。"""
    issues: List[dict] = []

    t = df["time_s"].to_numpy(dtype=float)
    I = df["current_A"].to_numpy(dtype=float)
    V = df["voltage_V"].to_numpy(dtype=float)
    n = len(df)

    # ---- 1. missing required columns -------------------------------
    for f, col in (("time", "time_s"), ("current", "current_A"),
                   ("voltage", "voltage_V")):
        if col not in df.columns or bool(df[col].isna().all()):
            _add(issues, "MISSING_REQUIRED", FAIL,
                 f"缺少必填列：{f}（canonical 列名 {col}）",
                 f"column_mapping 中没有填写 {f}")

    # ---- 2. NaN ----------------------------------------------------
    for f, col in (("time", "time_s"), ("current", "current_A"),
                   ("voltage", "voltage_V")):
        if col not in df.columns:
            continue
        n_nan = int(pd.isna(df[col]).sum())
        if n_nan:
            _add(issues, "NAN_IN_REQUIRED", FAIL,
                 f"{f} 列有 {n_nan} 个空值/非数字，无法用于仿真",
                 f"{col}: {n_nan}/{n}")
        else:
            _add(issues, "NAN_IN_REQUIRED", PASS, f"{f} 列没有空值", f"{n}/{n}")

    valid = np.isfinite(t) & np.isfinite(I) & np.isfinite(V)
    n_valid = int(valid.sum())
    if n_valid == 0:
        _add(issues, "NO_VALID_ROWS", FAIL,
             "没有任何一行同时具备有效的时间/电流/电压", f"n={n}")
        return issues
    if n_valid < n:
        _add(issues, "PARTIAL_VALID_ROWS", WARN,
             f"有 {n - n_valid} 行数据不完整，仿真时会被忽略",
             f"valid {n_valid}/{n}")

    tv, Iv, Vv = t[valid], I[valid], V[valid]

    # ---- 3. duplicate timestamps ----------------------------------
    n_dup = int(log.get("n_duplicate_timestamps_dropped", 0))
    if n_dup:
        _add(issues, "DUPLICATE_TIMESTAMP", WARN,
             f"有 {n_dup} 个重复时间戳，已自动保留每个时间的第一条"
             "（与平台现有数据处理方式一致）",
             f"dropped {n_dup}")
    else:
        _add(issues, "DUPLICATE_TIMESTAMP", PASS, "没有重复时间戳", "0")

    # ---- 4. non-monotonic time ------------------------------------
    dt = np.diff(tv)
    n_back = int((dt < 0).sum())
    if n_back:
        _add(issues, "NON_MONOTONIC_TIME", FAIL,
             f"时间列有 {n_back} 处回退（不是单调递增），无法用于仿真",
             f"back steps {n_back}")
    else:
        _add(issues, "NON_MONOTONIC_TIME", PASS, "时间单调递增", "0 back steps")

    # ---- 5. current sign vs 用户声明 -------------------------------
    #
    # 注意：进到这里时电流已经按用户声明翻转成 canonical（放电 = 正）。
    # 因此正确的检验是"放电段电流是否为正"：
    #   * 为负  -> 用户声明与数据矛盾（翻转方向错了），FAIL
    #   * 为正  -> 声明自洽
    # 这里不猜符号，只在声明与数据矛盾时报错。
    declared = str(exp.get("current_sign", "")).strip()
    m = _discharge_mask(tv, Iv, Vv)
    if m.sum() >= 5:
        med = float(np.median(Iv[m]))
        if med < 0:
            _add(issues, "CURRENT_SIGN_CONFLICT", FAIL,
                 f"你声明“原始电流：{'放电为负' if declared == 'discharge_negative' else '放电为正'}”，"
                 "但按该声明转换后，电压下降段的电流仍然是负的，与平台约定"
                 "（放电 = 正）矛盾。请检查 current_sign 是否填反了。"
                 "这里不会自动帮你猜符号。",
                 f"median I during V-decline = {med:.6g} A (expect > 0)")
        else:
            _add(issues, "CURRENT_SIGN_CONFLICT", PASS,
                 f"电流符号与声明自洽（{declared}），"
                 "转换后放电为正，符合平台约定",
                 f"median I during V-decline = {med:.6g} A")
    else:
        _add(issues, "CURRENT_SIGN_CONFLICT", WARN,
             "数据里找不到明显的放电段，无法用数据核对你声明的电流符号",
             f"discharge-like points {int(m.sum())}")

    # ---- 6. voltage range -----------------------------------------
    lo, hi = exp.get("voltage_lower"), exp.get("voltage_upper")
    if lo is not None and hi is not None:
        outside = int(((Vv < float(lo)) | (Vv > float(hi))).sum())
        frac = outside / max(len(Vv), 1)
        if frac > 0.05:
            _add(issues, "VOLTAGE_RANGE", FAIL,
                 f"有 {outside} 个点（{frac:.1%}）在你填写的电压窗口 "
                 f"[{lo:g}, {hi:g}] V 之外，声明窗口与数据严重不符",
                 f"measured V range [{Vv.min():.4g}, {Vv.max():.4g}] V")
        elif outside:
            _add(issues, "VOLTAGE_RANGE", WARN,
                 f"有 {outside} 个点（{frac:.1%}）在声明窗口之外",
                 f"measured V range [{Vv.min():.4g}, {Vv.max():.4g}] V")
        else:
            _add(issues, "VOLTAGE_RANGE", PASS,
                 "全部电压点都在声明窗口内",
                 f"measured V range [{Vv.min():.4g}, {Vv.max():.4g}] V")
    else:
        _add(issues, "VOLTAGE_RANGE", WARN,
             "未填写 voltage_lower / voltage_upper，跳过电压窗口检查", "")

    # ---- 7. current range -----------------------------------------
    imax = float(np.nanmax(np.abs(Iv)))
    if imax <= 0:
        _add(issues, "CURRENT_RANGE", FAIL, "电流全为 0，无法仿真", "max|I|=0")
    else:
        msg = f"max|I| = {imax:.6g} A"
        nom = exp.get("nominal_capacity")
        if nom:
            try:
                cr = imax / float(nom)
                msg += f"（约 {cr:.2f} C，按标称容量 {float(nom):g} Ah）"
                if cr > 20:
                    _add(issues, "CURRENT_RANGE", FAIL,
                         f"换算倍率约 {cr:.1f} C，明显不合理："
                         "请检查电流单位或标称容量是否填错", msg)
                    return issues
            except (TypeError, ValueError):
                pass
        _add(issues, "CURRENT_RANGE", PASS, "电流幅值在合理范围", msg)

    # ---- 8. capacity consistency ----------------------------------
    cap = df["capacity_Ah"].to_numpy(dtype=float) if "capacity_Ah" in df else None
    if cap is not None and np.isfinite(cap).sum() > 10:
        cv = cap[valid]
        if np.isfinite(cv).all():
            dQ = float(cv[-1] - cv[0])
            dtv = np.diff(tv, prepend=tv[0])
            Qint = float(np.sum(Iv * np.r_[dtv[1:], dtv[-1]]) / 3600.0)
            if abs(dQ) > 1e-12:
                rel = abs(abs(Qint) - abs(dQ)) / abs(dQ)
                if rel > 0.20:
                    _add(issues, "CAPACITY_CONSISTENCY", WARN,
                         f"容量列的增量与电流积分相差 {rel:.0%}，"
                         "容量列与电流列可能不同源或单位填错",
                         f"dQ_col={dQ:.6g} Ah, integral={Qint:.6g} Ah")
                else:
                    _add(issues, "CAPACITY_CONSISTENCY", PASS,
                         "容量列与电流积分一致",
                         f"dQ_col={dQ:.6g} Ah, integral={Qint:.6g} Ah, "
                         f"rel diff {rel:.1%}")
            else:
                _add(issues, "CAPACITY_CONSISTENCY", WARN,
                     "容量列首尾相同（增量为 0），可能不是累计容量列",
                     f"dQ={dQ:.6g} Ah")
        else:
            _add(issues, "CAPACITY_CONSISTENCY", WARN,
                 "容量列存在空值，已跳过一致性检查", "")
    else:
        _add(issues, "CAPACITY_CONSISTENCY", WARN,
             "未映射容量列（可选），跳过容量一致性检查", "")

    # ---- 9. cycle / step consistency ------------------------------
    for name, col in (("cycle", "cycle"), ("step", "step")):
        if col not in df.columns:
            continue
        s = df[col]
        if bool(s.isna().all()):
            continue
        if bool(s.isna().any()):
            _add(issues, "CYCLE_STEP_CONSISTENCY", FAIL,
                 f"{name} 列有空值", f"{int(s.isna().sum())} NaN")
        else:
            arr = s.to_numpy(dtype=float)
            if np.any(np.diff(arr) < 0):
                _add(issues, "CYCLE_STEP_CONSISTENCY", WARN,
                     f"{name} 列不是单调递增（可能正常，例如循环复位）",
                     f"{int((np.diff(arr) < 0).sum())} decreases")
            else:
                _add(issues, "CYCLE_STEP_CONSISTENCY", PASS,
                     f"{name} 列单调且无空值", f"n={len(arr)}")

    # ---- 10. sampling interval ------------------------------------
    #
    # 分级：普通 GCD 下采样间断只影响观感（插值能补），报 WARN；
    # 脉冲型协议（GITT/PITT）下它会直接改掉脉冲时长与弛豫完整度，
    # 而 D_s 是由脉冲时长与 ΔV 算出来的 —— 那里必须是 FAIL。
    # 依据见下面第 12 节的脉冲结构核对。
    proto = protocol_type_of(exp)
    pulse_proto = is_pulse_protocol(proto)
    dts = np.diff(tv)
    dts = dts[dts > 0]
    med = float(np.median(dts)) if dts.size else 0.0
    if dts.size:
        mx = float(dts.max())
        _add(issues, "SAMPLING_INTERVAL", PASS,
             "采样间隔统计已记录",
             f"median dt={med:.4g} s, max dt={mx:.4g} s, "
             f"protocol_type={proto or '未声明'}, "
             f"duration={tv[-1] - tv[0]:.4g} s")
        if mx > 20 * med and med > 0:
            ratio = mx / med
            if pulse_proto:
                _add(issues, "SAMPLING_INTERVAL_GAP", FAIL,
                     f"存在明显采样间断（最大间隔是中位数间隔的 {ratio:.0f} 倍）。"
                     f"本份数据的 protocol_type='{proto}'：脉冲时长与弛豫完整度"
                     f"会被这个断点改掉，而 D_s 直接由它们算出 —— "
                     f"请回到仪器导出文件把断点补上，或明确声明这一段被截断",
                     f"median {med:.4g} s vs max {mx:.4g} s")
            else:
                _add(issues, "SAMPLING_INTERVAL_GAP", WARN,
                     f"存在明显采样间断（最大间隔是中位数间隔的 {ratio:.0f} 倍）",
                     f"median {med:.4g} s vs max {mx:.4g} s")

    # ---- 11. 体系锚定的电压窗口（chemistry-anchored）----------------
    #
    # 第 6 项只核"数据 vs 你自己填的窗口"：填 [0.005, 15] V 也会 PASS。
    # 这里核的是"声明与实测 vs **该体系的**参考窗口"，规则表在
    # battery_sim/datasets/chemistry_windows.py（闭集 + 每条带依据）。
    # 缺声明时不猜：报 WARN 说明检查被跳过（跳过 ≠ 通过）。
    window, why = _resolve_window_system(
        chemistry=exp.get("chemistry", ""),
        cell_configuration=exp.get("cell_configuration", ""),
        working_electrode=exp.get("working_electrode", ""),
        counter_electrode=exp.get("counter_electrode", ""),
        working_electrode_material=exp.get("working_electrode_material", ""),
        physical_working_electrode=exp.get("physical_working_electrode", ""),
    )
    if window is None:
        _add(issues, "VOLTAGE_WINDOW_SYSTEM", WARN,
             f"没有与该体系匹配的参考窗口，这项检查被跳过：{why}。"
             f"跳过不等于通过 —— 请补声明，或确认该体系确实不在规则表内",
             why)
    else:
        lo_d, hi_d = exp.get("voltage_lower"), exp.get("voltage_upper")
        declared_ok = True
        try:
            float(lo_d)
            float(hi_d)
        except (TypeError, ValueError):
            declared_ok = False
        if not declared_ok:
            _add(issues, "VOLTAGE_WINDOW_SYSTEM", WARN,
                 "未填写 voltage_lower/voltage_upper，无法与体系窗口对账"
                 "（实测极值仍然核对）",
                 f"system={window.system_id}")
        else:
            errs, warns = _check_declared_window(window, lo_d, hi_d)
            for e in errs:
                _add(issues, "VOLTAGE_WINDOW_SYSTEM", FAIL, e,
                     f"system={window.system_id}; declared=[{float(lo_d):g}, "
                     f"{float(hi_d):g}] V")
            for w in warns:
                _add(issues, "VOLTAGE_WINDOW_SYSTEM", WARN, w,
                     f"system={window.system_id}; declared=[{float(lo_d):g}, "
                     f"{float(hi_d):g}] V")
            if not errs and not warns:
                _add(issues, "VOLTAGE_WINDOW_SYSTEM", PASS,
                     f"声明窗口在 {window.label} 的窗口内",
                     f"system={window.system_id}; {window.describe()}")

        errs2, warns2 = _check_measured_window(
            window, float(Vv.min()), float(Vv.max())
        )
        for e in errs2:
            _add(issues, "VOLTAGE_SYSTEM_RANGE", FAIL, e,
                 f"system={window.system_id}; measured=[{float(Vv.min()):.4g}, "
                 f"{float(Vv.max()):.4g}] V")
        for w in warns2:
            _add(issues, "VOLTAGE_SYSTEM_RANGE", WARN, w,
                 f"system={window.system_id}; measured=[{float(Vv.min()):.4g}, "
                 f"{float(Vv.max()):.4g}] V")
        if not errs2 and not warns2:
            _add(issues, "VOLTAGE_SYSTEM_RANGE", PASS,
                 f"实测电压落在 {window.label} 的窗口内",
                 f"system={window.system_id}; measured=[{float(Vv.min()):.4g}, "
                 f"{float(Vv.max()):.4g}] V")

    # ---- 12. 脉冲协议的结构与时长（GITT / PITT）-------------------
    #
    # 这一段是本模块里唯一"算过东西"的检查，因为脉冲协议的 QC 不能只看
    # 时间列是否单调：脉冲的**实际时长**与**弛豫是否完整**决定了后面
    # D_s(x) 的横轴与 ΔV 的取法。三件事分开报：
    #   (a) 结构：找得到几个脉冲（找不到 = 这不是脉冲数据）
    #   (b) 时长：实测中位脉冲时长 vs 声明值（5 % 容差）
    #   (c) 离散：脉冲之间时长是否一致（std/median ≤ 0.10）
    #   (d) 分辨：脉冲内采样是否足够密（dt ≤ 脉冲时长/20）
    # 阈值写在这里而不是常量表里，是因为它们是**判据**不是平台约定，
    # 改判据必须同时改 tests/test_user_data_qc.py 里的用例。
    pulse_tol = 0.05
    spread_tol = 0.10
    resolution_frac = 20.0
    in_pulse_gap_factor = 3.0
    if pulse_proto:
        pulses, rests = _pulse_segments(tv, Iv)
        dur_p = _durations(pulses)
        dur_r = _durations(rests)
        sum_p = _duration_summary(dur_p)
        sum_r = _duration_summary(dur_r)
        if sum_p["n"] < 2:
            _add(issues, "GITT_STRUCTURE", FAIL,
                 f"protocol_type='{proto}' 但只识别出 {sum_p['n']} 个脉冲段"
                 f"（阈值 = 5 % 峰值电流）。要么这份数据不是脉冲协议，"
                 f"要么被截断成了一段 —— 两种情况下都不能拿去算 D_s",
                 f"pulses={sum_p['n']}, rests={sum_r['n']}, "
                 f"max|I|={float(np.nanmax(np.abs(Iv))):.6g} A")
        else:
            _add(issues, "GITT_STRUCTURE", PASS,
                 f"识别出 {sum_p['n']} 个脉冲段 / {sum_r['n']} 个静置段",
                 f"pulse median {sum_p['median_s']:.4g} s, "
                 f"rest median {sum_r['median_s']:.4g} s")
            if sum_r["n"] == 0:
                _add(issues, "GITT_STRUCTURE", FAIL,
                     "脉冲之间没有静置段：没有弛豫就没有平衡电位，"
                     "D_s 的 ΔV 无法定义",
                     "rests=0")

        if sum_p["n"] >= 1:
            declared_pulse = exp.get("pulse_duration_s")
            try:
                declared_pulse_v = float(declared_pulse)
            except (TypeError, ValueError):
                declared_pulse_v = float("nan")
            gap = _relative_gap(sum_p["median_s"], declared_pulse_v)
            if gap is None:
                _add(issues, "GITT_PULSE_DURATION", WARN,
                     f"未声明 pulse_duration_s，无法核对你后续用于 D_s 的脉冲时长。"
                     f"实测中位脉冲时长 = {sum_p['median_s']:.4g} s"
                     f"（请以这个实测值为准，或补声明）",
                     f"measured median {sum_p['median_s']:.4g} s")
            elif gap > pulse_tol:
                _add(issues, "GITT_PULSE_DURATION", FAIL,
                     f"声明脉冲时长 {declared_pulse_v:g} s，实测中位 "
                     f"{sum_p['median_s']:.4g} s，相差 {gap * 100:.1f} % "
                     f"（容差 {pulse_tol * 100:.0f} %）。D_s 与该时长成反比，"
                     f"这里差多少，D_s 就错多少",
                     f"declared {declared_pulse_v:g} s vs measured "
                     f"{sum_p['median_s']:.4g} s, n={sum_p['n']}")
            else:
                _add(issues, "GITT_PULSE_DURATION", PASS,
                     f"实测中位脉冲时长 {sum_p['median_s']:.4g} s 与声明 "
                     f"{declared_pulse_v:g} s 一致（相差 {gap * 100:.1f} %）",
                     f"n={sum_p['n']}, tol {pulse_tol * 100:.0f} %")

            if sum_p["n"] >= 2:
                if sum_p["spread"] > spread_tol:
                    _add(issues, "GITT_PULSE_UNIFORMITY", FAIL,
                         f"各脉冲时长不一致（std/median = {sum_p['spread']:.3f} "
                         f"> {spread_tol:.2f}）：最短 "
                         f"{sum_p['min_s']:.4g} s，最长 {sum_p['max_s']:.4g} s。"
                         f"如果按统一的 t 去算 D_s，每一点的误差都不一样",
                         f"n={sum_p['n']}, min {sum_p['min_s']:.4g} s, "
                         f"max {sum_p['max_s']:.4g} s")
                else:
                    _add(issues, "GITT_PULSE_UNIFORMITY", PASS,
                         f"脉冲时长一致（std/median = {sum_p['spread']:.3f}）",
                         f"n={sum_p['n']}, median {sum_p['median_s']:.4g} s")

        # (d) 脉冲内分辨：只按脉冲段的采样间隔算，不受静置段影响
        if pulses and med > 0:
            inner = []
            for lo, hi in pulses:
                sel = (tv >= lo - 1e-9) & (tv <= hi + 1e-9)
                if int(sel.sum()) >= 2:
                    inner.append(np.diff(tv[sel]))
            if inner:
                inner_dt = np.concatenate(inner)
                mx_in = float(inner_dt.max())
                if mx_in > in_pulse_gap_factor * med:
                    _add(issues, "GITT_PULSE_RESOLUTION", FAIL,
                         f"脉冲段内部有采样断点（最大 {mx_in:.4g} s，"
                         f"是中位间隔 {med:.4g} s 的 "
                         f"{mx_in / med:.1f} 倍）。脉冲内的 ΔV 与时长都不可信",
                         f"max dt in pulse {mx_in:.4g} s vs median dt {med:.4g} s")
                elif (
                    sum_p["median_s"] == sum_p["median_s"]
                    and mx_in > sum_p["median_s"] / resolution_frac
                ):
                    _add(issues, "GITT_PULSE_RESOLUTION", WARN,
                         f"脉冲内采样偏稀（最大间隔 {mx_in:.4g} s，"
                         f"脉冲时长 {sum_p['median_s']:.4g} s）：脉冲只被 "
                         f"{sum_p['median_s'] / mx_in:.0f} 个点描述，"
                         f"外推 D_s 前先确认 ΔV 取得住",
                         f"max dt in pulse {mx_in:.4g} s")
                else:
                    _add(issues, "GITT_PULSE_RESOLUTION", PASS,
                         "脉冲内采样足够密",
                         f"max dt in pulse {mx_in:.4g} s, "
                         f"median dt {med:.4g} s")

    return issues


def summarize(issues: List[dict]) -> dict:
    n_fail = sum(1 for i in issues if i["severity"] == FAIL)
    n_warn = sum(1 for i in issues if i["severity"] == WARN)
    return {
        "import_status": "FAIL" if n_fail else "PASS",
        "simulation_allowed": n_fail == 0,
        "n_fail": n_fail,
        "n_warn": n_warn,
        "n_checks": len(issues),
    }

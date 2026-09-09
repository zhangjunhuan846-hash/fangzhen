# ============================================================
# Validation gate（S4）
#
# 导入后必须通过的检查。严重错误 = FAIL，不允许继续 simulation。
# 每一项都输出可读的中文说明 + 证据数字。
# ============================================================

from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd

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
    dts = np.diff(tv)
    dts = dts[dts > 0]
    if dts.size:
        med = float(np.median(dts))
        mx = float(dts.max())
        _add(issues, "SAMPLING_INTERVAL", PASS,
             "采样间隔统计已记录",
             f"median dt={med:.4g} s, max dt={mx:.4g} s, "
             f"duration={tv[-1] - tv[0]:.4g} s")
        if mx > 20 * med and med > 0:
            _add(issues, "SAMPLING_INTERVAL_GAP", WARN,
                 f"存在明显采样间断（最大间隔是中位数间隔的 {mx / med:.0f} 倍）",
                 f"median {med:.4g} s vs max {mx:.4g} s")

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

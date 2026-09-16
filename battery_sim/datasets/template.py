# ============================================================
# 新数据集接入模板（copy → 填 hook → 跑自检）
#
# 为什么需要这个文件
#   平台对数据集的全部要求，其实只有一件事：任何一份实验记录都要能变成
#   canonical 四列（time_s / current_A / voltage_V / capacity_Ah）+ 一个
#   实测初始 OCV + 一个实测环境温度。这件事在 7 个 adapter 里各写了一遍，
#   而重复的代价不是打字量，是**每一次都漏掉不同的检查**：
#     · 单位（mV vs V、mA vs A、Ah vs mAh）
#     · 符号（充电为正还是放电为正）
#     · 时间基准（绝对时间戳 vs 相对窗口起点）
#     · 容量列（积分出来的、还是仪器直接给的）
#   这四类错误**都不会抛异常**，只会让后面的可辨识性结论变脏。所以模板把
#   通用骨架写死，把"这份文件长什么样"留成 hook，并把四类陷阱做成**能跑的检查**。
#
# 用法（4 步）
#   1. cp battery_sim/datasets/template.py battery_sim/datasets/<new_name>.py
#   2. 类改名 <NewName>Adapter（registry 按 PascalCase(adapter) + "Adapter" 解析）
#   3. 实现 read_source_table / select_discharge_window / read_initial_state
#      （+ read_ambient_temperature，或直接在 yaml 的 extra 里写实测温度）
#   4. 在 configs/datasets.yaml 加一条（必须写 extra.source），然后
#        python -m battery_sim.datasets.template --check <dataset_id>
#      自检全绿才算接完。清单与坑清单见 docs/adding_a_dataset.md
#
# 契约（不可协商）
#   · 本文件与所有 adapter **不许 import pybamm**（纯数据 I/O 层）
#   · canonical 符号约定：**放电为正**
#   · 时间列相对**窗口起点**，从 0 开始
#   · 容量列单位 **Ah**（不是 mAh）
# ============================================================

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from battery_sim.datasets.base import BatteryDatasetAdapter

ROOT = Path(__file__).resolve().parents[2]

#: canonical 四列。缺任何一列，仿真层就直接不可用。
CANONICAL_COLUMNS = ("time_s", "current_A", "voltage_V", "capacity_Ah")

#: 平台唯一符号约定。写反了不会报错，只会让"放电"变成"充电"。
SIGN_CONVENTION = "discharge = +A"

#: 单个电芯电压的物理上限（V）。超过它基本只有一种解释：源文件用 mV。
MAX_PLAUSIBLE_VOLTAGE_V = 6.0

#: 积分电荷与声明容量列允许的相对差。
CAPACITY_AGREEMENT = 0.20


class CanonicalFormatError(ValueError):
    """canonical 表违反契约。

    刻意与 "参数名写错" 那类错误分开：**格式错误是接线问题，可修**，
    调用方应该能单独捕获它并把源文件的行号/列名带回去给人看。
    """


# ------------------------------------------------------------------
# 契约检查（可被任何 adapter 复用，不必继承模板）
# ------------------------------------------------------------------
def validate_canonical(
    df: pd.DataFrame,
    *,
    what: str = "",
    require: Sequence[str] = CANONICAL_COLUMNS,
    require_time_from_zero: bool = True,
    expect_current_sign: Optional[str] = None,
) -> Dict[str, Any]:
    """检查一张 canonical 表，返回 ``{ok, errors, warnings, stats}``。

    分两级：
      · ``errors``   物理上不可能 / 仿真层会直接炸 → 必须修
      · ``warnings`` 可能是陷阱但需要人判断 → 必须**读一遍**再决定

    ``expect_current_sign`` 取 ``"discharge"`` / ``"charge"`` / None。
    符号这种事**没法自动判定**，只能声明后核对，所以这里只做一致性检查，
    不猜。
    """
    label = f"[{what}] " if what else ""
    errors: List[str] = []
    warnings: List[str] = []
    stats: Dict[str, Any] = {"n_rows": int(len(df))}

    if not isinstance(df, pd.DataFrame):
        return {"ok": False, "errors": [f"{label}不是 DataFrame"],
                "warnings": [], "stats": stats}

    missing = [c for c in require if c not in df.columns]
    if missing:
        errors.append(
            f"{label}缺少必需列 {missing}；现有列 {list(df.columns)}"
        )
        return {"ok": False, "errors": errors, "warnings": warnings,
                "stats": stats}
    if len(df) == 0:
        errors.append(f"{label}表是空的（0 行）")
        return {"ok": False, "errors": errors, "warnings": warnings,
                "stats": stats}

    cols: Dict[str, np.ndarray] = {}
    for c in require:
        try:
            cols[c] = pd.to_numeric(df[c], errors="raise").to_numpy(float)
        except Exception:
            errors.append(f"{label}列 '{c}' 不是数值（有非数字内容？）")
    if errors:
        return {"ok": False, "errors": errors, "warnings": warnings,
                "stats": stats}

    t = cols["time_s"]
    i = cols["current_A"]
    v = cols["voltage_V"]

    # ---- 空值 --------------------------------------------------------
    for c in require:
        n_nan = int(np.sum(~np.isfinite(cols[c])))
        if n_nan:
            errors.append(f"{label}列 '{c}' 有 {n_nan} 个非有限值")
        stats[f"n_nonfinite_{c}"] = n_nan

    # ---- 时间基准与单调性 --------------------------------------------
    stats["t_start_s"] = float(t[0])
    stats["t_stop_s"] = float(t[-1])
    stats["dt_min_s"] = float(np.min(np.diff(t))) if len(t) > 1 else float("nan")
    stats["dt_max_s"] = float(np.max(np.diff(t))) if len(t) > 1 else float("nan")
    if len(t) > 1:
        d = np.diff(t)
        n_nonpos = int(np.sum(d <= 0))
        if n_nonpos:
            errors.append(
                f"{label}时间列有 {n_nonpos} 处非递增（含重复）——"
                f"采样会被仿真层的插值静默吃掉"
            )
        n_dup = int(np.sum(d == 0))
        stats["n_duplicate_timestamps"] = n_dup
        if 0 < n_dup:
            warnings.append(f"{label}有 {n_dup} 个重复时间戳")
    if require_time_from_zero and abs(float(t[0])) > 1e-9:
        errors.append(
            f"{label}时间列不是从 0 开始（首点 {float(t[0]):.6g} s）。"
            f"canonical 约定是**相对窗口起点**；绝对时间戳会把整条剖面平移，"
            f"而平移在电压上看不出来。"
        )

    # ---- 电流：先说清楚"零电流" --------------------------------------
    stats["current_min_A"] = float(np.min(i))
    stats["current_max_A"] = float(np.max(i))
    if np.all(i == 0.0):
        errors.append(
            f"{label}电流整列为 0 —— 没有激励就没有可辨识性可言。"
            f"先确认符号/单位没被解析器吃掉。"
        )
    frac_pos = float(np.mean(i > 0)) if len(i) else float("nan")
    stats["fraction_positive_current"] = frac_pos
    if expect_current_sign == "discharge" and frac_pos < 0.5:
        warnings.append(
            f"{label}声明为放电窗口，但只有 {frac_pos * 100:.1f} % 的采样"
            f"电流为正（约定 {SIGN_CONVENTION}）——很可能符号翻转漏了"
        )
    if expect_current_sign == "charge" and frac_pos > 0.5:
        warnings.append(
            f"{label}声明为充电窗口，但 {frac_pos * 100:.1f} % 的采样电流"
            f"为正（约定 {SIGN_CONVENTION}）"
        )
    if 0.0 < frac_pos < 1.0:
        stats["current_sign_changes"] = int(np.sum(np.diff(np.sign(i)) != 0))

    # ---- 电压：单位陷阱 ----------------------------------------------
    stats["voltage_min_V"] = float(np.min(v))
    stats["voltage_max_V"] = float(np.max(v))
    if float(np.max(v)) > MAX_PLAUSIBLE_VOLTAGE_V:
        warnings.append(
            f"{label}电压最大 {float(np.max(v)):.3f} V，超过单芯物理上限 "
            f"{MAX_PLAUSIBLE_VOLTAGE_V} V —— 源文件很可能是 **mV**"
        )
    if float(np.max(v)) < 0.05:
        warnings.append(f"{label}电压最大 {float(np.max(v)):.6g} V，偏低得可疑")

    # ---- 容量：与积分电荷对账 ----------------------------------------
    if len(t) > 1:
        charge_Ah = float(np.sum(0.5 * (i[1:] + i[:-1]) * np.diff(t))) / 3600.0
    else:
        charge_Ah = 0.0
    cap = cols["capacity_Ah"]
    cap_span = float(np.max(cap) - np.min(cap))
    stats["integrated_charge_Ah"] = charge_Ah
    stats["declared_capacity_span_Ah"] = cap_span
    stats["capacity_ratio_span_over_charge"] = (
        cap_span / abs(charge_Ah) if charge_Ah != 0 else float("nan")
    )
    if charge_Ah != 0 and cap_span > 0:
        rel = abs(cap_span - abs(charge_Ah)) / abs(charge_Ah)
        stats["capacity_relative_mismatch"] = rel
        if rel > CAPACITY_AGREEMENT:
            warnings.append(
                f"{label}容量列跨度 {cap_span * 1e3:.4f} mAh，与积分电荷 "
                f"{abs(charge_Ah) * 1e3:.4f} mAh 差 {rel * 100:.1f} % ——"
                f"两列至少有一个不是这份窗口的（或容量列是仪器另算的）"
            )
    if float(np.min(cap)) < 0:
        warnings.append(f"{label}容量列出现负值（最小 {float(np.min(cap)):.6g}）")

    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "stats": stats}


def format_check(result: Dict[str, Any], *, what: str = "") -> str:
    """把 :func:`validate_canonical` 的结果排成人能读的一段。"""
    head = f"{what}: " if what else ""
    lines = [f"{head}{'PASS' if result['ok'] else 'FAIL'}"
             f"（{result['stats'].get('n_rows', 0)} 行）"]
    for e in result["errors"]:
        lines.append(f"  ERROR   {e}")
    for w in result["warnings"]:
        lines.append(f"  WARN    {w}")
    return "\n".join(lines)


# ------------------------------------------------------------------
# 骨架 adapter
# ------------------------------------------------------------------
class NewDatasetAdapter(BatteryDatasetAdapter):
    """通用骨架。子类只需要填 hook，其余方法本类已实现。

    子类**不要**重写 ``load_raw`` / ``load_discharge`` / ``list_cells`` /
    ``rate_info`` —— 重写它们就等于绕过了 :func:`validate_canonical`，
    而绕过检查正是这个模板要防的事。

    录制型协议（GITT / p-OCV / 循环日志）是**可选的**：基类的
    ``load_protocol`` / ``load_processed_protocol`` 会主动抛
    ``NotImplementedError``，平台靠"子类是否覆盖了它们"判断数据集有没有
    这种能力（``type(adapter).X is not Base.X``）。所以模板**刻意不覆盖**
    它们。若本数据集有录制型协议，在子类里自己覆盖，参考
    ``battery_sim/datasets/dlr_gitt.py``。
    """

    #: 源文件里的倍率标签 → 数值 C-rate（见 battery_sim/rates.py）
    SOURCE_TO_CANONICAL: Dict[str, float] = {}

    def __init__(self, config):
        # 数据来源是硬要求：没有来源的实验数据在本平台不可引用。
        extra = dict(config.extra or {})
        source = str(extra.get("source") or "").strip()
        if not source:
            raise ValueError(
                f"dataset '{config.dataset_id}': configs/datasets.yaml 的 "
                f"extra.source 必填（这份数据从哪来：论文/DOI/本实验室/仪器"
                f"导出）。没有来源的数据在本平台不可引用。"
            )
        self.config = config
        self._extra = extra
        self.source = source
        self._raw_dir = ROOT / str(config.raw_dir)

    # ---------------- 已实现（不要重写） ----------------
    def get_metadata(self) -> dict:
        return {
            "dataset_id": self.config.dataset_id,
            "name": self.config.name,
            "chemistry": self.config.chemistry,
            "ion": self.config.ion,
            "source": self.source,
            "raw_dir": str(self.config.raw_dir),
            "cells": list(self.list_cells()),
            "nominal_capacity_Ah": self.config.nominal_capacity_Ah,
            "voltage_window_V": [
                self.config.lower_voltage_cutoff_V,
                self.config.upper_voltage_cutoff_V,
            ],
            "material_metadata": self._extra.get("material_metadata"),
        }

    def list_cells(self):
        return [str(c) for c in (self.config.cells or [])]

    def list_rates(self):
        return [str(r) for r in (self.config.rates or [])]

    def load_raw(self, cell) -> pd.DataFrame:
        raw = self.read_source_table(str(cell))
        norm = self.normalise_source_table(raw, str(cell))
        if not isinstance(norm, pd.DataFrame):
            raise TypeError(
                f"{type(self).__name__}.normalise_source_table 必须返回 "
                f"DataFrame，得到 {type(norm).__name__}"
            )
        return norm

    def load_discharge(self, cell, rate) -> pd.DataFrame:
        """一条额定放电，返回已校验的 canonical 表。

        这是**唯一**允许被仿真层消费的放电入口，所以校验挂在这里：
        出了这个门就假定列名/单位/符号/时间基准都是对的。
        """
        raw = self.load_raw(str(cell))
        df = self.select_discharge_window(raw, str(cell), rate)
        if not isinstance(df, pd.DataFrame):
            raise TypeError(
                f"{type(self).__name__}.select_discharge_window 必须返回 "
                f"DataFrame，得到 {type(df).__name__}"
            )
        df = df.reindex(columns=list(CANONICAL_COLUMNS)).copy()
        result = validate_canonical(
            df, what=f"{self.config.dataset_id}/{cell}/rate={rate}",
            expect_current_sign="discharge",
        )
        if not result["ok"]:
            raise CanonicalFormatError(format_check(
                result, what=f"{self.config.dataset_id}/{cell}/rate={rate}"))
        df.attrs["contract_check"] = result
        df.attrs["canonical_convention"] = SIGN_CONVENTION
        return df

    def get_initial_state(self, cell) -> float:
        value = float(self.read_initial_state(str(cell)))
        if not (-0.1 < value < MAX_PLAUSIBLE_VOLTAGE_V):
            raise ValueError(
                f"{type(self).__name__}.read_initial_state 返回 {value} V，"
                f"不是一个单芯 OCV（单位是 mV 吗？）"
            )
        return value

    def get_ambient_temperature(self, cell) -> float:
        """实测环境温度（°C）。

        默认从 yaml 的 ``extra.ambient_temperature_C`` 读；如果这份数据
        的温度是逐点记录的，覆盖 ``read_ambient_temperature``。
        """
        if self._extra.get("ambient_temperature_C") is not None:
            return float(self._extra["ambient_temperature_C"])
        return float(self.read_ambient_temperature(str(cell)))

    # ---------------- hook（必须实现） ----------------
    def read_source_table(self, cell) -> pd.DataFrame:
        """读源文件，**原样**返回（不重命名、不换算、不翻转符号）。

        保持"原样"是有意的：重命名/换算集中在
        :meth:`normalise_source_table` 一处，源文件的真实列名只在一处出现。
        """
        raise NotImplementedError(
            f"{type(self).__name__}.read_source_table(cell) 未实现。\n"
            f"  要返回：源文件的整张表（可以是多 step 的长日志），列名照抄源文件。\n"
            f"  注意：编码（Latin-1 / GBK / UTF-8-BOM）、表头行数、"
            f"分隔符先在确认一遍。"
        )

    def select_discharge_window(self, raw, cell, rate) -> pd.DataFrame:
        """从源表里切出这一条放电，返回 canonical 四列。

        切之前必须确认：这是**哪个 step**、是否含 CV 段、截止条件是什么。
        """
        raise NotImplementedError(
            f"{type(self).__name__}.select_discharge_window(...) 未实现。\n"
            f"  要返回：columns = {list(CANONICAL_COLUMNS)}（放电为正、"
            f"time_s 从 0 开始、capacity_Ah 用 Ah）。"
        )

    def read_initial_state(self, cell) -> float:
        """**实测**的开路电压（V），用作仿真初值。

        不许用"第一条采样点的电压"凑数：那是带电流时的电压，含过电位，
        会让模型从错误的 SOC 出发（平台里曾留下 44.64 mV 的缺口）。
        """
        raise NotImplementedError(
            f"{type(self).__name__}.read_initial_state(cell) 未实现。\n"
            f"  要返回：静置后实测 OCV（V）。"
        )

    def read_ambient_temperature(self, cell) -> float:
        """实测环境温度（°C）。仅在 yaml 没写 extra.ambient_temperature_C 时调用。"""
        raise NotImplementedError(
            f"{type(self).__name__}.read_ambient_temperature(cell) 未实现。\n"
            f"  要返回：实测温度（°C）。"
        )

    # ---------------- hook（可选，默认恒等） ----------------
    def normalise_source_table(self, raw: pd.DataFrame, cell) -> pd.DataFrame:
        """列重命名 / 单位换算 / 符号翻转。默认恒等。

        四类陷阱都集中在这一处修，修完 :meth:`load_discharge` 会替你验。
        """
        return raw


# ------------------------------------------------------------------
# 自检 CLI：新 adapter 接完之后跑这个
# ------------------------------------------------------------------
def _check_dataset(dataset_id: str) -> int:
    from battery_sim.registry import get_dataset

    try:
        adapter = get_dataset(dataset_id)
    except Exception as exc:
        print(f"FAIL  无法实例化 '{dataset_id}'：{type(exc).__name__}: {exc}")
        return 1

    problems: List[str] = []
    warnings: List[str] = []

    print(f"=== 数据集契约自检：{dataset_id} ===")
    print(f"adapter      : {type(adapter).__name__}")
    if type(adapter) is NewDatasetAdapter:
        print("NOTE  这是模板本身，不是一份真实 adapter")

    # 1 元数据（来源必须查得到；查不到只警告，不回退去猜）
    try:
        meta = adapter.get_metadata()
        source = (meta.get("source")
                  or (adapter.config.extra or {}).get("source"))
        print(f"metadata     : source = {source}")
        if not str(source or "").strip():
            warnings.append(
                "本数据集没有声明数据来源（configs 里的 extra.source）—— "
                "新接数据集时这是必填项，见 docs/adding_a_dataset.md"
            )
        for key in ("dataset_id", "name", "chemistry", "ion"):
            if not str(meta.get(key) or "").strip():
                problems.append(f"metadata.{key} 为空")
    except Exception as exc:
        problems.append(f"get_metadata 失败：{type(exc).__name__}: {exc}")

    # 2 单元
    cells = [str(c) for c in adapter.list_cells()]
    print(f"cells        : {cells}")
    if not cells:
        problems.append("list_cells() 为空 —— 仿真层无从下手")

    # 3 每条放电（协议型数据集本来就没有额定放电，那不算错误）
    rates = [str(r) for r in adapter.list_rates()]
    print(f"rates        : {rates}")
    for cell in cells:
        for rate in rates:
            tag = f"{dataset_id}/{cell}/rate={rate}"
            try:
                df = adapter.load_discharge(cell, rate)
                res = df.attrs.get("contract_check", {})
                print(f"  {tag}: {len(df)} 行  "
                      f"{df['voltage_V'].min():.4f}-{df['voltage_V'].max():.4f} V  "
                      f"{df['capacity_Ah'].iloc[-1] * 1e3:.3f} mAh")
                for w in res.get("warnings", []):
                    warnings.append(w)
            except NotImplementedError:
                warnings.append(
                    f"{tag}: 本数据集不提供额定放电（协议型数据集）⇒ 跳过 "
                    f"canonical 放电检查；容量基准请走录制型协议"
                )
                print(f"  {tag}: skip（无额定放电）")
            except Exception as exc:
                problems.append(f"{tag}: {type(exc).__name__}: {exc}")
                print(f"  {tag}: FAIL {exc}")

    # 4 初始态 / 温度
    for cell in cells:
        for name, call in (("get_initial_state", adapter.get_initial_state),
                           ("get_ambient_temperature",
                            adapter.get_ambient_temperature)):
            try:
                val = call(cell)
                if not np.isfinite(val):
                    problems.append(f"{name}('{cell}') 不是有限值：{val}")
                else:
                    print(f"  {name}('{cell}') = {val}")
            except Exception as exc:
                problems.append(f"{name}('{cell}'): {type(exc).__name__}: {exc}")

    # 5 容量一致化（尺度对齐门的前置；这里只报数不判）
    nominal = adapter.config.nominal_capacity_Ah
    print(f"nominal_cap  : {nominal} Ah")
    if nominal is None:
        warnings.append(
            "没有声明 nominal_capacity_Ah —— 尺度对齐门只能从参数集反推模型容量"
        )
    else:
        for cell in cells:
            for rate in rates:
                try:
                    df = adapter.load_discharge(cell, rate)
                    passed = abs(float(df["capacity_Ah"].iloc[-1]))
                    if passed > 0:
                        print(f"  Q(measured,{cell},{rate}) = "
                              f"{passed * 1e3:.4f} mAh "
                              f"| vs nominal x{passed / nominal:.4f}")
                except Exception:
                    pass

    # 6 录制型协议（可选能力）
    from battery_sim.datasets.base import BatteryDatasetAdapter

    has_proto = (
        type(adapter).load_processed_protocol
        is not BatteryDatasetAdapter.load_processed_protocol
    )
    if has_proto:
        ids: List[str] = []
        try:
            ids = list(adapter.list_protocols())
        except Exception as exc:
            problems.append(f"list_protocols 失败：{type(exc).__name__}: {exc}")
        print(f"protocols    : {len(ids)} 个（能力已声明）")

        # 广告出来的 id 必须**真的能载入**。此外，若数据集按窗口回放
        # （有 list_triplets / find_triplet），顺手验一个窗口 id —— 那才是
        # 仿真层实际回放的单位（G6.1c 用的是 `GITT-charge#t475` 这种）。
        to_test: List[str] = list(ids[:3])
        lister = getattr(adapter, "list_triplets", None)
        if callable(lister):
            try:
                to_test += [str(x) for x in list(lister())[:1]]
            except Exception as exc:
                warnings.append(
                    f"list_triplets 失败：{type(exc).__name__}: {exc}"
                )

        n_ok = 0
        for pid in to_test:
            try:
                df = adapter.load_processed_protocol(cells[0], pid)
                adapter.load_protocol(pid)
                res = validate_canonical(
                    df, what=f"{dataset_id}/{pid}", require=CANONICAL_COLUMNS,
                    require_time_from_zero=False,
                )
                if res["ok"]:
                    n_ok += 1
                    print(f"  protocol {pid}: {len(df)} 行 OK")
                else:
                    problems.extend(res["errors"])
            except Exception as exc:
                warnings.append(
                    f"广告的协议 id '{pid}' 载入失败："
                    f"{type(exc).__name__}: {str(exc)[:150]}"
                    f"（扫程级 id 未必可整流回放；若按窗口回放，调用方应传"
                    f"窗口 id，例如 '#tN'）"
                )
        if to_test and n_ok == 0:
            problems.append(
                f"list_protocols 广告了 {ids}，但没有任何 id 能载入 —— "
                f"list_protocols 必须返回 load_protocol 接受的 id"
            )
    else:
        print("protocols    : 未声明（基类接口保持未覆盖，符合契约）")

    print()
    for w in warnings:
        print(f"WARN  {w}")
    for p in problems:
        print(f"ERROR {p}")
    print(f"\n=== {'PASS' if not problems else 'FAIL'} "
          f"（{len(problems)} 个错误 / {len(warnings)} 个警告）===")
    return 0 if not problems else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m battery_sim.datasets.template",
        description="新数据集接入自检（契约：canonical 四列 + 初值 + 温度）",
    )
    parser.add_argument("--check", metavar="DATASET_ID",
                        help="对某个已注册数据集跑整套契约自检")
    parser.add_argument("--metadata", metavar="PATH",
                        help="校验一份材料元数据 yaml（回收石墨模板用）")
    parser.add_argument("--canonical", metavar="CSV",
                        help="直接校验一个 canonical CSV（不经过 adapter）")
    args = parser.parse_args(argv)

    if args.metadata:
        from battery_sim.datasets.material_metadata import (
            load_metadata, render, validate,
        )
        try:
            meta = load_metadata(args.metadata)
        except Exception as exc:
            print(f"FAIL  读不了 {args.metadata}：{type(exc).__name__}: {exc}")
            return 1
        res = validate(meta)
        print(render(meta, res))
        return 0 if not res["errors"] else 1

    if args.canonical:
        df = pd.read_csv(args.canonical)
        res = validate_canonical(df, what=Path(args.canonical).name)
        print(format_check(res, what=Path(args.canonical).name))
        for k, val in sorted(res["stats"].items()):
            print(f"  {k} = {val}")
        return 0 if res["ok"] else 1

    if args.check:
        return _check_dataset(args.check)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "CANONICAL_COLUMNS",
    "SIGN_CONVENTION",
    "CanonicalFormatError",
    "NewDatasetAdapter",
    "format_check",
    "main",
    "validate_canonical",
]

# ============================================================
# 回收石墨半电池 adapter 骨架（空模板，待填）
#
# 对应用户的实验方案（不在本文件重复）：
#   docs/graphite_halfcell_phase1_test_plan.md（Phase 0 → Phase 1 → 回收石墨）
#   docs/graphite_heat_treatment_test_plan.md（A 组处理温度）
#
# 为什么先有这个空模板
#   真实数据到手时，"接进来"只有两种失败方式：
#     (a) 格式没问清（编码/表头/相位/符号/单位/时间基准）→ 契约检查兜
#     (b) 几何与来源没记（载量/厚度/粒径/批次）→ **本文件在构造时直接报错**
#   (b) 比 (a) 更危险：几何缺失不会让任何一步失败，只会让不同样品之间
#   的 D_s 差异无法归因（D ∝ R²）。
#
# 启用（4 步）
#   1. cp templates/recycled_graphite/recycled_graphite.py battery_sim/datasets/
#   2. cp templates/recycled_graphite/metadata.example.yaml data/raw/LIB/<样品>.yaml 并填
#   3. datasets_yaml_snippet.yaml 贴进 configs/datasets.yaml（改 sample/cells）
#   4. 填下面 5 个 hook，然后
#        python -m battery_sim.datasets.template --check recycled_graphite
# ============================================================

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pandas as pd

from battery_sim.datasets.material_metadata import (
    MaterialMetadataError,
    load_metadata,
    render,
    validate,
)
from battery_sim.datasets.template import ROOT, NewDatasetAdapter


class RecycledGraphiteAdapter(NewDatasetAdapter):
    """回收石墨半电池。元数据不完整时**构造即失败**，不给"先跑起来再说"。"""

    def __init__(self, config):
        super().__init__(config)

        rel = str(self._extra.get("material_metadata") or "").strip()
        if not rel:
            raise MaterialMetadataError(
                f"dataset '{config.dataset_id}': extra.material_metadata 必填"
                f"（指向这份样品的材料元数据 yaml）。\n"
                f"  回收石墨的比较对象是**同批料不同处理**，材料信息缺失时"
                f"任何参数差异都不可归因。\n"
                f"  模板：templates/recycled_graphite/metadata.example.yaml"
            )
        path = Path(rel)
        self.metadata_path = path if path.is_absolute() else (ROOT / path)
        self.metadata: Dict[str, Any] = load_metadata(self.metadata_path)

        result = validate(self.metadata)
        self.metadata_warnings = list(result["warnings"])
        if result["errors"]:
            raise MaterialMetadataError(
                f"{self.metadata_path} 不满足材料元数据契约，逐条如下：\n  - "
                + "\n  - ".join(result["errors"])
            )

    # ---------------- 已实现：材料侧接口 ----------------
    def material_summary(self) -> str:
        """材料元数据 + 警告的清单（报告里可直接引用）。"""
        return render(self.metadata)

    @property
    def sample_group(self) -> str:
        """样品组：用于 fresh / recycled 对照分组。"""
        return str(self.metadata.get("material_class") or "unknown")

    # ---------------- hook 1/5：读源文件 ----------------
    def read_source_table(self, cell) -> pd.DataFrame:
        """读仪器导出的原始表，**原样**返回（不重命名、不换算、不翻符号）。

        动手前先回答 docs/adding_a_dataset.md §2 的 10 个问题，至少：
          编码？几行表头？有没有 step/Command 列？电流单位 A 还是 mA？
          时间列是绝对时间戳还是相对秒？
        """
        raise NotImplementedError(
            "RecycledGraphiteAdapter.read_source_table 未实现。\n"
            "  源文件格式先按 docs/adding_a_dataset.md §2 问清楚；\n"
            "  若用的是新威/LAND/Arbin 导出，注意表头行数与 unit 行。"
        )

    # ---------------- hook 2/5：列重命名 / 单位 / 符号 ----------------
    def normalise_source_table(self, raw: pd.DataFrame, cell) -> pd.DataFrame:
        """四类陷阱集中在这一处修：列名、单位、符号、时间基准。"""
        raise NotImplementedError(
            "RecycledGraphiteAdapter.normalise_source_table 未实现。\n"
            "  示例做法（按实际列名改）：\n"
            "    df = raw.rename(columns={'Time(h)': 't_h', 'Current(mA)': 'I_mA',\n"
            "                             'Voltage(V)': 'V'})\n"
            "    df['time_s'] = df['t_h'] * 3600.0\n"
            "    df['current_A'] = df['I_mA'] / 1e3 * (-1)   # 若仪器约定充电为正\n"
            "  完成后 load_discharge 会替你验符号与时间基准。"
        )

    # ---------------- hook 3/5：切出这一条放电 ----------------
    def select_discharge_window(self, raw, cell, rate) -> pd.DataFrame:
        """返回 canonical 四列（放电为正、time_s 从 0 开始、capacity_Ah 用 Ah）。

        先确认：这是哪个 step、含不含 CV 段、截止条件是什么。
        多个 step 的文件**不要只取第一段**。
        """
        raise NotImplementedError(
            "RecycledGraphiteAdapter.select_discharge_window 未实现。"
        )

    # ---------------- hook 4/5：实测初值 ----------------
    def read_initial_state(self, cell) -> float:
        """静置后**实测** OCV（V）。不要拿第一条带电流的采样顶替：那含过电位。"""
        raise NotImplementedError(
            "RecycledGraphiteAdapter.read_initial_state 未实现。"
        )

    # ---------------- hook 5/5：实测温度 ----------------
    def read_ambient_temperature(self, cell) -> float:
        """实测环境温度（°C）。若 yaml 写了 extra.ambient_temperature_C 则不走这里。"""
        raise NotImplementedError(
            "RecycledGraphiteAdapter.read_ambient_temperature 未实现。"
        )

    # ---------------- 可选：录制型协议 ----------------
    # 这份数据若有 GITT / p-OCV / 循环日志的录制段，在这里覆盖基类的三个方法：
    #   list_protocols() / load_protocol(protocol_id) / load_processed_protocol(cell, pid)
    # 覆盖 = 声明能力（平台按 type(adapter).X is not Base.X 判定）。
    # 参考实现：battery_sim/datasets/dlr_gitt.py

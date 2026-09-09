# ============================================================
# UserDatasetAdapter（S5 接入）
#
# 继承平台的 BatteryDatasetAdapter，把 generic importer 产出的
# canonical CSV 喂给平台现有的 run_baseline_cell()。
#
# 关键点：本文件不复制、不修改任何科学计算逻辑。
# 平台的 runner / evaluator / PyBaMM 调用完全不动。
# ============================================================

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

from battery_sim.datasets.base import BatteryDatasetAdapter
from battery_sim.schemas import DatasetConfig

# 平台默认环境温度假设（只在用户既没声明、数据里也没有温度时启用，
# 且会在 manifest / 报告里明确标成 assumed，不伪装成实测）
DEFAULT_AMBIENT_C = 25.0


class UserDatasetAdapter(BatteryDatasetAdapter):
    """
    一个用户数据包 = 一个 cell + 一个 rate（用户给什么就跑什么）。
    """

    def __init__(
        self,
        canonical_csv: Path,
        exp: dict,
        gate: dict,
        dataset_id: str,
    ):
        self.canonical_csv = Path(canonical_csv)
        self.exp = dict(exp)
        self.gate = dict(gate)
        self.dataset_id = dataset_id

        self._df: pd.DataFrame | None = None

        amb = self.exp.get("temperature", None)
        self.ambient_source = (
            "user_declared_in_dataset_info" if amb is not None else "assumed_default"
        )
        self._ambient_C = (
            float(amb) if amb is not None else self._ambient_from_data()
        )

        cfg_raw = {
            "name": f"USER: {self.exp.get('dataset_name', dataset_id)}",
            "chemistry": str(self.exp.get("chemistry", "")),
            "raw_dir": str(self.canonical_csv.parent),
            "adapter": "user_tools",
            "protocol": str(self.exp.get("protocol", "") or "user_provided"),
            "parameter_set": str(gate.get("parameter_set") or ""),
            "cells": [str(self.exp.get("sample_id", "") or "user")],
            "rates": ["as_provided"],
            "supported_models": ["SPM", "SPMe", "DFN"],
            "nominal_capacity_Ah": self._as_float(
                self.exp.get("nominal_capacity", None)
            ),
            "lower_voltage_cutoff_V": self._as_float(
                self.exp.get("voltage_lower", None)
            ),
            "upper_voltage_cutoff_V": self._as_float(
                self.exp.get("voltage_upper", None)
            ),
        }
        # 未知键会被 from_dict 收进 extra（DatasetConfig 是 frozen）
        cfg_raw["cell_configuration"] = str(
            self.exp.get("cell_configuration", "full_cell")
        )
        cfg_raw["working_electrode"] = str(
            self.exp.get("working_electrode", "") or ""
        )
        self.config = DatasetConfig.from_dict(dataset_id, cfg_raw)

    # ------------------------------------------------------------------
    @staticmethod
    def _as_float(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------
    def _ambient_from_data(self) -> float:
        df = self._load()
        if "cell_temperature_C" in df.columns:
            s = df["cell_temperature_C"].dropna()
            if len(s):
                self.ambient_source = "measured_cell_temperature_median"
                return float(s.median())
        self.ambient_source = "assumed_default"
        return DEFAULT_AMBIENT_C

    # ------------------------------------------------------------------
    def _load(self) -> pd.DataFrame:
        if self._df is None:
            df = pd.read_csv(self.canonical_csv)
            # 环境温度列：优先用户声明，其次实测中位数，最后平台默认假设
            amb = self.exp.get("temperature", None)
            if amb is not None:
                df["temperature_ambient_C"] = float(amb)
            elif "cell_temperature_C" in df.columns and \
                    df["cell_temperature_C"].dropna().size:
                df["temperature_ambient_C"] = float(
                    df["cell_temperature_C"].dropna().median()
                )
            else:
                df["temperature_ambient_C"] = DEFAULT_AMBIENT_C
            soc = self.exp.get("initial_soc", None)
            df.attrs["initial_soc"] = float(soc) if soc is not None else 1.0
            df.attrs["ambient_source"] = self.ambient_source

            # 半电池：沿用平台 v0.5 的 fixed_initial_concentration 扩展点，
            # 用实测起始电压反解工作电极初始锂浓度。
            # （这是平台已支持的初始化方式，本文件不新增/修改科学逻辑）
            if str(self.exp.get("cell_configuration", "")) == "half_cell":
                df.attrs["initialisation"] = self._inverse_ocp_init(df)

            self._df = df
        return self._df

    # ------------------------------------------------------------------
    def _inverse_ocp_init(self, df: pd.DataFrame) -> dict:
        """
        由实测起始（静置）电压反解工作电极初始嵌锂量 x0。

        与平台 Birmingham 适配器同一方法：inverse-OCP on the
        parameter set's working-electrode OCP curve。
        x0 不是拟合参数；LFP 等平台区会弱定，已在报告里提示。
        """
        import numpy as np
        from scipy.optimize import brentq

        from battery_sim.models.pybamm_factory import load_parameter_values

        we = str(self.exp.get("working_electrode", "") or "positive")
        key = f"{we.capitalize()} electrode OCP [V]"
        conc_key = f"Initial concentration in {we} electrode [mol.m-3]"
        max_key = f"Maximum concentration in {we} electrode [mol.m-3]"

        pv = load_parameter_values(str(self.gate["parameter_set"]))
        ocp = pv[key]

        v0 = float(df["voltage_V"].dropna().iloc[0])

        def eval_ocp(x: float) -> float:
            """
            通用 OCP 求值：
              * 内置参数集（Chen2020 / Prada2013 ...）返回 numpy 数组
              * 外部作者参数集（Jackowska2025）返回 pybamm 符号，
                需要 .evaluate()
            """
            r = ocp(np.array([x]))
            if hasattr(r, "evaluate"):
                return float(np.ravel(r.evaluate())[0])
            return float(np.ravel(r)[0])

        xs = np.linspace(1e-4, 0.9999, 2000)
        us = np.array([eval_ocp(float(x)) for x in xs])

        # OCP 单调下降 -> 用 brentq 求根
        if us[0] > us[-1]:
            f = lambda x: eval_ocp(x) - v0
        else:
            f = lambda x: v0 - eval_ocp(x)
        try:
            x0 = float(brentq(f, 1e-4, 0.9999))
        except ValueError:
            x0 = float(xs[np.argmin(np.abs(us - v0))])

        # 条件数：|dU/dx| 越小，x0 越不确定
        slope = float(np.gradient(us, xs)[np.argmin(np.abs(us - v0))])

        self.x0_conditioning = {
            "v0_V": v0,
            "x0": x0,
            "dUdx_V_per_sto": slope,
            "status": (
                "weakly_determined_from_voltage"
                if abs(slope) < 0.05
                else "determined_from_voltage"
            ),
        }

        return {
            "method": "fixed_initial_concentration",
            "ocp_voltage_V": v0,
            "stoichiometry_from_ocp": x0,
            "concentration_parameter": conc_key,
            "max_concentration_parameter": max_key,
            "mapping_reason": (
                "user_tools: inverse-OCP(measured start voltage) -> x0. "
                "Not fitted. "
                + (
                    "weakly determined (flat OCP plateau)"
                    if abs(slope) < 0.05
                    else ""
                )
            ),
        }

    # ------------------------------------------------------------------
    # Adapter interface
    # ------------------------------------------------------------------
    def get_metadata(self) -> dict:
        return {
            "dataset_id": self.dataset_id,
            "name": self.config.name,
            "chemistry": self.config.chemistry,
            "sample_id": self.exp.get("sample_id", ""),
            "cell_configuration": self.exp.get("cell_configuration", ""),
            "parameter_match": self.gate,
            "source": "user_tools generic importer",
        }

    def list_cells(self) -> List[str]:
        return list(self.config.cells)

    def list_rates(self) -> List[str]:
        return ["as_provided"]

    def rate_info(self, rate) -> Dict[str, object]:
        """用户协议没有 C-rate 语义：如实标注，不反推。"""
        df = self._load()
        I = df["current_A"].to_numpy(dtype=float)
        imax = float(np.nanmax(np.abs(I))) if len(I) else 0.0
        nom = self.exp.get("nominal_capacity", None)
        c_rate = 0.0
        label = "C-rate unknown (nominal capacity not provided)"
        if nom:
            try:
                c_rate = imax / float(nom)
                label = f"~{c_rate:.2f} C (from max|I| / declared nominal capacity)"
            except (TypeError, ValueError, ZeroDivisionError):
                pass
        return {
            "c_rate": float(c_rate),
            "rate_label": label,
            "rate_slug": "as_provided",
            "source_rate": "user_provided",
            "legacy_rate": "as_provided",
        }

    def load_raw(self, cell) -> pd.DataFrame:
        return self._load()

    def load_discharge(self, cell, rate) -> pd.DataFrame:
        return self._load()

    def load_processed_discharge(self, cell: str, rate: str) -> pd.DataFrame:
        return self._load()

    def get_initial_state(self, cell) -> float:
        df = self._load()
        return float(df["voltage_V"].dropna().iloc[0])

    def get_ambient_temperature(self, cell) -> float:
        return float(self._ambient_C)

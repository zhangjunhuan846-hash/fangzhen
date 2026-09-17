# ============================================================
# Self-Service Data Onboarding Layer -- 常量与规则层
#
# 这一层只放"规则"，不放任何科学计算。
# 所有单位换算、允许取值、参数集支持表都写死在这里，
# 便于审计：改规则 = 改这一个文件。
#
# 平台约定（不得改动）：
#   canonical 电流符号：放电 = 正 (discharge = +)
#   canonical 列名：time_s / current_A / voltage_V / capacity_Ah /
#                   cell_temperature_C
#
# 禁止自动猜：chemistry / current sign / units / full-cell/half-cell /
#             parameter set / dataset_role。
#             必须由用户在 dataset_info.xlsx 中显式声明。
# ============================================================

from __future__ import annotations

from governance.dataset_roles import ALLOWED_DECLARED_ROLES

# ------------------------------------------------------------------
# canonical 字段（用户在 column_mapping 里填的就是这些）
# ------------------------------------------------------------------
CANONICAL_FIELDS = [
    "time",
    "current",
    "voltage",
    "capacity",
    "cycle",
    "step",
    "temperature",
]

REQUIRED_FIELDS = ["time", "current", "voltage"]  # 最低必填
OPTIONAL_FIELDS = ["capacity", "cycle", "step", "temperature"]

FIELD_LABEL_ZH = {
    "time": "时间",
    "current": "电流",
    "voltage": "电压",
    "capacity": "容量",
    "cycle": "循环号",
    "step": "工步号",
    "temperature": "温度",
}

# ------------------------------------------------------------------
# 单位换算：source_unit -> (canonical 乘数, canonical 偏移)
#   值_canonical = 值_原始 * factor + offset
# ------------------------------------------------------------------
_UNIT_LINEAR = {
    "time": {"s": 1.0, "sec": 1.0, "min": 60.0, "h": 3600.0, "hour": 3600.0, "ms": 1e-3},
    "current": {"a": 1.0, "ma": 1e-3, "ua": 1e-6, "\u00b5a": 1e-6},
    "voltage": {"v": 1.0, "mv": 1e-3},
    "capacity": {"ah": 1.0, "mah": 1e-3},
    "cycle": {"-": 1.0, "1": 1.0, "": 1.0},
    "step": {"-": 1.0, "1": 1.0, "": 1.0},
    "temperature": {"c": 1.0, "k": 1.0, "f": 1.0},
}

_UNIT_OFFSET = {
    "temperature": {"c": 0.0, "k": -273.15, "f": 0.0},
}
_TEMPERATURE_FAHRENHEIT_SCALE = 5.0 / 9.0

ALLOWED_UNITS = {
    f: sorted({k for k in v.keys() if k != ""})
    for f, v in _UNIT_LINEAR.items()
}


def unit_factor_offset(field: str, unit: str) -> tuple[float, float]:
    """返回 (factor, offset)；未知单位直接抛错（禁止猜）。"""
    f = str(field).strip().lower()
    u = str(unit).strip().lower()
    if f not in _UNIT_LINEAR:
        raise ValueError(f"未知 canonical 字段 '{field}'")
    table = _UNIT_LINEAR[f]
    if u not in table:
        raise ValueError(
            f"字段 '{field}' 的单位 '{unit}' 不支持。"
            f"允许：{ALLOWED_UNITS[f]}"
        )
    factor = float(table[u])
    offset = float(_UNIT_OFFSET.get(f, {}).get(u, 0.0))
    if f == "temperature" and u == "f":
        factor = _TEMPERATURE_FAHRENHEIT_SCALE
        offset = -32.0 * _TEMPERATURE_FAHRENHEIT_SCALE
    return factor, offset


# ------------------------------------------------------------------
# experiment sheet 允许取值（Excel 下拉来源）
# ------------------------------------------------------------------
ALLOWED_CHEMISTRY = ["LFP", "NMC", "LCO", "other"]
ALLOWED_CELL_CONFIGURATION = ["full_cell", "half_cell"]
ALLOWED_WORKING_ELECTRODE = ["positive", "negative", ""]
# 工作电极**材料**（不是槽位）。它只为一件事存在：把"这个体系该用哪个电压
# 窗口"从数据里 anchor 住（见 battery_sim/datasets/chemistry_windows.py）。
# `chemistry` 那一栏在平台里装的是**正极**化学体系，装不下"负极是石墨"，
# 而半电池的窗口恰恰由工作电极决定。留空 = 无法锚定 = 该项检查跳过（不猜）。
ALLOWED_WORKING_ELECTRODE_MATERIAL = [
    "graphite",
    "nmc",
    "lfp",
    "lco",
    "lithium_metal",
    "silicon_c",
    "other",
    "",
]
ALLOWED_COUNTER_ELECTRODE = ["lithium_metal", "graphite", "other", ""]
ALLOWED_CURRENT_SIGN = ["discharge_positive", "discharge_negative"]
# 协议类型（**闭集**）。它决定 QC 的严厉程度：
#   脉冲型协议（GITT / PITT）里，采样间断会把脉冲时长与弛豫完整度算错，
#   而 D_s 直接由脉冲时长与 ΔV 决定 —— 所以那里间断是 FAIL，不是 WARN。
# 自由文本的 `protocol` 字段保留（仪器档位名要原样留住），
# 但它**不参与**分级；分级只认 `protocol_type`（或它的可识别写法）。
ALLOWED_PROTOCOL_TYPE = [
    "GCD",
    "GITT",
    "PITT",
    "pOCV",
    "rate_capability",
    "cycle_life",
    "EIS",
    "other",
    "",
]
#: 脉冲型协议：这些协议下采样间断/脉冲时长不一致会直接污染参数
PULSE_PROTOCOL_TYPES = ("GITT", "PITT")
# 用途声明：identification / validation / benchmark / prediction
# （词表与规则在 governance/dataset_roles.py，这里只引用，不复制）
ALLOWED_DATASET_ROLE = list(ALLOWED_DECLARED_ROLES)

EXPERIMENT_FIELDS = [
    # (字段名, 中文标签, 必填, 允许值 or None)
    ("dataset_name", "数据集名称", True, None),
    ("sample_id", "样品编号", True, None),
    ("chemistry", "正极化学体系", True, ALLOWED_CHEMISTRY),
    # 必填与否：留空按 identification 处理，但每次调用都会返回警告
    # 并要求写进 provenance（不静默）——见 governance/dataset_roles.py
    ("dataset_role", "数据用途", False, ALLOWED_DATASET_ROLE),
    ("cell_configuration", "电池构型", True, ALLOWED_CELL_CONFIGURATION),
    ("working_electrode", "工作电极", False, ALLOWED_WORKING_ELECTRODE),
    ("working_electrode_material", "工作电极材料", False,
     ALLOWED_WORKING_ELECTRODE_MATERIAL),
    ("counter_electrode", "对电极", False, ALLOWED_COUNTER_ELECTRODE),
    ("nominal_capacity", "标称容量 [Ah]", False, None),
    ("active_material_loading", "面容量 [mAh/cm2]", False, None),
    ("electrode_area", "极片面积 [cm2]", False, None),
    ("electrolyte", "电解液", False, None),
    ("voltage_lower", "下限电压 [V]", True, None),
    ("voltage_upper", "上限电压 [V]", True, None),
    ("temperature", "环境温度 [C]", False, None),
    ("protocol", "测试protocol（原始档位名）", False, None),
    ("protocol_type", "协议类型（闭集）", False, ALLOWED_PROTOCOL_TYPE),
    ("pulse_duration_s", "GITT 脉冲时长 [s]", False, None),
    ("relax_duration_s", "GITT 静置时长 [s]", False, None),
    ("current_sign", "原始电流符号", True, ALLOWED_CURRENT_SIGN),
    ("initial_soc", "初始 SOC (0-1, 可选)", False, None),
]

REQUIRED_EXPERIMENT_FIELDS = [f for f, _, req, _ in EXPERIMENT_FIELDS if req]
NUMERIC_EXPERIMENT_FIELDS = {
    "nominal_capacity",
    "active_material_loading",
    "electrode_area",
    "voltage_lower",
    "voltage_upper",
    "temperature",
    "initial_soc",
    "pulse_duration_s",
    "relax_duration_s",
}

#: 自由文本 protocol 里可识别的脉冲协议写法（只用于**补齐**未填的
#: protocol_type；识别不到就保持空，绝不硬猜成 GITT）
_PULSE_TEXT_TOKENS = ("gitt", "pitt", "pulse", "脉冲")
_GCD_TEXT_TOKENS = ("gcd", "cc_cv", "cccv", "恒流", "充放电")


def protocol_type_of(exp: dict) -> str:
    """取协议类型（闭集内），**优先显式声明**。

    * ``protocol_type`` 填了 -> 原样规整返回（不在闭集内则原样返回，
      由调用方报错；本函数不静默改写）。
    * 没填 -> 只在自由文本 ``protocol`` 里找**无歧义的**脉冲协议写法
      （gitt / pitt / pulse / 脉冲）。找不到就返回 ``""`` = 未知。
      识别不到时**不许**默认成 GITT：这会让一份普通 GCD 也走脉冲级判据。
    """
    raw = str(exp.get("protocol_type", "") or "").strip()
    if raw:
        for allowed in ALLOWED_PROTOCOL_TYPE:
            if allowed and raw.lower() == allowed.lower():
                return allowed
        return raw

    text = str(exp.get("protocol", "") or "").strip().lower()
    if not text:
        return ""
    if any(tok in text for tok in _PULSE_TEXT_TOKENS):
        return "GITT" if "pitt" not in text else "PITT"
    if any(tok in text for tok in _GCD_TEXT_TOKENS):
        return "GCD"
    return ""


def is_pulse_protocol(protocol_type: str) -> bool:
    """该协议是否属于"时间结构会被采样质量直接毁掉"的一类。"""
    return str(protocol_type).strip().upper() in PULSE_PROTOCOL_TYPES

# ------------------------------------------------------------------
# S6 参数集兼容支持表
#
# 只有下面三类"声明组合"有对应参数集。
# 其余一律 SIMULATION = NOT AVAILABLE。
# 禁止为了能跑而偷偷换一个参数集。
# ------------------------------------------------------------------
JACKOWSKA_AREAL_CAPACITY = 2.0        # mAh/cm2（该参数集标定的电极设计）
JACKOWSKA_LOADING_TOL = 0.2           # mAh/cm2

PARAMETER_SUPPORT = {
    ("LFP", "full_cell"): {
        "parameter_set": "Prada2013",
        "level": "compatible_surrogate",
        "grade": "B",
        "available": True,
        "reason": (
            "LFP/石墨全电池：PyBaMM 中唯一可用的 LFP/石墨参数集。"
            "化学体系兼容，但不是用你的电池标定的。"
        ),
    },
    ("NMC", "full_cell"): {
        "parameter_set": "Chen2020",
        "level": "compatible_surrogate",
        "grade": "B",
        "available": True,
        "reason": (
            "NMC/石墨全电池：Chen2020（LG M50 NMC811/石墨）。"
            "化学体系兼容，但容量/几何与你的电池不同。"
        ),
    },
}


def parameter_gate(exp: dict) -> dict:
    """
    S6 参数兼容门。

    输入：experiment sheet 字典。
    输出：{"available": bool, "parameter_set": str|None,
           "level": str, "grade": str, "fitted_to_dataset": bool,
           "reason": str, "blockers": [str]}

    所有用户数据默认 fitted_to_dataset = false。
    没有合理参数集 -> available=False（DATA IMPORT 仍 PASS）。
    """
    chem = str(exp.get("chemistry", "")).strip()
    cfg = str(exp.get("cell_configuration", "")).strip()
    we = str(exp.get("working_electrode", "")).strip()
    ce = str(exp.get("counter_electrode", "")).strip()
    loading = exp.get("active_material_loading", None)

    out = {
        "available": False,
        "parameter_set": None,
        "level": "not_available",
        "grade": "n/a",
        "provenance": {
            "provenance": "not_available",
            "electrode_design": "",
            "fitted_to_user_dataset": False,
            "executable_reproduction": "none",
        },
        "fitted_to_dataset": False,
        "reason": "",
        "blockers": [],
    }

    # --- NMC 正半电池：只有电极设计真正匹配时才给 Jackowska2025 ---
    if cfg == "half_cell":
        if chem == "NMC" and we == "positive" and ce == "lithium_metal":
            if loading is None:
                out["blockers"].append(
                    "NMC 正半电池需要填写 active_material_loading"
                    "（面容量 mAh/cm2）才能判断电极设计是否匹配。"
                )
                out["reason"] = (
                    "Jackowska2025 参数集是针对 2 mAh/cm2 的 NCM 电极标定的；"
                    "缺少面容量无法判断是否匹配，因此不提供仿真。"
                )
                return out
            try:
                load_v = float(loading)
            except (TypeError, ValueError):
                out["blockers"].append(
                    f"active_material_loading 不是数字：{loading!r}"
                )
                return out
            if abs(load_v - JACKOWSKA_AREAL_CAPACITY) <= JACKOWSKA_LOADING_TOL:
                out.update(
                    available=True,
                    parameter_set="Jackowska2025_2mAh_cm2",
                    level="design_matched_surrogate",
                    grade="B",
                    provenance={
                        # 结构化溯源：不用 A/B/C 之外的新等级。
                        # Birmingham = 参数集作者自己的实验数据（matched_study），
                        # 电极设计尺度与参数集标定一致；但不是用"用户本次批次"标定的。
                        "provenance": "matched_study",
                        "electrode_design": "matched_2mAh_cm2",
                        "fitted_to_user_dataset": False,
                        "executable_reproduction": "partial",
                    },
                    reason=(
                        f"电极设计尺度匹配（面容量 {load_v:g} mAh/cm2，"
                        f"参数集标定值 {JACKOWSKA_AREAL_CAPACITY:g}"
                        f" +/-{JACKOWSKA_LOADING_TOL:g}）。"
                        "此数据源即参数集作者研究的同一电极体系（matched_study），"
                        "但仍不是用你的材料/批次标定的，"
                        "结果只能作为 zero-fit baseline，不能作为模型验证。"
                    ),
                )
            else:
                out["blockers"].append(
                    f"面容量 {load_v:g} mAh/cm2 与参数集标定设计 "
                    f"{JACKOWSKA_AREAL_CAPACITY:g} mAh/cm2 差异超过 "
                    f"+/-{JACKOWSKA_LOADING_TOL:g} mAh/cm2。"
                )
                out["reason"] = (
                    "Jackowska2025 只适用于 2 mAh/cm2 的 NCM 正半电池设计；"
                    "你的电极设计不同，套用会构成容量/几何失配，"
                    "因此不提供仿真（而不是换一个不匹配的参数集来跑）。"
                )
            return out

        out["reason"] = (
            f"当前支持表不覆盖该半电池组合"
            f"（chemistry={chem or '空'}, working_electrode={we or '空'}, "
            f"counter_electrode={ce or '空'}）。仅支持 NMC 正半电池"
            "（工作电极=positive，对电极=锂金属）。"
        )
        out["blockers"].append("半电池构型不在支持表内")
        return out

    # --- 全电池 ---
    if cfg == "full_cell":
        key = (chem, "full_cell")
        if key in PARAMETER_SUPPORT:
            e = PARAMETER_SUPPORT[key]
            out.update(
                available=True,
                parameter_set=e["parameter_set"],
                level=e["level"],
                grade=e["grade"],
                provenance={
                    "provenance": "compatible_surrogate",
                    "electrode_design": "not_matched_to_user_electrode",
                    "fitted_to_user_dataset": False,
                    "executable_reproduction": "not_expected",
                },
                reason=e["reason"]
                + " fitted_to_dataset=false：未用你的数据做任何标定。",
            )
        else:
            out["reason"] = (
                f"当前支持表不覆盖 chemistry='{chem or '空'}' 的全电池。"
                "支持：LFP 全电池 -> Prada2013；NMC 全电池 -> Chen2020。"
            )
            out["blockers"].append(f"chemistry '{chem or '空'}' 无对应参数集")
        return out

    out["reason"] = f"cell_configuration='{cfg or '空'}' 无法识别。"
    out["blockers"].append("cell_configuration 缺失或非法")
    return out


# ------------------------------------------------------------------
# 输出文件名（S4）
# ------------------------------------------------------------------
OUT_VALIDATION_REPORT = "validation_report.html"
OUT_ISSUES = "issues.csv"
OUT_CANONICAL_PREVIEW = "canonical_preview.csv"
OUT_PREVIEW_PNG = "voltage_capacity_preview.png"
OUT_MANIFEST = "dataset_manifest.json"
OUT_CANONICAL_FULL = "canonical_data.csv"

CANONICAL_COLUMNS = [
    "time_s",
    "current_A",
    "voltage_V",
    "capacity_Ah",
    "cycle",
    "step",
    "cell_temperature_C",
    "sample_id",
    "protocol_id",
]

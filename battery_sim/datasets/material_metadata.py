# ============================================================
# 材料元数据契约（material_metadata）
#
# 为什么单独有这一层
#   回收石墨 case 的第一个科学问题是"再生过程改没改可辨识的动力学参数"。
#   要回答它，模型侧需要的**不是**数据文件本身，而是一组电极/颗粒的实测量
#   （载量、涂层厚度、粒径……）。这些量不在任何仪器导出里，只在人手里。
#   如果它们以"备注"的形式散在聊天记录里，那么半年后没人能复算这项分析。
#
#   所以把这份输入做成**声明式契约**：缺哪个字段就报哪个字段，
#   而不是让分析在缺少几何的情况下"跑出来一个数"。
#
# 与平台的接口
#   · canonical 四列是**电化学**输入；本文件是**材料**输入，二者互补
#   · 几何量（面积/厚度/载量/粒径）直接影响 D_s 的尺度：
#     D ∝ R²，粒径被读错 2 倍 = 扩散系数差 4 倍（见 docs/scale_alignment_gate.md）
#   · 参数来源用固定词表（PARAMETER_SOURCE_VOCAB），论文里逐条可查
# ============================================================

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

#: 逗号分隔的点路径；子路径取值必须是数字（除注明外）
REQUIRED_FIELDS = (
    "sample_id",
    "material_class",
    "source",
    "electrode.mass_loading_mg_cm2",
    "electrode.coating_thickness_um",
    "electrode.area_cm2",
    "particle.d50_um",
    "cell.counter_electrode",
    "cell.electrolyte",
)

#: 条件必填：material_class 落在这些值上时，必须写 regeneration_condition
REGENERATION_REQUIRED_FOR = ("recycled", "regenerated")

MATERIAL_CLASSES = (
    "pristine", "recycled", "regenerated", "reference", "unknown",
)

#: 电化学测了什么。判据只有一条：**没测过的量不许写结论。**
TECHNIQUE_VOCAB = (
    "GITT", "pOCV", "CC_charge_discharge", "rate_capability", "EIS", "cycling",
)

#: 参数来源词表。审稿人问"这个参数怎么来的"，答案必须落在这几个词里，
#: 不许写"拟合得到"这种无法归因的说法。
PARAMETER_SOURCE_VOCAB = (
    "gitt_fitting",         # 从 GITT 瞬态反演
    "eis_fitting",          # 从 EIS 拟合
    "ocv_derived",          # 从准平衡曲线派生（如 OCP 双支）
    "literature_prior",     # 文献值，非本数据集
    "inferred",             # 由其它量推算（如 R_p²/D_s 这类派生量）
    "parameter_set_default", # 参数集默认值，本轮未改
    "user_override",        # 调用方在运行时显式覆盖
    "not_measured",         # 本轮没有证据
)

#: 每个参数的"下限证据"：连这些都没测，就不该出现该参数的判定
PARAMETER_EVIDENCE = {
    "Ds": ("GITT",),
    "k0": ("EIS",),
    "Rct": ("EIS",),
}

FIELD_HELP = {
    "sample_id": "样品编号（同一批料的不同处理各一个）",
    "material_class": f"材料类别，取值 {list(MATERIAL_CLASSES)}",
    "source": "这份样品/数据从哪来（本实验室哪一批、谁做的、日期）",
    "regeneration_condition": "再生/处理条件（温度、气氛、时长）；pristine 可不填",
    "electrode.mass_loading_mg_cm2": "活性物质载量 (mg/cm²)",
    "electrode.coating_thickness_um": "涂层厚度 (µm)，实测不是标称",
    "electrode.area_cm2": "电极几何面积 (cm²)",
    "particle.d50_um": "粒径中位 D50 (µm)。D ∝ R²，这个数错一倍 = D_s 错 4 倍",
    "cell.counter_electrode": "对电极（Li 片？规格与厚度）",
    "cell.electrolyte": "电解液（配方、浓度、添加剂）",
    "measurements": "测了哪些电化学（technique + file），technique 取 TECHNIQUE_VOCAB",
}


class MaterialMetadataError(ValueError):
    """元数据不满足契约。消息里逐条列出缺什么。"""


def _dig(meta: Dict[str, Any], path: str) -> Any:
    node: Any = meta
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def missing_fields(meta: Dict[str, Any]) -> List[str]:
    """列出缺的字段（含条件必填），按契约顺序。"""
    missing = []
    for path in REQUIRED_FIELDS:
        value = _dig(meta, path)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(path)
    if str(_dig(meta, "material_class") or "").strip() in REGENERATION_REQUIRED_FOR:
        # 结构化回收史（recycling.treatment）填了的话，regeneration_condition
        # 就是一个重复字段：**二选一即可**（结构化那份才是机器可读的）。
        treatment = _dig(meta, "recycling.treatment") or {}
        has_block = isinstance(treatment, dict) and any(
            _filled(v) for v in treatment.values())
        value = _dig(meta, "regeneration_condition")
        if not has_block and (value is None
                              or (isinstance(value, str)
                                  and not value.strip())):
            missing.append("regeneration_condition")
    if not _dig(meta, "measurements"):
        missing.append("measurements")
    return missing


def load_metadata(path) -> Dict[str, Any]:
    """读一份材料元数据 yaml。文件不存在就直说。"""
    import yaml

    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(
            f"材料元数据文件不存在：{p}\n"
            f"  从 templates/recycled_graphite/metadata.example.yaml 复制一份再填。"
        )
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise MaterialMetadataError(f"{p} 顶层必须是一个 mapping")
    return data


#: pybamm 无关；这些名字同时是**单位声明**（`_nm` / `_m2_g` / `_cm3_g` / `_cm1`）
STRUCTURE_BLOCKS = ("xrd", "raman", "bet")

#: 每个块的**白名单**。多一个键就是越界 —— 见下面 WHY WHITELIST。
STRUCTURE_FIELDS = {
    "xrd": ("available", "file", "role", "wavelength_nm", "d002_nm",
            "lc_nm", "la_nm", "crystallite_method", "source",
            "not_available_reason"),
    "raman": ("available", "file", "role", "laser_wavelength_nm", "id_ig",
              "g_band_cm1", "d_band_cm1", "source", "not_available_reason"),
    "bet": ("available", "file", "role", "adsorption_gas",
            "surface_area_m2_g", "pore_volume_cm3_g", "pore_size_distribution",
            "model", "source", "not_available_reason"),
}

#: `available: true` 时必须给的字段（其余为可选）
STRUCTURE_REQUIRED = {
    "xrd": ("file", "role", "wavelength_nm", "d002_nm", "source"),
    "raman": ("file", "role", "laser_wavelength_nm", "id_ig", "source"),
    "bet": ("file", "role", "adsorption_gas", "surface_area_m2_g",
            "pore_volume_cm3_g", "source"),
}

#: 必须为正数的字段（单位写在名字里）
STRUCTURE_POSITIVE = (
    "wavelength_nm", "d002_nm", "lc_nm", "la_nm", "laser_wavelength_nm",
    "id_ig", "g_band_cm1", "d_band_cm1", "surface_area_m2_g",
    "pore_volume_cm3_g",
)

#: 结构表征的来源词表（与测量清单同一套口径）
SOURCE_TYPES = ("experiment", "literature", "vendor", "estimate")

#: 已知的"解释性"键名：写进来就直接报错，并给出该写什么
INTERPRETATION_KEYS = {
    "defect_level": "写 `id_ig`（测量量）；缺陷程度的判断放在分析层",
    "quality": "写具体测量量（`d002_nm` / `id_ig` / `surface_area_m2_g`）",
    "graphitization": "写 `d002_nm` 与 `lc_nm`；「石墨化程度」是解释",
    "crystallinity": "写 `d002_nm` / `lc_nm` / `crystallite_method`",
    "activation": "写 `surface_area_m2_g` 与 `pore_volume_cm3_g`",
    "capacity_fade": "那是电化学派生量，不属于结构表征",
}

#: 数值合理区间（只 warn，不判死）：超范围通常是单位或测错
STRUCTURE_PLAUSIBLE = {
    "d002_nm": (0.20, 1.00),        # 石墨 d002 ≈ 0.336 nm
    "id_ig": (0.05, 20.0),
    "surface_area_m2_g": (0.01, 5000.0),
}


def _filled(value: Any) -> bool:
    """"填了没有"的判定：``None`` / 空串 / 空 dict / **全为 null 的 dict** 都算没填。

    最后一条是为了模板：``source: {type: null, instrument: null, ...}``
    是"还没填"的形态，不该被读成"填了一个空来源"。
    """
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(_filled(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_filled(v) for v in value)
    return True


# ---------------------------------------------------------------
# 回收史（recycling provenance）
#
# 为什么它对回收材料是**必填**而不是"最好有"
#   回收材料最大的问题不是测量误差，而是**样品身份不可追踪**：
#   两个都叫"再生石墨"的样品，一个是酸浸 + 600 °C Ar、一个是碱处理 + 900 °C
#   Ar/H2 —— 根本不是同一个材料。缺了这段历史，D_s 的任何差异都无法归因，
#   而"再生石墨"这个词本身会被当成一个材料类别来用。
#
#   所以 material_class ∈ {recycled, regenerated} 时，这一块**必须**给出
#   （来源三问 + 处理四问）。pristine 的参照样品可以不填。
# ---------------------------------------------------------------
RECYCLING_REQUIRED_FOR = ("recycled", "regenerated")

RECYCLING_SOURCE_FIELDS = ("battery_type", "cathode_type", "graphite_origin")
RECYCLING_TREATMENT_FIELDS = ("method", "temperature_C", "duration_h",
                              "atmosphere")

#: 氧化性气氛 + 高温 = 石墨会被烧掉。只 warn：先让人确认气氛写法与单位，
#: 不直接判死（"air" 也可能是实验室内部的缩写）。
OXIDATIVE_HINTS = ("air", "o2", "oxygen", "空气", "氧")
OXIDATIVE_ALERT_ABOVE_C = 500.0


# ---------------------------------------------------------------
# 通用工艺史（process history）
#
# 为什么不能复用 recycling
#   recycling 回答的是"这个材料从哪来"（退役电池 → 再生），它的必填性挂在
#   material_class 上。而"对它做了什么"是**另一个维度**：热处理梯度实验里
#   600/800/900 °C 就是**自变量本身**，与材料是不是回收料无关。
#   把两者挤进一个块，会让"未回收但被热处理"的样品无处记录工艺 ——
#   而这批样品的全部结论都由工艺决定。
#
# 形状刻意与 structure 块同构（applied / not_applied_reason）：
#   · applied: true  → 方法/温度/时长/气氛四项必填，键是**闭集**
#   · applied: false → 必须写 not_applied_reason
#   「没处理」与「忘了写」在下游完全一样，所以两种都要有说法。
#
# 逐份文件里它是**可选**的（单份接入不被卡住）；但一条梯度里它是**必须**的，
# 由 validate_series 强制 —— 否则「600」与「800」只差 sample_id 里一个字符串。
# ---------------------------------------------------------------
PROCESSING_REQUIRED_FIELDS = ("method", "temperature_C", "duration_h",
                              "atmosphere")

#: 可选、但必须**按名字**写。加键要改这里：闭集是有意的，自由键会让
#: "这批样品到底怎么处理的"半年后无法回答。
PROCESSING_OPTIONAL_FIELDS = (
    "ramp_rate_C_per_min",    # 升温速率：决定实际热历史，不只是峰值温度
    "cooling",                # 降温方式（炉冷 / 随炉 / 快冷）
    "atmosphere_flow_sccm",   # 气氛流量
    "crucible",               # 坩埚与装样方式
    "mass_before_mg",         # 处理前质量
    "mass_after_mg",          # 处理后质量 → 失重率（去除 SEI/官能团的第一手证据）
    "batch",                  # 同炉次（同炉样品共享热历史）
    "notes",
)

PROCESSING_FIELDS = (("applied", "not_applied_reason")
                     + PROCESSING_REQUIRED_FIELDS
                     + PROCESSING_OPTIONAL_FIELDS)

#: 必须为正的数值字段
PROCESSING_POSITIVE = ("temperature_C", "duration_h", "ramp_rate_C_per_min",
                       "atmosphere_flow_sccm", "mass_before_mg",
                       "mass_after_mg")

PROCESSING_FIELD_HELP = {
    "method": "处理方法（例：管式炉热处理 / 真空干燥 / 酸洗）",
    "temperature_C": "处理温度（°C）；氧化性气氛下高温会烧损石墨",
    "duration_H": "保温时长（h）",
    "duration_h": "保温时长（h）",
    "atmosphere": "气氛（例：Ar / N2 / Ar-H2 / 真空）—— 它常常比温度更决定结论",
    "ramp_rate_C_per_min": "升温速率（°C/min）",
    "cooling": "降温方式（炉冷 / 随炉 / 快冷）",
    "atmosphere_flow_sccm": "气氛流量（sccm）",
    "crucible": "坩埚 / 装样方式",
    "mass_before_mg": "处理前质量（mg）",
    "mass_after_mg": "处理后质量（mg）",
    "batch": "同炉次编号（同炉样品共享热历史）",
}


def _oxidative_warning(temperature: float, atmosphere: str,
                       where: str) -> Optional[str]:
    """氧化性气氛 + 高温 = 石墨会被烧掉。返回警告文本，或 None。

    只 warn 不判死：气氛写法可能是实验室内部的缩写，先让人确认写法与单位，
    再让他解释容量损失。
    """
    if temperature > OXIDATIVE_ALERT_ABOVE_C and any(
            h in str(atmosphere).lower() for h in OXIDATIVE_HINTS):
        return (
            f"{where}: 处理气氛写作 '{atmosphere}' 且温度 {temperature} °C —— "
            f"石墨在氧化性气氛下 >{OXIDATIVE_ALERT_ABOVE_C:g} °C 会烧损，"
            f"先确认气氛写法（Ar / N2 / 真空？）再解释容量损失"
        )
    return None


def validate_recycling(meta: Dict[str, Any]) -> Dict[str, List[str]]:
    """校验 ``recycling:`` 块。返回 ``{errors, warnings, missing}``。"""
    errors: List[str] = []
    warnings: List[str] = []
    missing: List[str] = []

    cls = str(meta.get("material_class") or "").strip()
    raw = meta.get("recycling")
    required = cls in RECYCLING_REQUIRED_FOR

    if raw is None:
        if required:
            errors.append(
                f"material_class='{cls}' 必须给 recycling 块"
                f"（source: {'/'.join(RECYCLING_SOURCE_FIELDS)}；"
                f"treatment: {'/'.join(RECYCLING_TREATMENT_FIELDS)}）——"
                f"缺了它，两个「再生石墨」无法区分是不是同一个材料"
            )
            missing.extend(f"recycling.{p}" for p in
                           ("source", "treatment"))
        return {"errors": errors, "warnings": warnings, "missing": missing}
    if not isinstance(raw, dict):
        errors.append("recycling 必须是 mapping（source / treatment）")
        return {"errors": errors, "warnings": warnings, "missing": missing}

    source = raw.get("source")
    treatment = raw.get("treatment")
    if not isinstance(source, dict):
        errors.append("recycling.source 必须是 mapping")
        source = {}
    if not isinstance(treatment, dict):
        errors.append("recycling.treatment 必须是 mapping")
        treatment = {}

    for group, fields in (("source", RECYCLING_SOURCE_FIELDS),
                          ("treatment", RECYCLING_TREATMENT_FIELDS)):
        for field in fields:
            value = (source if group == "source" else treatment).get(field)
            if not _filled(value):
                missing.append(f"recycling.{group}.{field}")
                errors.append(
                    f"recycling.{group}.{field} 必填"
                    f"（{RECYCLING_FIELD_HELP[field]}）"
                )

    if _filled(treatment.get("temperature_C")):
        try:
            temp = float(treatment["temperature_C"])
            if temp < 0:
                errors.append(f"recycling.treatment.temperature_C = {temp} 为负")
            else:
                warn = _oxidative_warning(
                    temp, str(treatment.get("atmosphere") or ""),
                    "recycling.treatment",
                )
                if warn:
                    warnings.append(warn)
        except (TypeError, ValueError):
            errors.append(
                f"recycling.treatment.temperature_C = "
                f"{treatment['temperature_C']!r} 不是数字"
            )

    if _filled(treatment.get("duration_h")):
        try:
            if float(treatment["duration_h"]) <= 0:
                errors.append("recycling.treatment.duration_h 必须为正")
        except (TypeError, ValueError):
            errors.append(
                f"recycling.treatment.duration_h = "
                f"{treatment['duration_h']!r} 不是数字"
            )

    return {"errors": errors, "warnings": warnings, "missing": missing}


def validate_processing(meta: Dict[str, Any]) -> Dict[str, List[str]]:
    """校验 ``processing:`` 块。返回 ``{errors, warnings, pending}``。

    ``applied`` 是**必需**的：不写它就无法区分"没处理"与"忘了写"，
    而那正是这个块存在的理由。
    """
    errors: List[str] = []
    warnings: List[str] = []
    pending: List[str] = []

    raw = meta.get("processing")
    if raw is None:
        # 单份文件可以没有（由 validate_series 在梯度层面强制）
        return {"errors": errors, "warnings": warnings, "pending": pending}
    if not isinstance(raw, dict):
        errors.append("processing 必须是 mapping（applied / method / "
                      "temperature_C / duration_h / atmosphere / ...）")
        return {"errors": errors, "warnings": warnings, "pending": pending}

    unknown = [k for k in raw if k not in PROCESSING_FIELDS]
    if unknown:
        errors.append(
            f"processing 里有未知键 {unknown}；允许 {list(PROCESSING_FIELDS)}"
        )

    if "applied" not in raw:
        errors.append("processing.applied 必填（true/false）")
        return {"errors": errors, "warnings": warnings, "pending": pending}
    applied = raw["applied"]
    if not isinstance(applied, bool):
        errors.append(f"processing.applied 必须是布尔值，得到 {applied!r}")
        return {"errors": errors, "warnings": warnings, "pending": pending}

    if not applied:
        reason = str(raw.get("not_applied_reason") or "").strip()
        if not reason:
            errors.append(
                "processing.applied=false 必须写 not_applied_reason"
                "（为什么什么都没做 —— 「没处理」也要有说法）"
            )
        else:
            pending.append(f"processing: 未处理（{reason}）")
        for key in PROCESSING_REQUIRED_FIELDS + ("mass_before_mg",
                                                 "mass_after_mg"):
            if _filled(raw.get(key)):
                warnings.append(
                    f"processing.applied=false 却填了 {key} —— 自相矛盾"
                )
        return {"errors": errors, "warnings": warnings, "pending": pending}

    for key in PROCESSING_REQUIRED_FIELDS:
        if not _filled(raw.get(key)):
            errors.append(
                f"processing.{key} 必填（applied=true 就要给出完整工艺；"
                f"{PROCESSING_FIELD_HELP.get(key, '')}）"
            )

    for key in PROCESSING_POSITIVE:
        if key not in raw or raw[key] in (None, ""):
            continue
        try:
            num = float(raw[key])
        except (TypeError, ValueError):
            errors.append(f"processing.{key} = {raw[key]!r} 不是数字")
            continue
        if not num > 0:
            errors.append(f"processing.{key} = {num} 必须为正")

    if _filled(raw.get("temperature_C")) and _filled(raw.get("atmosphere")):
        try:
            warn = _oxidative_warning(
                float(raw["temperature_C"]), str(raw["atmosphere"]),
                "processing",
            )
            if warn:
                warnings.append(warn)
        except (TypeError, ValueError):
            pass

    before, after = raw.get("mass_before_mg"), raw.get("mass_after_mg")
    if _filled(before) and _filled(after):
        try:
            if float(after) > float(before):
                warnings.append(
                    f"processing: 处理后质量 {after} mg > 处理前 {before} mg "
                    f"—— 只可能来自称量误差或装样残留，确认一下"
                )
        except (TypeError, ValueError):
            pass

    return {"errors": errors, "warnings": warnings, "pending": pending}


def mass_loss_pct(meta: Dict[str, Any]) -> Optional[float]:
    """处理失重率 %（处理前/后质量都在时才有值）。除去的是 SEI、无定形碳、
    表面官能团 —— 这是"500 与 800 差在哪"最便宜的一条第一手证据。"""
    raw = meta.get("processing") or {}
    if not isinstance(raw, dict):
        return None
    try:
        before = float(raw["mass_before_mg"])
        after = float(raw["mass_after_mg"])
    except (KeyError, TypeError, ValueError):
        return None
    if before <= 0:
        return None
    return (before - after) / before * 100.0


def processing_summary(meta: Dict[str, Any]) -> str:
    """一行工艺摘要。没有 processing 块时**明说没有**，不留白。"""
    raw = meta.get("processing")
    if not isinstance(raw, dict):
        return "processing: 未声明（梯度实验里工艺是自变量，必须声明）"
    if raw.get("applied") is False:
        return f"processing: 未处理（{raw.get('not_applied_reason') or '无原因'}）"
    if raw.get("applied") is True:
        text = (f"{raw.get('method')} @ {raw.get('temperature_C')} °C"
                f" × {raw.get('duration_h')} h in {raw.get('atmosphere')}")
        loss = mass_loss_pct(meta)
        if loss is not None:
            text += f"；失重 {loss:.2f} %"
        ramp = raw.get("ramp_rate_C_per_min")
        if _filled(ramp):
            text += f"；升温 {ramp} °C/min"
        return "processing: " + text
    return "processing: 未声明 applied（true/false）"


def series_table(metas) -> str:
    """一行一样品的梯度表：sample_id | material_class | 工艺 | 失重。"""
    rows = []
    for meta in metas:
        loss = mass_loss_pct(meta)
        raw = meta.get("processing")
        if isinstance(raw, dict) and raw.get("applied") is True:
            treat = (f"{raw.get('method') or '?'} @ {raw.get('temperature_C')} °C"
                     f" × {raw.get('duration_h')} h"
                     f" in {raw.get('atmosphere') or '?'}")
        elif isinstance(raw, dict) and raw.get("applied") is False:
            treat = "未处理"
        else:
            treat = "工艺未声明"
        rows.append([
            str(meta.get("sample_id") or "?"),
            str(meta.get("material_class") or "?"),
            treat,
            "-" if loss is None else f"{loss:.2f} %",
        ])
    header = ["sample_id", "material_class", "processing", "mass_loss"]
    width = [max(len(header[i]), *(len(r[i]) for r in rows)) if rows
             else len(header[i]) for i in range(4)]
    out = ["  " + " | ".join(h.ljust(width[i]) for i, h in enumerate(header))]
    for row in rows:
        out.append("  " + " | ".join(v.ljust(width[i])
                                     for i, v in enumerate(row)))
    return "\n".join(out)


def validate_series(metas, *, require_processing: bool = True,
                    geometry_tolerance_pct: float = 10.0
                    ) -> Dict[str, List[str]]:
    """一组样品（同一条梯度）的**系列级**校验。

    每份文件各自合法 ≠ 它们构成一条可比较的梯度。这里查四件事：
      1. **sample_id 唯一** —— 不同处理必须是不同编号；
      2. **工艺史都声明了** —— 缺了它，「600」与「800」只差 sample_id 里
         一个字符串，样品身份不可追踪（与 recycling 块同一个理由）；
      3. **工艺至少有一样不同** —— 全都相同就不是梯度；同条件下的重复
         属于同一 sample 的多颗电芯，不该占两个 sample_id；
      4. **电极几何一致** —— 材料对比时电极差异会混进参数差异，
         结论只能退到「当前电极工艺下的综合差异」（phase1 方案 §3.2）。
    """
    metas = [m for m in metas if isinstance(m, dict)]
    errors: List[str] = []
    warnings: List[str] = []

    ids = [str(m.get("sample_id") or "") for m in metas]
    dup = sorted({i for i in ids if i and ids.count(i) > 1})
    if dup:
        errors.append(f"sample_id 重复：{dup} —— 不同处理的样品必须是不同编号")

    if require_processing:
        for meta in metas:
            if not isinstance(meta.get("processing"), dict):
                errors.append(
                    f"样品 '{meta.get('sample_id') or '?'}' 没有 processing 块 "
                    f"—— 这条梯度里工艺就是自变量，缺了它样品身份不可追踪"
                )

    treatments = []
    for meta in metas:
        raw = meta.get("processing")
        if isinstance(raw, dict) and raw.get("applied") is True:
            treatments.append((
                str(meta.get("sample_id") or "?"),
                tuple(str(raw.get(k)) for k in PROCESSING_REQUIRED_FIELDS),
            ))
    if len(treatments) >= 2:
        bucket: Dict[Any, List[str]] = {}
        for name, key in treatments:
            bucket.setdefault(key, []).append(name)
        same = [v for v in bucket.values() if len(v) > 1]
        if len(bucket) == 1:
            errors.append(
                "所有样品的工艺完全相同 —— 这不是一条梯度；"
                "同条件下的重复属于同一 sample 的多颗电芯"
            )
        else:
            for group in same:
                warnings.append(
                    f"样品 {'/'.join(group)} 的工艺完全相同 —— "
                    f"确认它们是平行批还是同一个处理（后者应合并为一个 sample）"
                )

    for path in ("electrode.mass_loading_mg_cm2",
                 "electrode.coating_thickness_um",
                 "electrode.area_cm2"):
        vals = []
        for meta in metas:
            value = _dig(meta, path)
            try:
                vals.append(float(value))
            except (TypeError, ValueError):
                continue
        if len(vals) < 2:
            continue
        lo, hi = min(vals), max(vals)
        if lo > 0 and (hi - lo) / lo * 100.0 > geometry_tolerance_pct:
            warnings.append(
                f"{path} 在样品间相差 {(hi - lo) / lo * 100.0:.1f} % "
                f"（{lo:g} → {hi:g}）—— 材料对比时电极差异会混进参数差异，"
                f"结论只能写「当前电极工艺下的综合差异」"
            )

    return {"errors": errors, "warnings": warnings}


def _main(argv=None) -> int:
    """``python -m battery_sim.datasets.material_metadata --series <dir>``

    一个目录 = 一条梯度：逐份校验 + 系列级校验。填完 metadata 先跑这个，
    再看报告 —— 错误为零才谈分析。
    """
    import argparse
    from pathlib import Path as _Path

    parser = argparse.ArgumentParser(
        description="材料元数据校验（单份 / 一条梯度）")
    parser.add_argument("--series", metavar="DIR",
                        help="目录里每个 *.yaml 是一个样品，并做系列级校验")
    parser.add_argument("--file", action="append", default=[], metavar="PATH")
    args = parser.parse_args(argv)

    paths = [_Path(p) for p in args.file]
    if args.series:
        paths += sorted(_Path(args.series).glob("*.yaml"))
    if not paths:
        parser.error("至少给 --series DIR 或 --file PATH")

    metas: List[Dict[str, Any]] = []
    bad = 0
    for path in paths:
        meta = load_metadata(path)
        metas.append(meta)
        result = validate(meta)
        print(f"\n=== {path} ===")
        print(render(meta, result))
        print(f"  {processing_summary(meta)}")
        for item in result.get("pending", []):
            print(f"  PENDING  {item}")
        bad += len(result["errors"])

    if len(metas) > 1:
        series = validate_series(metas)
        print("\n=== 系列级（同一条梯度）===")
        print(series_table(metas))
        for err in series["errors"]:
            print(f"  ERROR  {err}")
            bad += 1
        for warn in series["warnings"]:
            print(f"  WARN   {warn}")

    print(f"\n{'FAIL' if bad else 'PASS'}：{bad} 个错误 / "
          f"{len(metas)} 份元数据")
    return 1 if bad else 0


#: 逐字段的"为什么问这个"
RECYCLING_FIELD_HELP = {
    "battery_type": "退役电池类型（例：18650 NMC/石墨 动力电池）",
    "cathode_type": "正极体系（例：NMC532 / LFP）—— 它决定石墨被什么污染",
    "graphite_origin": "石墨本身从哪来（原生人造石墨 / 天然 / 未知）",
    "method": "再生方法（例：酸浸 / 碱处理 / 水洗 / 热处理 / 组合）",
    "temperature_C": "处理温度（°C）；氧化性气氛高温会烧损石墨",
    "duration_h": "处理时长（h）",
    "atmosphere": "处理气氛（例：Ar / N2 / Ar-H2 / 真空）",
}


def recycling_identity(meta: Dict[str, Any]) -> Dict[str, Any]:
    """这一份样品的**身份元组**（用于分组与"是不是同一个材料"的判断）。

    报告里 fresh / spent / regenerated 三组必须带着它出现，
    否则表格里的"再生石墨"是一个无法复核的标签。
    """
    raw = meta.get("recycling") or {}
    source = raw.get("source") or {}
    treatment = raw.get("treatment") or {}
    return {
        "sample_id": meta.get("sample_id"),
        "material_class": meta.get("material_class"),
        "battery_type": source.get("battery_type"),
        "cathode_type": source.get("cathode_type"),
        "graphite_origin": source.get("graphite_origin"),
        "method": treatment.get("method"),
        "temperature_C": treatment.get("temperature_C"),
        "duration_h": treatment.get("duration_h"),
        "atmosphere": treatment.get("atmosphere"),
    }


def recycling_summary(meta: Dict[str, Any]) -> str:
    """一行摘要（报告用）。没有回收史时**明说没有**，不留白。"""
    identity = recycling_identity(meta)
    if not _filled(identity.get("method")) and \
            not _filled(identity.get("battery_type")):
        return "recycling: 未声明（pristine 参照可不填；回收料必须填）"
    parts = [
        f"来自 {identity.get('battery_type') or '?'}"
        f" / 正极 {identity.get('cathode_type') or '?'}"
        f" / 石墨 {identity.get('graphite_origin') or '?'}",
        f"处理 {identity.get('method') or '?'}"
        f" @ {identity.get('temperature_C')} °C"
        f" × {identity.get('duration_h')} h"
        f" in {identity.get('atmosphere') or '?'}",
    ]
    return "recycling: " + "；".join(parts)


def validate_structure(meta: Dict[str, Any]) -> Dict[str, List[str]]:
    """校验 ``structure:`` 块。返回 ``{errors, warnings, pending}``。

    WHY WHITELIST
        "平台只保存测量量"这条原则靠自觉是守不住的：一旦允许自由键，
        第一个写进来的会是 `defect_level: high`，半年后没人知道它是
        从 `id_ig` 推的还是从别的什么推的，而它会和参数一起进相关性分析。
        所以键必须**闭集**，越界要报错，并告诉他该写哪个测量量。

    WHY `not_available_reason`
        "缺失处理方式"也是契约的一部分：一个块要么给出测量量与来源，
        要么明确说明**为什么没有**。否则"没测"与"忘了写"在下游完全一样。
        与 `not_measured` 判定词是同一个道理。
    """
    errors: List[str] = []
    warnings: List[str] = []
    pending: List[str] = []

    raw = meta.get("structure")
    if raw is None:
        pending.append(
            "structure: 整块未声明 —— XRD/Raman/BET 一个都没有，"
            "Phase 3 的「结构 → 参数」关联无从建立"
        )
        return {"errors": errors, "warnings": warnings, "pending": pending}
    if not isinstance(raw, dict):
        errors.append("structure 必须是一个 mapping（键为 xrd / raman / bet）")
        return {"errors": errors, "warnings": warnings, "pending": pending}

    unknown_blocks = [k for k in raw if k not in STRUCTURE_BLOCKS]
    if unknown_blocks:
        errors.append(
            f"structure 里有未知块 {unknown_blocks}；"
            f"允许 {list(STRUCTURE_BLOCKS)}"
        )

    for block in STRUCTURE_BLOCKS:
        entry = raw.get(block)
        where = f"structure.{block}"
        if entry is None:
            pending.append(f"{where}: 未声明（没测过？写上 available: false + 原因）")
            continue
        if not isinstance(entry, dict):
            errors.append(f"{where} 必须是 mapping")
            continue

        # 1 键白名单（含解释性键的定向提示）
        allowed = STRUCTURE_FIELDS[block]
        for key in entry:
            if key in allowed:
                continue
            hint = INTERPRETATION_KEYS.get(str(key).lower())
            if hint:
                errors.append(
                    f"{where}.{key} 是**解释**不是测量量：{hint}。"
                    f"（结构与参数的关联属分析层，不写进数据契约）"
                )
            else:
                errors.append(
                    f"{where}.{key} 不在允许字段内 {list(allowed)}"
                )

        if "available" not in entry:
            errors.append(f"{where}.available 必填（true/false）")
            continue
        available = entry["available"]
        if not isinstance(available, bool):
            errors.append(f"{where}.available 必须是布尔值，得到 {available!r}")
            continue

        # 2 缺失处理方式
        if not available:
            reason = str(entry.get("not_available_reason") or "").strip()
            if not reason:
                errors.append(
                    f"{where}.available=false 必须写 not_available_reason"
                    f"（没测 / 样品不够 / 仪器不可用 —— 说明「为什么没有」）"
                )
            else:
                pending.append(f"{where}: 未测（{reason}）")
            # available=false 时其余字段可以留空，但填了就要合法。
            # "填了"要用 _filled 判：模板里 source 是一堆 null 的 mapping，
            # 那种形态是"还没填"，不是"自相矛盾"。
            for key in STRUCTURE_REQUIRED[block]:
                if _filled(entry.get(key)):
                    warnings.append(
                        f"{where}.available=false 却填了 {key} —— 自相矛盾"
                    )
            continue

        # 3 available=true：必填 + 来源 + 数值
        for key in STRUCTURE_REQUIRED[block]:
            value = entry.get(key)
            if value is None or (isinstance(value, str)
                                 and not str(value).strip()):
                errors.append(
                    f"{where}.{key} 必填（available=true 就要给出测量量与来源）"
                )
        role = str(entry.get("role") or "").strip()
        if role and role not in ("identification", "validation", "exploration"):
            errors.append(
                f"{where}.role='{role}' 不在 "
                f"['identification', 'validation', 'exploration'] 内"
            )
        src = entry.get("source")
        if src is not None:
            errors.extend(_validate_source(src, where))

        for key in STRUCTURE_POSITIVE:
            if key not in entry or entry[key] in (None, ""):
                continue
            try:
                num = float(entry[key])
            except (TypeError, ValueError):
                errors.append(f"{where}.{key} = {entry[key]!r} 不是数字")
                continue
            if not num > 0:
                errors.append(f"{where}.{key} = {num} 必须为正")
                continue
            band = STRUCTURE_PLAUSIBLE.get(key)
            if band and not (band[0] <= num <= band[1]):
                warnings.append(
                    f"{where}.{key} = {num} 落在常见区间 {band} 之外 —— "
                    f"先确认单位（名字里的单位就是契约）"
                )

        # 4 孔分布：文件路径或含 file 的 mapping
        if block == "bet" and "pore_size_distribution" in entry:
            psd = entry["pore_size_distribution"]
            ok_form = (isinstance(psd, str) and psd.strip()) or (
                isinstance(psd, dict) and str(psd.get("file") or "").strip())
            if not ok_form:
                errors.append(
                    "structure.bet.pore_size_distribution 必须是文件路径"
                    "（字符串）或含 file 的 mapping"
                )

    return {"errors": errors, "warnings": warnings, "pending": pending}


def _validate_source(src: Any, where: str) -> List[str]:
    """结构表征同样要**逐条来源**：谁测的、什么仪器、哪一天、什么样品状态。"""
    if not isinstance(src, dict):
        return [f"{where}.source 必须是 mapping（type/instrument/operator/date）"]
    out: List[str] = []
    stype = str(src.get("type") or "").strip()
    if stype not in SOURCE_TYPES:
        out.append(
            f"{where}.source.type='{stype}' 不在 {list(SOURCE_TYPES)} 内"
        )
    for key in ("instrument", "operator", "date"):
        if not str(src.get(key) or "").strip():
            out.append(
                f"{where}.source.{key} 必填 —— 出现 「BET=56.3」 却不知道"
                f"谁测的/哪台仪器/哪一天，这个数就不能进论文"
            )
    return out


def structure_available(meta: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """已测的结构块（含文件路径与关键测量量），供报告引用。"""
    out: Dict[str, Dict[str, Any]] = {}
    raw = meta.get("structure") or {}
    if not isinstance(raw, dict):
        return out
    for block in STRUCTURE_BLOCKS:
        entry = raw.get(block)
        if isinstance(entry, dict) and entry.get("available") is True:
            out[block] = dict(entry)
    return out


def structure_pending(meta: Dict[str, Any]) -> List[str]:
    """哪些结构块没有（含原因）——报告里要写出来，不能留白。"""
    out: List[str] = []
    raw = meta.get("structure") or {}
    if not isinstance(raw, dict):
        return [f"{b}: 未声明" for b in STRUCTURE_BLOCKS]
    for block in STRUCTURE_BLOCKS:
        entry = raw.get(block)
        if not isinstance(entry, dict):
            out.append(f"{block}: 未声明")
        elif entry.get("available") is not True:
            out.append(f"{block}: {entry.get('not_available_reason') or '未测'}")
    return out


def validate(meta: Dict[str, Any]) -> Dict[str, List[str]]:
    """返回 ``{errors, warnings, missing}``。

    · errors    契约不满足 → 不能开始分析
    · warnings  可能自相矛盾或证据不足 → 必须读一遍
    """
    errors: List[str] = []
    warnings: List[str] = []

    missing = missing_fields(meta)
    for path in missing:
        errors.append(
            f"缺字段 '{path}'：{FIELD_HELP.get(path, '')}"
        )

    cls = str(_dig(meta, "material_class") or "").strip()
    if cls and cls not in MATERIAL_CLASSES:
        errors.append(
            f"material_class='{cls}' 不在允许集合 {list(MATERIAL_CLASSES)} 内"
        )
    if cls == "pristine" and _dig(meta, "regeneration_condition"):
        warnings.append(
            "material_class='pristine' 却写了 regeneration_condition —— "
            "两者自相矛盾，确认这是不是参照样品"
        )

    # 数值字段：必须是正数
    for path in ("electrode.mass_loading_mg_cm2",
                 "electrode.coating_thickness_um",
                 "electrode.area_cm2",
                 "particle.d50_um"):
        value = _dig(meta, path)
        if value is None:
            continue
        try:
            num = float(value)
        except (TypeError, ValueError):
            errors.append(f"字段 '{path}' = {value!r} 不是数字")
            continue
        if not num > 0:
            errors.append(f"字段 '{path}' = {num} 必须为正")

    # 测量项
    measurements = _dig(meta, "measurements") or []
    if isinstance(measurements, dict):
        measurements = [measurements]
    if measurements and not isinstance(measurements, list):
        errors.append("measurements 必须是列表（每项含 technique 与 file）")
        measurements = []
    seen_techniques = []
    for i, item in enumerate(measurements):
        if not isinstance(item, dict):
            errors.append(f"measurements[{i}] 不是 mapping")
            continue
        tech = str(item.get("technique") or "").strip()
        if not tech:
            errors.append(f"measurements[{i}] 缺 technique")
        elif tech not in TECHNIQUE_VOCAB:
            errors.append(
                f"measurements[{i}].technique='{tech}' 不在词表 "
                f"{list(TECHNIQUE_VOCAB)} 内（不许自造，否则下游无法判断"
                f"这个参数有没有证据）"
            )
        else:
            seen_techniques.append(tech)
        if not str(item.get("file") or "").strip():
            errors.append(
                f"measurements[{i}]（{tech or '?'}）缺 file —— 没有文件路径"
                f"的分析无法复算"
            )
        role = str(item.get("role") or "").strip()
        if role and role not in ("identification", "validation", "exploration"):
            errors.append(
                f"measurements[{i}].role='{role}' 不在 "
                f"['identification', 'validation', 'exploration'] 内"
            )

    # 证据覆盖：没测的量不许出结论
    for param, needed in PARAMETER_EVIDENCE.items():
        if not any(t in seen_techniques for t in needed):
            warnings.append(
                f"没有 {needed} 测量 ⇒ 本数据集对 '{param}' **只能写 "
                f"not measured**，不许给判定"
            )
    if "CC_charge_discharge" not in seen_techniques \
            and "rate_capability" not in seen_techniques:
        warnings.append(
            "没有恒流充放电/倍率测量 ⇒ 容量与倍率行为没有独立证据"
        )

    # 参数来源声明（可选；填了就必须合法，留空 = 未声明）
    sources = meta.get("parameter_sources")
    if sources is not None:
        if not isinstance(sources, dict):
            errors.append("parameter_sources 必须是 {参数名: 来源} 的 mapping")
        else:
            for name, src in sources.items():
                if src is None or not str(src).strip():
                    continue          # 模板里的 null = 还没填，不是错
                try:
                    validate_parameter_source(name, src)
                except ValueError as exc:
                    errors.append(str(exc))

    # 结构表征（XRD / Raman / BET）：只收测量量与来源，解释留给分析层
    structure = validate_structure(meta)
    errors.extend(structure["errors"])
    warnings.extend(structure["warnings"])
    pending = list(structure["pending"])

    # 回收史：回收/再生料的**样品身份**（缺了它"再生石墨"只是一个标签）
    recycling = validate_recycling(meta)
    errors.extend(recycling["errors"])
    warnings.extend(recycling["warnings"])
    missing.extend(recycling["missing"])

    # 通用工艺史：与 recycling 是两个维度（从哪来 vs 做了什么）
    processing = validate_processing(meta)
    errors.extend(processing["errors"])
    warnings.extend(processing["warnings"])
    pending.extend(processing["pending"])

    return {"errors": errors, "warnings": warnings, "missing": missing,
            "pending": pending}


def validate_parameter_source(name: str, source) -> str:
    """校验一个参数来源声明，返回规整后的来源词。非法即报错（禁止猜）。"""
    raw = str(source or "").strip().lower()
    if raw not in PARAMETER_SOURCE_VOCAB:
        raise ValueError(
            f"参数 '{name}' 的来源 '{source}' 不在词表 "
            f"{list(PARAMETER_SOURCE_VOCAB)} 内。"
            f"审稿人会问这个参数怎么来的，答案必须是可归因的一个词。"
        )
    return raw


def techniques(meta: Dict[str, Any]) -> List[str]:
    """这份元数据声明了哪些电化学测量（去重、保序）。"""
    out: List[str] = []
    items = _dig(meta, "measurements") or []
    if isinstance(items, dict):
        items = [items]
    for item in items:
        if isinstance(item, dict):
            tech = str(item.get("technique") or "").strip()
            if tech and tech not in out:
                out.append(tech)
    return out


def render(meta: Optional[Dict[str, Any]],
           result: Optional[Dict[str, List[str]]] = None) -> str:
    """把元数据与校验结果排成一份可贴进报告/聊天记录的清单。"""
    lines: List[str] = []
    if meta is None:
        lines.append("材料元数据：**未提供**")
        lines.append("  ⇒ 粒径/载量/厚度未知时，任何 D_s 数值都不能与另一份"
                     "样品比较（D ∝ R²）")
        return "\n".join(lines)

    lines.append("# 材料元数据")
    lines.append(f"sample_id       : {_dig(meta, 'sample_id')}")
    lines.append(f"material_class  : {_dig(meta, 'material_class')}")
    if _dig(meta, "regeneration_condition"):
        lines.append(f"regeneration    : {_dig(meta, 'regeneration_condition')}")
    lines.append(f"source          : {_dig(meta, 'source')}")
    lines.append(
        f"electrode       : 载量 {_dig(meta, 'electrode.mass_loading_mg_cm2')} "
        f"mg/cm² | 厚度 {_dig(meta, 'electrode.coating_thickness_um')} µm | "
        f"面积 {_dig(meta, 'electrode.area_cm2')} cm²"
    )
    lines.append(f"particle d50    : {_dig(meta, 'particle.d50_um')} µm")
    lines.append(
        f"cell            : 对电极 {_dig(meta, 'cell.counter_electrode')} | "
        f"电解液 {_dig(meta, 'cell.electrolyte')}"
    )
    lines.append(f"processing      : {processing_summary(meta)[12:]}")
    tech = techniques(meta)
    lines.append(f"measurements    : {tech if tech else '(未声明)'}")

    # 结构表征：只写测量量（数值 + 单位写在字段名里），解释留在分析层
    keys = {"xrd": ("d002_nm", "nm"), "raman": ("id_ig", ""),
            "bet": ("surface_area_m2_g", "m2/g")}
    avail = structure_available(meta)
    if avail:
        parts = []
        for block, entry in avail.items():
            field, unit = keys[block]
            parts.append(f"{block} {field}={entry.get(field)}{unit}")
        lines.append(f"structure       : {' | '.join(parts)}")
    gaps = structure_pending(meta)
    if gaps:
        lines.append(f"structure gap   : {'; '.join(gaps)}")

    if result is not None:
        for err in result.get("errors", []):
            lines.append(f"  ERROR  {err}")
        for warn in result.get("warnings", []):
            lines.append(f"  WARN   {warn}")
        if not result.get("errors"):
            lines.append(
                f"  => 契约满足（{len(result.get('warnings', []))} 个警告需人工确认）"
            )
    return "\n".join(lines)


__all__ = [
    "FIELD_HELP",
    "MATERIAL_CLASSES",
    "MaterialMetadataError",
    "PARAMETER_EVIDENCE",
    "PARAMETER_SOURCE_VOCAB",
    "PROCESSING_FIELDS",
    "PROCESSING_OPTIONAL_FIELDS",
    "PROCESSING_REQUIRED_FIELDS",
    "REGENERATION_REQUIRED_FOR",
    "REQUIRED_FIELDS",
    "TECHNIQUE_VOCAB",
    "load_metadata",
    "mass_loss_pct",
    "missing_fields",
    "processing_summary",
    "render",
    "series_table",
    "techniques",
    "validate",
    "validate_parameter_source",
    "validate_processing",
    "validate_series",
]


if __name__ == "__main__":       # pragma: no cover
    raise SystemExit(_main())

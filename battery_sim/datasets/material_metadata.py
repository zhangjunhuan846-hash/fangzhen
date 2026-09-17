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
        value = _dig(meta, "regeneration_condition")
        if value is None or (isinstance(value, str) and not value.strip()):
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
    "REGENERATION_REQUIRED_FOR",
    "REQUIRED_FIELDS",
    "TECHNIQUE_VOCAB",
    "load_metadata",
    "missing_fields",
    "render",
    "techniques",
    "validate",
    "validate_parameter_source",
]

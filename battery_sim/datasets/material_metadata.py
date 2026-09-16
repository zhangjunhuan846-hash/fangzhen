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

    return {"errors": errors, "warnings": warnings, "missing": missing}


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

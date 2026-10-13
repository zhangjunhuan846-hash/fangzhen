"""回收石墨 Excel 工作台：标准库读取、受控约束推导、校验与版本归档。

不执行工作簿公式，不改写原始 Excel，不调用 PyBaMM，不生成未测性能。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import posixpath
from datetime import datetime, timedelta
from pathlib import Path
from user_tools.excel_columns import column
import xml.etree.ElementTree as ET
import zipfile

SCHEMA_PATH = Path(__file__).with_name("rg_workstation_schema.json")
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

# y = constant * product(factors) / product(divisors). 只允许此处登记的关系。
RULES = (
    ("active_mass", "active_mass_mg", 1.0, ("area_cm2", "total_loading_mg_cm2", "active_fraction"), ()),
    ("reference_capacity", "capacity_mAh", 0.001, ("active_mass_mg", "q_ref_mAh_g"), ()),
    ("test_current", "current_mA", 1.0, ("capacity_mAh", "c_rate"), ()),
    ("coating_density", "bulk_density_g_cm3", 10.0, ("total_loading_mg_cm2",), ("thickness_um",)),
)
LABELS = {
    "area_cm2": "面积 (cm²)", "total_loading_mg_cm2": "总干涂层面载量 (mg/cm²)",
    "active_fraction": "活性质量分数", "capacity_mAh": "参考容量 (mAh)",
    "active_mass_mg": "活性质量 (mg)", "q_ref_mAh_g": "参考比容量 (mAh/g)",
    "current_mA": "电流 (mA)", "c_rate": "倍率 (C)", "thickness_um": "涂层厚度 (µm)",
    "bulk_density_g_cm3": "干涂层体密度 (g/cm³)",
}
UNITS = {
    'area_cm2': {'cm2': 1, 'cm²': 1, 'mm2': .01, 'mm²': .01},
    'total_loading_mg_cm2': {'mg/cm2': 1, 'mg/cm²': 1, 'g/cm2': 1000, 'g/cm²': 1000},
    'active_fraction': {'fraction': 1, '1': 1, '%': 1},
    'capacity_mAh': {'mAh': 1, 'Ah': 1000},
    'active_mass_mg': {'mg': 1, 'g': 1000},
    'q_ref_mAh_g': {'mAh/g': 1, 'Ah/kg': 1, 'Ah/g': 1000},
    'current_mA': {'mA': 1, 'A': 1000},
    'c_rate': {'C': 1, '1/h': 1},
    'thickness_um': {'µm': 1, 'μm': 1, 'um': 1, 'mm': 1000},
    'bulk_density_g_cm3': {'g/cm3': 1, 'g/cm³': 1, 'kg/m3': .001, 'kg/m³': .001},
}


def constraint_number(key, value, unit):
    if value is None:
        return None
    if unit not in UNITS[key]:
        raise ValueError(f'{key} 单位未登记：{unit!r}；允许 {list(UNITS[key])}')
    if isinstance(value, str) and value.strip().endswith('%'):
        if key != 'active_fraction':
            raise ValueError(f'{key} 不接受百分数')
        number = float(value.strip()[:-1])/100
    else:
        number = float(value)
    if not math.isfinite(number):
        raise ValueError(f'{key} 需要有限数值')
    if key == 'active_fraction' and unit == '%' and number > 1:
        raise ValueError('活性分数请填 90% 或 0.9，不填裸数 90')
    return number * UNITS[key][unit]


def is_number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def solve_constraints(known, bounds=None):
    """对单未知的乘除关系迭代传播；多未知保留，不补默认值或强称唯一解。"""
    values, issues, trace = {}, [], []
    for key, value in known.items():
        if key not in LABELS:
            issues.append(f"未登记的变量：{key}")
        elif not is_number(value):
            issues.append(f"{key} 必须为有限数值")
        elif value < 0 or (key not in ("c_rate", "current_mA") and value == 0):
            issues.append(f"{LABELS[key]} 的取值必须为正（倍率和电流允许为零）")
        elif key == "active_fraction" and value > 1:
            issues.append("活性质量分数应在 (0,1] 内，90% 对应 0.9")
        else:
            values[key] = float(value)
    supplied = set(values)
    if issues:
        return {"status": "conflict", "values": values, "unknown": sorted(set(LABELS) - supplied), "trace": [], "issues": issues}
    for _ in range(len(LABELS) + 1):
        changed = False
        for rule_id, out, factor, factors, divisors in RULES:
            keys = (out,) + factors + divisors
            missing = [k for k in keys if k not in values]
            if len(missing) > 1:
                continue
            try:
                if not missing:
                    predicted = factor * math.prod(values[k] for k in factors) / math.prod(values[k] for k in divisors)
                    if not math.isclose(values[out], predicted, rel_tol=1e-6, abs_tol=1e-9):
                        message = f"{rule_id} 冲突：已知 {LABELS[out]}={values[out]:.8g}，其余已知量要求 {predicted:.8g}"
                        if message not in issues:
                            issues.append(message)
                    continue
                target = missing[0]
                if target == out:
                    result = factor * math.prod(values[k] for k in factors) / math.prod(values[k] for k in divisors)
                elif target in factors:
                    result = values[out] * math.prod(values[k] for k in divisors) / (factor * math.prod(values[k] for k in factors if k != target))
                else:
                    result = factor * math.prod(values[k] for k in factors) / (values[out] * math.prod(values[k] for k in divisors if k != target))
                if not math.isfinite(result):
                    raise ValueError("nonfinite")
                if result < 0 or (result == 0 and target not in ("current_mA", "c_rate")) or (target == "active_fraction" and result > 1):
                    issues.append(f"{rule_id} 推得 {target}={result:.8g}，越过物理取值范围")
                    continue
                values[target] = result
                trace.append({"rule": rule_id, "solved": target, "value": result, "from": [k for k in keys if k != target]})
                changed = True
            except ZeroDivisionError:
                # 例如 I=0、C=0 不能唯一反推容量。
                continue
            except (OverflowError, ValueError):
                issues.append(f"{rule_id} 无法进行有限值计算")
        if not changed:
            break
    for key, limits in (bounds or {}).items():
        low, high = limits
        if any(v is not None and not is_number(v) for v in (low, high)):
            issues.append(f"{key} 边界必须为有限数值")
            continue
        if low is not None and high is not None and low > high:
            issues.append(f"{key} 下限大于上限")
        if key in values:
            if low is not None and values[key] < low - 1e-9:
                issues.append(f"{LABELS.get(key,key)}={values[key]:.8g} 小于下限 {low:g}")
            if high is not None and values[key] > high + 1e-9:
                issues.append(f"{LABELS.get(key,key)}={values[key]:.8g} 大于上限 {high:g}")
    unknown = sorted(set(LABELS) - set(values))
    return {"status": "conflict" if issues else ("partial" if unknown else "solved"),
            "values": values, "unknown": unknown, "trace": trace, "issues": issues,
            "input_variables": sorted(supplied),
            "note": "此处容量是参考比容量换算结果，不是电化学性能预测。"}


def read_xlsx(path):
    """读取单元格原值；公式标记原样保留，绝不执行任意表达式。"""
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
                shared.append("".join(t.text or "" for t in si.findall(".//m:t", NS)))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        targets = {r.attrib["Id"]: r.attrib["Target"] for r in rels}
        out = {}
        root = ET.fromstring(z.read("xl/workbook.xml"))
        for sheet in root.findall("m:sheets/m:sheet", NS):
            target = targets[sheet.attrib[f"{{{REL}}}id"]]
            target = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
            cells = {}
            for c in ET.fromstring(z.read(target)).findall(".//m:sheetData/m:row/m:c", NS):
                address, typ = c.attrib["r"], c.attrib.get("t", "")
                formula = c.find("m:f", NS)
                if formula is not None:
                    cells[address] = {"formula": formula.text or ""}
                    continue
                v = c.find("m:v", NS)
                if typ == "inlineStr":
                    value = "".join(t.text or "" for t in c.findall(".//m:t", NS))
                elif v is None or v.text is None:
                    value = None
                elif typ == "s":
                    value = shared[int(v.text)]
                elif typ in ("str", "e"):
                    value = v.text
                elif typ == "b":
                    value = v.text == "1"
                else:
                    try:
                        value = float(v.text)
                    except ValueError:
                        value = v.text
                cells[address] = value
            out[sheet.attrib["name"]] = cells
        return out


def load_records(cells):
    records, issues = {}, []
    for spec in SCHEMA["tables"]:
        name = spec["sheet"]
        records[name] = []
        if name not in cells:
            issues.append({"sheet": name, "row": None, "severity": "error", "message": "缺少工作表"})
            continue
        grid = cells[name]
        # 验证实际列名与模板一致，避免插列后读取错位。
        for i, f in enumerate(spec["fields"], 1):
            if grid.get(f"{column(i)}{SCHEMA['header_row']}") != f["label"]:
                issues.append({"sheet": name, "row": 6, "severity": "error", "message": f"列名/顺序发生变化：预期 {f['label']} 在 {column(i)}6"})
        row_numbers = sorted({int(c.lstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ")) for c in grid if int(c.lstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ")) >= SCHEMA["first_data_row"]})
        for row in row_numbers:
            record = {"_row": row}
            for i,f in enumerate(spec["fields"],1):
                if f["type"] == "derived":
                    continue
                value = grid.get(f"{column(i)}{row}")
                if isinstance(value, str):
                    value = value.strip() or None
                if isinstance(value, dict):
                    issues.append({"sheet": name, "row": row, "severity": "error", "message": f"输入字段 {f['label']} 含公式；请填写实测原值"})
                    value = None
                if f["type"] == "date" and is_number(value):
                    value = (datetime(1899,12,30) + timedelta(days=value)).date().isoformat()
                record[f["key"]] = value
            if any(v is not None for k,v in record.items() if k != "_row"):
                records[name].append(record)
    return records, issues


def normalize_and_validate(records):
    issues, indexes = [], {}
    def issue(sheet, record, message, severity="error"):
        issues.append({"sheet": sheet, "row": record["_row"], "severity": severity, "message": message})
    for spec in SCHEMA["tables"]:
        name, key = spec["sheet"], spec["id"]
        index = indexes.setdefault(name,{})
        for rec in records.get(name,[]):
            ident = rec.get(key)
            if ident is not None and not isinstance(ident,str):
                issue(name,rec,f"{key} 应填写文本编号")
            if ident in index:
                issue(name,rec,f"编号重复：{ident}")
            elif ident is not None:
                index[ident] = rec
            for f in spec["fields"]:
                v = rec.get(f["key"])
                if f["type"] == "derived":
                    continue
                if v is None:
                    if f.get("required"):
                        issue(name,rec,f"缺少 {f['label']}")
                    continue
                if f["type"] in ("number","fraction"):
                    if not is_number(v):
                        issue(name,rec,f"{f['label']} 必须是数值")
                    elif f["type"] == "fraction" and not 0 <= v <= 1:
                        issue(name,rec,f"{f['label']} 应在 0–100% 内，90% 对应 0.9")
                    elif "min" in f and (v < f["min"] or (f.get("exclusive_min") and v == f["min"])):
                        issue(name,rec,f"{f['label']} 低于允许下限")
                elif f["type"] == "date":
                    try:
                        datetime.fromisoformat(str(v))
                    except ValueError:
                        issue(name,rec,f"{f['label']} 应填 Excel 日期或 YYYY-MM-DD")
                if f.get("choices") and v not in f["choices"]:
                    issue(name,rec,f"{f['label']} 不在允许选项中")
    for spec in SCHEMA["tables"]:
        name = spec["sheet"]
        for rec in records.get(name,[]):
            for f in spec["fields"]:
                if f.get("ref") and rec.get(f["key"]) is not None:
                    target,_ = f["ref"]
                    if rec[f["key"]] not in indexes[target]:
                        issue(name,rec,f"{f['label']} 找不到对应记录：{rec[f['key']]}")
    def divide(a,b,scale=1):
        return a/b*scale if is_number(a) and is_number(b) and b > 0 else None
    for r in records["样品工艺"]:
        r["mass_yield"] = divide(r.get("mass_after_g"),r.get("mass_before_g"))
        before,after = r.get("carbon_before_fraction"),r.get("carbon_after_fraction")
        r["carbon_yield"] = r["mass_yield"]*after/before if r["mass_yield"] is not None and is_number(before) and before > 0 and is_number(after) else None
        if r.get("status") == "已完成" and not r.get("method"):
            issue("样品工艺",r,"已完成处理需要记录实际方法")
        if r.get("status") == "已完成" and (r.get("mass_before_g") is None or r.get("mass_after_g") is None):
            issue("样品工艺",r,"缺少处理前/后干基质量，暂不能计算收率","warning")
        if r["mass_yield"] is not None and r["mass_yield"] > 1:
            issue("样品工艺",r,"质量收率超过 100%，请核对干基边界或添加物","warning")
    for r in records["极片"]:
        m,w,a = r.get("dry_coating_mass_mg"),r.get("active_fraction"),r.get("area_cm2")
        r["active_mass_mg"] = m*w if is_number(m) and is_number(w) else None
        r["total_loading_mg_cm2"] = divide(m,a)
        r["active_loading_mg_cm2"] = divide(r["active_mass_mg"],a)
        q = r.get("q_ref_mAh_g")
        r["capacity_ref_mAh"] = r["active_mass_mg"]*q/1000 if is_number(r["active_mass_mg"]) and is_number(q) else None
        if r.get("porosity") is not None and not r.get("porosity_source"):
            issue("极片",r,"孔隙率缺少实测/派生依据","warning")
    for r in records["电芯"]:
        e = indexes["极片"].get(r.get("electrode_id"),{})
        r["prepare_id"] = e.get("prepare_id")
    for r in records["测试"]:
        lo,hi = r.get("voltage_lower_V"),r.get("voltage_upper_V")
        if is_number(lo) and is_number(hi) and lo >= hi:
            issue("测试",r,"电压下限应小于上限")
        if r.get("protocol") == "GITT" and (r.get("pulse_duration_s") is None or r.get("rest_duration_s") is None):
            issue("测试",r,"GITT 缺脉冲或静置时长","warning")
        if r.get("raw_file_path") is None:
            issue("测试",r,"尚未填写原始曲线路径","warning")
    for r in records["性能记录"]:
        c = indexes["电芯"].get(r.get("cell_id"),{})
        e = indexes["极片"].get(c.get("electrode_id"),{})
        r["electrode_id"],r["active_mass_mg"] = c.get("electrode_id"),e.get("active_mass_mg")
        r["ice"] = divide(r.get("first_delithiation_mAh"),r.get("first_lithiation_mAh"))
        r["q_1C_mAh_g"] = divide(r.get("q_1C_mAh"),r["active_mass_mg"],1000)
        if r.get("first_lithiation_mAh") == 0:
            issue("性能记录",r,"首次嵌锂电荷为零，不能计算 ICE")
        for key in ("formation_test_id","rate_test_id"):
            t = indexes["测试"].get(r.get(key),{})
            if t and t.get("cell_id") != r.get("cell_id"):
                issue("性能记录",r,f"{key} 属于另一颗电芯")
        if r.get("q_1C_mAh") is not None:
            t = indexes["测试"].get(r.get("rate_test_id"),{})
            if not t or not is_number(t.get("c_rate")) or not math.isclose(t["c_rate"],1,abs_tol=1e-6) or t.get("direction") != "脱锂":
                issue("性能记录",r,"1C 容量需关联声明倍率为 1C、方向为脱锂的测试")
            if not is_number(r["active_mass_mg"]) or r["active_mass_mg"] <= 0:
                issue("性能记录",r,"缺少有效活性质量，不能计算比容量")
            if r.get("rate_cycle") is None:
                issue("性能记录",r,"1C 容量缺少取值循环号","warning")
        if r.get("quality_status") == "排除" and not r.get("exclusion_reason"):
            issue("性能记录",r,"排除数据需要说明原因")
    for r in records["目标约束"]:
        lo,hi = r.get("lower"),r.get("upper")
        if is_number(lo) and is_number(hi) and lo > hi:
            issue("目标约束",r,"下限大于上限")
    for r in records["推荐记录"]:
        if r.get("mode") == "model_based" and (not r.get("model_version") or not r.get("training_snapshot")):
            issue("推荐记录",r,"模型推荐缺模型版本或训练快照")
    return records,issues


def design_from_cells(cells,records):
    grid = cells.get(SCHEMA["design"]["sheet"],{})
    known = {}
    problems = []
    mode = grid.get(SCHEMA["design"]["mode_cell"]) or "正向核算"
    if mode not in ('正向核算','反推面载量','参数联动'):
        problems.append(f'未支持的计算方式：{mode}')
    mapping = SCHEMA["design"]["inputs"]
    for k,address in mapping.items():
        if k in ("loading_min_mg_cm2","loading_max_mg_cm2"):
            continue
        value = grid.get(address)
        if value is None or value == "":
            continue
        if isinstance(value,dict):
            problems.append(f"{address} 已知值含公式，请填数值")
            continue
        if k == "target_capacity_mAh":
            if mode == "正向核算":
                continue
            k = "capacity_mAh"
        if mode == "反推面载量" and k == "total_loading_mg_cm2":
            continue
        known[k] = value
    low,high = grid.get("B13"),grid.get("B14")
    bounds = {}
    if low is not None or high is not None:
        if any(v is not None and not is_number(v) for v in (low,high)):
            problems.append("面载量边界必须为数值")
        else:
            bounds["total_loading_mg_cm2"] = (low,high)
    for r in records.get("目标约束",[]):
        # 批次专用约束不隐式应用于全局设计计算。
        if r.get("batch_id") or r.get("status") != "已确认":
            continue
        key = r.get("variable")
        if key in LABELS:
            try:
                if r.get('variable_role') in ('bounded','free'):
                    low = constraint_number(key,r.get('lower'),r.get('unit'))
                    high = constraint_number(key,r.get('upper'),r.get('unit'))
                    old_low, old_high = bounds.get(key,(None,None))
                    bounds[key] = (max(v for v in (low,old_low) if v is not None) if low is not None or old_low is not None else None,
                                   min(v for v in (high,old_high) if v is not None) if high is not None or old_high is not None else None)
                if r.get('variable_role') in ('fixed','target'):
                    if r.get('fixed_value') is None:
                        raise ValueError(f'{key} 的固定/目标值为空')
                    value = constraint_number(key,r['fixed_value'],r.get('unit'))
                    if key in known and not math.isclose(known[key],value,rel_tol=1e-6,abs_tol=1e-9):
                        problems.append(f"{key} 在已知输入与确认约束中不一致")
                    else:
                        known[key] = value
            except (TypeError,ValueError) as exc:
                problems.append(str(exc))
    result = solve_constraints(known,bounds)
    if problems:
        result["issues"].extend(problems)
        result["status"] = "conflict"
    result["mode"] = mode
    return result


def check_workbook(path,out,open_report=False):
    path = Path(path).resolve()
    cells = read_xlsx(path)
    from user_tools.rg_lite import is_lite, check_lite
    if is_lite(cells):
        return check_lite(path,cells,out,open_report)
    records,issues = load_records(cells)
    records,extra = normalize_and_validate(records)
    issues.extend(extra)
    if SCHEMA['design']['sheet'] not in cells:
        issues.append({'sheet': SCHEMA['design']['sheet'], 'row': None, 'severity': 'error', 'message': '缺少设计计算工作表'})
    design = design_from_cells(cells,records)
    total = sum(len(rs) for rs in records.values())
    errors = sum(i["severity"] == "error" for i in issues)
    status = "待录入" if total == 0 and not errors else ("需修正" if errors else "已归档")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    dest = Path(out).resolve()/stamp
    dest.mkdir(parents=True,exist_ok=False)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {"schema_version":SCHEMA["version"],"created_at":datetime.now().astimezone().isoformat(),
                "workbook":str(path),"input_sha256":digest,"status":status,
                "counts":{k:len(v) for k,v in records.items()},"issues":issues,
                "constraint_result":design,
                "capabilities":{"data_entry":True,"registered_constraint_rules":True,"pybamm_execution":False,"trained_process_recommender":False}}
    (dest/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    (dest/"records.json").write_text(json.dumps(records,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    for spec in SCHEMA["tables"]:
        with (dest/(spec["sheet"]+".csv")).open("w",encoding="utf-8-sig",newline="") as f:
            writer=csv.DictWriter(f,fieldnames=[v["key"] for v in spec["fields"]]+["_row"],extrasaction="ignore")
            writer.writeheader()
            writer.writerows(records[spec["sheet"]])
    (dest/"source.xlsx").write_bytes(path.read_bytes())
    esc=lambda x:html.escape(str(x))
    rows="".join(f"<tr><td>{esc(i['sheet'])}</td><td>{esc(i['row'])}</td><td>{esc(i['severity'])}</td><td>{esc(i['message'])}</td></tr>" for i in issues)
    design_rows="".join(f"<tr><td>{esc(LABELS[k])}</td><td>{v:.8g}</td></tr>" for k,v in design["values"].items())
    traces="".join(f"<li>{esc(t['rule'])}：推得 {esc(LABELS[t['solved']])} = {t['value']:.8g}</li>" for t in design["trace"])
    html_text=f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>工作台校验与归档</title>
<style>body{{font:16px/1.65 Arial,'Microsoft YaHei',sans-serif;max-width:1080px;margin:40px auto;padding:0 24px;color:#1e293b}}h1,h2{{color:#18324f}}table{{border-collapse:collapse;width:100%;margin:18px 0}}td,th{{text-align:left;padding:9px;border-bottom:1px solid #dbe4ee}}.muted{{color:#64748b}}pre{{white-space:pre-wrap}}</style>
<h1>回收石墨工作台校验</h1><p>记录状态：{esc(status)}。记录 {total} 条；错误 {errors} 项；提示 {len(issues)-errors} 项。</p>
<p class="muted">源文件 SHA256：{digest}<br>每次运行独立归档，原始 Excel 未改写。</p>
<h2>已知参数联动</h2><p>求解状态：{esc(design['status'])}。未知量仍保留为空，不补默认值。</p><table>{design_rows}</table><ul>{traces}</ul><p>{esc('；'.join(design['issues']) or '已知关系未发现冲突')}</p>
<p>仍缺：{esc('、'.join(LABELS[k] for k in design['unknown']))}</p>
<h2>记录问题</h2><table><tr><th>工作表</th><th>Excel 行</th><th>级别</th><th>说明</th></tr>{rows}</table>
<p>参考容量来自质量和参考比容量的代数换算。本版本未运行 PyBaMM，也未训练再生工艺推荐器。</p></html>"""
    (dest/"report.html").write_text(html_text,encoding="utf-8")
    if open_report:
        import webbrowser
        webbrowser.open((dest/'report.html').as_uri())
    print(json.dumps({"status":status,"records":total,"errors":errors,"constraint_status":design["status"],"report":str(dest/"report.html")},ensure_ascii=False))
    return 1 if errors or design["status"]=="conflict" else 0


def main(argv=None):
    ap=argparse.ArgumentParser(description="回收石墨 Excel 工作台：校验、受控约束求解与版本归档")
    ap.add_argument("command",choices=["check"])
    ap.add_argument("--workbook",required=True)
    ap.add_argument("--out",required=True)
    ap.add_argument('--open-report',action='store_true',help='校验后在默认浏览器打开报告')
    args=ap.parse_args(argv)
    try:
        return check_workbook(args.workbook,args.out,args.open_report)
    except (OSError,ValueError,KeyError,zipfile.BadZipFile,ET.ParseError) as exc:
        print(f"无法读取工作台：{exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

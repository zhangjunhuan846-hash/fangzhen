"""Native, dependency-free sample joins and explicit descriptor roles."""
import csv
import hashlib
import io
import json
import math
from user_tools.rg_lite import SCHEMA

NUMERIC = {'number', 'positive', 'fraction', 'temperature', 'integer', 'signed'}
PROCESS = {'method', 'temperature_C', 'reagent', 'concentration', 'solid_liquid_ratio_ml_g'}

def number(value):
    if value in (None, ''):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None

def catalog():
    result = []
    for table in SCHEMA['tables']:
        if table['sheet'] not in ['处理工艺', '表征', '极片']:
            continue
        for key, label, kind in table['fields']:
            if kind not in NUMERIC and key not in PROCESS and key not in ['conductive_type', 'binder_type']:
                continue
            if table['sheet'] == '处理工艺' and key not in PROCESS:
                continue
            result.append({'key': table['sheet'] + '.' + key, 'label': label,
                           'kind': 'numeric' if kind in NUMERIC else 'categorical',
                           'stage': 'process' if table['sheet'] == '处理工艺' else 'measured'})
    return result

def targets():
    return [{'key': '半电池.capacity', 'label': '比容量 (mAh/g)'}, {'key': '半电池.ice', 'label': '首次库仑效率'},
            {'key': '半电池.retention', 'label': '容量保持率'}, {'key': '处理工艺.yield', 'label': '材料质量收率'}] + [
                {'key': f['key'], 'label': f['label']} for f in catalog() if f['key'].startswith('表征.') and f['kind'] == 'numeric']

def unique_index(rows, key, name):
    result = {}
    for row in rows:
        ident = row.get(key)
        if not ident:
            raise ValueError(name + '缺少编号。')
        if ident in result:
            raise ValueError(name + '编号重复，不能建立一对一建模关联。')
        result[ident] = row
    return result

def workspace_dataset(tables, config):
    target = config.get('target', '半电池.capacity')
    if target not in {t['key'] for t in targets()}:
        raise ValueError('未知预测目标。')
    processes = unique_index(tables['处理工艺'], 'sample_id', '处理工艺')
    chars = unique_index(tables['表征'], 'sample_id', '表征')
    electrodes = unique_index(tables['极片'], 'electrode_id', '极片')
    cells = unique_index(tables['半电池'], 'cell_id', '半电池')
    output, exclusions = [], []
    for sample, proc in processes.items():
        batch = str(proc.get('batch_id') or '')
        if not batch:
            exclusions.append({'sample_id': sample, 'reason': '缺少原料批次'}); continue
        selected = []
        if target.startswith('半电池.'):
            for cell in cells.values():
                if cell.get('sample_id') != sample:
                    continue
                if any(number(cell.get(k)) != number(config.get(k, default)) for k, default in [('c_rate', 1), ('cycle', 1), ('temperature_C', 25)]):
                    continue
                electrode = electrodes.get(cell.get('electrode_id'))
                if electrode is None or electrode.get('sample_id') != sample:
                    raise ValueError('电芯与极片的样品关联不一致：' + str(cell.get('cell_id')))
                for key in ['electrolyte_recipe', 'separator_type', 'voltage_lower_V', 'voltage_upper_V']:
                    if cell.get(key) in (None, ''):
                        raise ValueError('建模需要明确电解液、隔膜和电压窗口；缺少：' + key)
                selected.append(cell)
            if not selected:
                exclusions.append({'sample_id': sample, 'reason': '没有符合倍率/循环/温度的电芯'}); continue
            protocol = {tuple(str(c.get(k)) for k in ['electrolyte_recipe', 'separator_type', 'voltage_lower_V', 'voltage_upper_V']) for c in selected}
            if len(protocol) != 1:
                raise ValueError('同一样品的测试体系不同，不能平均：' + sample)
            output_protocol = list(protocol)[0]
            values = []
            for cell in selected:
                v = number(cell.get(target.split('.')[1]))
                if target == '半电池.ice':
                    a, b = number(cell.get('first_lithiation')), number(cell.get('first_delithiation'))
                    v = b / a if a is not None and a > 0 and b is not None else None
                if v is not None:
                    values.append(v)
            electrode_rows = [electrodes[c['electrode_id']] for c in selected]
        else:
            output_protocol = ('material',)
            electrode_rows = [e for e in electrodes.values() if e.get('sample_id') == sample]
            if target == '处理工艺.yield':
                a, b = number(proc.get('mass_before_g')), number(proc.get('mass_after_g'))
                values = [b / a] if a is not None and a > 0 and b is not None else []
            else:
                v = number(chars.get(sample, {}).get(target.split('.')[1])); values = [] if v is None else [v]
        if not values:
            exclusions.append({'sample_id': sample, 'reason': '目标未测，保持缺失'}); continue
        y = sum(values) / len(values)
        if y < 0 or (target in ['半电池.ice', '半电池.retention', '处理工艺.yield'] and y > 1):
            raise ValueError('目标超出物理范围：' + sample)
        row = {'record_id': sample, 'batch_id': batch, 'target': y, 'replicates': len(values), '_protocol': output_protocol}
        recipe = {k: proc.get(k) for k in sorted(PROCESS | {'concentration_unit'})}
        row['group_id'] = hashlib.sha256(json.dumps([batch, recipe], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]
        for field in catalog():
            sheet, key = field['key'].split('.')
            if sheet == '处理工艺':
                v = proc.get(key)
            elif sheet == '表征':
                v = chars.get(sample, {}).get(key)
            else:
                vals = {str(e.get(key)): e.get(key) for e in electrode_rows if e.get(key) not in (None, '')}
                v = next(iter(vals.values())) if len(vals) == 1 else None
            row[field['key']] = number(v) if field['kind'] == 'numeric' else (str(v) if v not in (None, '') else None)
        output.append(row)
    protocols = {tuple(r.pop('_protocol')) for r in output}
    if len(protocols) > 1:
        raise ValueError('样品使用不同电解液/隔膜/电压窗口，请先筛选为同一协议或使用明确分组的自定义CSV。')
    return {'rows': output, 'fields': catalog(), 'target': target, 'exclusions': exclusions,
            'source': 'workspace_sample_join', 'group_basis': '同批次、相同已记录工艺配方同组；未记录工艺差异不能自动识别'}

def csv_dataset(raw, config):
    if len(raw) > 3_000_000:
        raise ValueError('建模CSV最多3MB。')
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
    names = reader.fieldnames or []
    if len(names) != len(set(names)) or len(names) > 100:
        raise ValueError('CSV列名重复或超过100列。')
    target = config.get('target')
    if not target or not {'record_id', 'group_id', 'batch_id', target} <= set(names):
        raise ValueError('CSV需要record_id、group_id、batch_id和指定目标列。')
    roles = config.get('roles', {})
    rows, ids, exclusions = [], set(), []
    for rawrow in reader:
        ident = str(rawrow['record_id']).strip()
        if not ident or ident in ids:
            raise ValueError('record_id缺失或重复。')
        ids.add(ident)
        if not str(rawrow['group_id']).strip() or not str(rawrow['batch_id']).strip():
            raise ValueError('独立工艺组和批次必须填写。')
        y = number(rawrow[target])
        if y is None:
            exclusions.append({'record_id': ident, 'reason': '目标缺失，不插补'}); continue
        rows.append({**rawrow, 'record_id': ident, 'group_id': str(rawrow['group_id']).strip(),
                     'batch_id': str(rawrow['batch_id']).strip(), 'target': y})
        if len(rows) > 500:
            raise ValueError('第一版最多500行建模样本。')
    fields = []
    for name in names:
        if name.startswith('_') or name in {'record_id', 'group_id', 'batch_id', target, 'target'}:
            continue
        observed = [r[name] for r in rows if r[name] not in ('', None)]
        numeric = bool(observed) and all(number(v) is not None for v in observed)
        fields.append({'key': name, 'label': name, 'kind': 'numeric' if numeric else 'categorical', 'stage': roles.get(name, 'measured')})
    return {'rows': rows, 'fields': fields, 'target': target, 'exclusions': exclusions,
            'source': 'user_csv', 'source_sha256': hashlib.sha256(raw).hexdigest(), 'group_basis': '用户声明独立工艺组，不能从CSV自动证明其正确性'}

def validate_selection(dataset, config):
    selected = config.get('features', [])
    fields = {f['key']: f for f in dataset['fields']}
    if not isinstance(selected, list) or not 1 <= len(selected) <= 30 or len(selected) != len(set(selected)):
        raise ValueError('请选择1–30个不同描述符。')
    for name in selected:
        if name not in fields or name in {dataset['target'], 'target'}:
            raise ValueError('不能把目标或编号作为描述符：' + name)
        if config.get('purpose', 'material') == 'process' and fields[name]['stage'] != 'process':
            raise ValueError('再生工艺推荐只能使用实验前已知变量：' + name)
    if config.get('purpose', 'material') not in ['material', 'process']:
        raise ValueError('未知建模用途。')
    return selected

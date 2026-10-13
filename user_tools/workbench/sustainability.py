"""Validated foreground inventory and explicitly scoped recycling references."""
import hashlib
import json
import math

PRESETS = {'default', 'pack_pyro', 'pack_hydro', 'pack_direct', 'pack_custom', 'scrap_direct'}
UNITS = {'kg', 'kWh', 'm3', 'L', 'tkm'}
SOURCE_COMMIT = 'e834058d2b361c8009fe53bd73347d84b17b4704'


def number(value, label, positive=False):
    if isinstance(value, bool) or value in (None, ''):
        raise ValueError(label + '需明确填写数值。')
    try:
        value = float(value)
    except (ValueError, TypeError):
        raise ValueError(label + '需为数值。') from None
    if not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError(label + ('需为正有限数。' if positive else '需为非负有限数。'))
    return value


def text(value, label, required=True):
    if not isinstance(value, str):
        if not required and value is None:
            return ''
        raise ValueError(label + '需为文本。')
    value = value.strip()
    if len(value) > 600 or (required and not value):
        raise ValueError(label + '需填写，且不超过600字。')
    return value


def normalize_config(config):
    if not isinstance(config, dict):
        raise ValueError('评价配置需为对象。')
    kind = config.get('kind')
    if kind == 'everbatt':
        if config.get('preset') not in PRESETS:
            raise ValueError('请选择已支持的EverBatt参考案例。')
        if config.get('accept_reference') is not True:
            raise ValueError('请确认参考案例采用上游工艺与价格假设。')
        return {'kind': kind, 'preset': config['preset'], 'accept_reference': True}
    if kind != 'inventory':
        raise ValueError('未知环境与经济评价类型。')
    if config.get('currency') not in {'CNY', 'USD', 'EUR'}:
        raise ValueError('请选择整份清单统一使用的币种。')
    if config.get('data_kind') not in {'declared_inventory', 'synthetic_demo'}:
        raise ValueError('请声明用户清单或软件合成算例。')
    rows = config.get('inventory')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 200:
        raise ValueError('清单需要1–200项。')
    result = {key: text(config.get(key), label) for key, label in [
        ('case_name', '评价名称'), ('boundary', '系统边界'),
        ('region', '地域/电力情景'), ('price_basis', '价格年份与依据')]}
    result.update(kind=kind, currency=config['currency'], data_kind=config['data_kind'],
                  sample_id=text(config.get('sample_id'), '关联样品', False),
                  output_kg=number(config.get('output_kg'), '本批合格再生石墨质量(kg)', True))
    normalized = []
    names = set()
    for i, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ValueError('清单行需为对象。')
        name = text(row.get('name'), f'第{i}项名称')
        if name in names:
            raise ValueError('清单名称重复，请合并或按工序明确区分。')
        names.add(name)
        if row.get('unit') not in UNITS:
            raise ValueError('清单单位只支持kg、kWh、m3、L、tkm；请先明确换算。')
        normalized.append({'name': name, 'unit': row['unit'],
            'quantity': number(row.get('quantity'), name + '本批消耗量'),
            'unit_price': number(row.get('unit_price'), name + '单位成本'),
            'gwp_factor': number(row.get('gwp_factor'), name + '单位碳足迹因子'),
            'source': text(row.get('source'), name + '数量/价格/因子来源')})
    result['inventory'] = normalized
    # First-stage cost screening: explicitly entered batch labor/equipment/overhead.
    result['batch_overhead'] = number(config.get('batch_overhead'), '本批人工/设备/其他费用')
    result['overhead_source'] = text(config.get('overhead_source'), '其他费用依据')
    json.dumps(result, allow_nan=False)
    return result


def inventory_totals(config):
    config = normalize_config(config)
    if config['kind'] != 'inventory':
        raise ValueError('此计算只接受工艺清单。')
    rows = [{**row, 'cost': row['quantity'] * row['unit_price'],
             'gwp_kg_co2e': row['quantity'] * row['gwp_factor']}
            for row in config['inventory']]
    cost = sum(row['cost'] for row in rows) + config['batch_overhead']
    gwp = sum(row['gwp_kg_co2e'] for row in rows)
    if not math.isfinite(cost) or not math.isfinite(gwp):
        raise ValueError('数量与因子乘积溢出，请核对单位。')
    mass = config['output_kg']
    if not math.isfinite(cost / mass) or not math.isfinite(gwp / mass):
        raise ValueError('单位产品结果溢出，请核对产量与单位。')
    return {'case_name': config['case_name'], 'sample_id': config['sample_id'],
            'currency': config['currency'], 'output_kg': mass,
            'batch_cost': cost, 'batch_gwp_kg_co2e': gwp,
            'cost_per_kg_product': cost / mass, 'gwp_kg_co2e_per_kg_product': gwp / mass,
            'contributions': rows, 'batch_overhead': config['batch_overhead'],
            'overhead_source': config['overhead_source'],
            'functional_unit': '1 kg of declared qualified regenerated graphite',
            'boundary': config['boundary'], 'region': config['region'], 'price_basis': config['price_basis'],
            'inventory_sha256': hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
            'evidence_type': 'synthetic_sustainability_demo' if config['data_kind'] == 'synthetic_demo' else 'user_inventory_screening',
            'scope': '用户声明清单与碳足迹因子的筛选计算；成本包含明确录入的批次费用。仅评价所列边界和GWP，不自动补充缺失工序、背景数据库、分配或避免负担，不构成完整多类别LCA、投资可行性或独立材料验证。'}

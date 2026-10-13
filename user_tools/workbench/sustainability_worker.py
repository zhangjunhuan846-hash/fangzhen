"""Independent Windows Python worker; imports no PyBaMM/PyBOP environment."""
import argparse
import csv
import importlib.metadata
import hashlib
import json
import math
import os
from pathlib import Path
import sys

from user_tools.workbench.sustainability import normalize_config, inventory_totals, SOURCE_COMMIT


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def inventory(config, out):
    result = inventory_totals(config)
    project_data = out / 'brightway'
    project_data.mkdir(parents=True, exist_ok=True)
    os.environ['BRIGHTWAY2_DIR'] = str(project_data.resolve())
    import bw2data as bd
    import bw2calc as bc
    bd.projects.set_current('foreground')
    emission = ('biosphere', 'co2_equivalent')
    bd.Database('biosphere').write({emission: {'name': 'Aggregated declared GWP',
        'unit': 'kilogram', 'type': 'emission', 'categories': ('air',)}})
    database = {}
    product = ('foreground', 'product')
    exchanges = [{'input': product, 'amount': 1, 'type': 'production'}]
    for i, row in enumerate(config['inventory']):
        key = ('foreground', f'flow_{i}')
        database[key] = {'name': row['name'], 'unit': row['unit'], 'exchanges': [
            {'input': key, 'amount': 1, 'type': 'production'},
            {'input': emission, 'amount': row['gwp_factor'], 'type': 'biosphere'}]}
        exchanges.append({'input': key, 'amount': row['quantity'] / config['output_kg'], 'type': 'technosphere'})
    database[product] = {'name': config['case_name'], 'unit': 'kilogram', 'exchanges': exchanges}
    bd.Database('foreground').write(database)
    method_key = ('declared factors', 'GWP screening')
    method = bd.Method(method_key)
    method.register(unit='kg CO2-eq')
    method.write([(emission, 1)])
    lca = bc.LCA({product: 1}, method_key)
    lca.lci(); lca.lcia()
    score = float(lca.score)
    if not math.isfinite(score) or not math.isclose(score, result['gwp_kg_co2e_per_kg_product'], rel_tol=2e-6, abs_tol=1e-8):
        raise ValueError('Brightway结果与清单核算不一致，请核对。')
    result.update(engine='Brightway foreground / declared aggregated factors',
                  brightway_score=score,
                  backend_versions={name: importlib.metadata.version(name) for name in ['bw2calc', 'bw2data', 'numpy']})
    with (out / 'contributions.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(result['contributions'][0]))
        writer.writeheader(); writer.writerows(result['contributions'])
    return result


def everbatt(config, out, project):
    source = project / 'data/backends/recycle_cost_tool_e834058'
    provenance = json.loads((source / 'SOURCE.json').read_text(encoding='utf-8-sig'))
    if provenance['commit'] != SOURCE_COMMIT:
        raise ValueError('EverBatt迁移源码版本与声明不一致。')
    if not provenance.get('hashes'):
        raise ValueError('EverBatt参考源码缺少文件哈希，请重新安装。')
    for name, digest in provenance.get('hashes', {}).items():
        file = (source / name).resolve()
        if not file.is_relative_to(source.resolve()) or hashlib.sha256(file.read_bytes()).hexdigest() != digest:
            raise ValueError('EverBatt参考源文件已改变，请核对后重新安装。')
    sys.path.insert(0, str(source / 'src'))
    from recycle_cost.model import get_scenario_from_preset
    from recycle_cost.app_services import calculated_result_tables, recycling_process_key
    scenario = get_scenario_from_preset(config['preset'])
    process = recycling_process_key(scenario.recycling_process)
    tables = calculated_result_tables(scenario, process)
    for name, table in tables.items():
        table.to_csv(out / (name + '.csv'), index=False, encoding='utf-8-sig')
    output = tables['output_summary'].set_index('metric')
    def metric(label):
        value = output.loc[label, process]
        return float(value) if value is not None and math.isfinite(float(value)) else None
    result = {'engine': 'recycle_cost_tool Python core', 'source_commit': SOURCE_COMMIT,
        'source_file_sha256': provenance['hashes'],
        'backend_versions': {name: importlib.metadata.version(name) for name in ['pandas', 'openpyxl']},
        'source_repository': 'https://github.com/zhouzhq2021/recycle_cost_tool',
        'evidence_type': 'everbatt_reference_scenario', 'preset': config['preset'], 'process': process,
        'feedstock': scenario.feedstock_type, 'chemistry': scenario.feedstock_chemistry,
        'throughput_tonnes_per_year': scenario.feedstock_tonnes_per_year,
        'location': scenario.manufacturing_location,
        'cost_per_kg_feedstock': metric('Recycling cost'),
        'revenue_per_kg_feedstock': metric('Recycling revenue'),
        'energy_mj_per_kg_feedstock': metric('Recycling total energy'),
        'water_gal_per_kg_feedstock': metric('Recycling water'),
        'gwp_g_co2e_per_kg_feedstock': metric('Recycling GHGs'),
        'currency_basis': '上游EverBatt参考美元与价格假设；未转换为当前中国报价',
        'functional_unit': '1 kg of reference feedstock, NOT 1 kg qualified regenerated graphite',
        'scope': '固定版本社区EverBatt迁移模型的参考案例；沿用上游物料、工艺、产能和价格。不是当前样品的石墨再生流程、完整LCA或投资结论。源码MIT声明与原工作簿/背景数据使用条件分别记录。'}
    return result


def run(config, out, project):
    config = normalize_config(config)
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    result = inventory(config, out) if config['kind'] == 'inventory' else everbatt(config, out, Path(project))
    save(out / 'result.json', result)
    save(out / 'ui_result.json', {'result': result, 'curves': []})
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--project', type=Path, required=True)
    args = parser.parse_args()
    run(json.loads(args.config.read_text(encoding='utf-8')), args.out, args.project)

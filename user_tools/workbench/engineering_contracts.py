"""Dependency-free contract for optional engineering jobs."""
from __future__ import annotations

import copy
import csv
import io
import math


ACTIONS = {
    'ecm_bms': '电热模型与SOC估计', 'mpc': '受约束充电MPC',
    'optimize': 'BoTorch与实验选点', 'eis_joint': '多SOC联合电路辨识', 'eis_grid': 'EIS多工况RC参数表',
    'pack': 'liionpack串并联仿真', 'batteryml': 'BatteryML寿命预测基线',
    'faults': 'CH-BatteryGen故障诊断', 'cycler': 'PyProBE测试数据处理',
    'can': 'foxBMS DBC与虚拟CAN',
    'frontier': 'MOBO-OSD / rMFBO / CAMO',
    'batterylife': 'BatteryLife曲线寿命预测',
    'commercial_validation': 'Panasonic PF商用电芯独立验证',
    'commercial_adaptive': 'PF温度/SOH更新与新工况验证',
    'eis_audit': 'PF原始EIS单位与全谱复核',
    'calb_validation': 'CALB多电芯脉冲与驾驶回放验证',
    'crosscell_validation': 'CALB跨电芯温度OCV与RC验证',
    'tesla_refined': 'Tesla低温OCV补偿与跨电芯验证',
    'stanford_frozen': 'Stanford公开电芯冻结开环案例',
    'eis_hppc_ablation': 'CALB EIS＋HPPC回顾性对照',
    'safety_bench': '设备接入准备与保护逻辑SIL',
}


def default_cell():
    return {'cell_id': 'synthetic-5Ah-1RC', 'capacity_Ah': 5., 'initial_soc': .8,
            'estimated_initial_soc': .65, 'temperature_C': 25., 'mass_kg': .07,
            'heat_capacity_J_kgK': 900., 'heat_transfer_W_K': .2,
            'voltage_min_V': 2.8, 'voltage_max_V': 4.2, 'temperature_max_C': 45.,
            'current_max_A': 5., 'ocv_soc': [0., .2, .5, .8, 1.],
            'ocv_V': [3., 3.35, 3.65, 3.95, 4.18],
            'R0_ohm': .012, 'R_ohm': [.025], 'C_F': [1500.]}


def defaults(action):
    if action not in ACTIONS:
        raise ValueError('未知工程任务。')
    result = {'action': action, 'data_origin': 'synthetic', 'seed': 42, 'cell': default_cell(),
            'steps': 90, 'dt_s': 10., 'voltage_noise_V': .003, 'current_noise_A': .01,
            'current_bias_A': .015, 'algorithm': 'qlognehvi', 'target_soc': .9,
            'horizon': 8, 'Ns': 2, 'Np': 2, 'pack_current_A': 2.,
            'duration_s': 60., 'period_s': 10., 'voltage_guard_V': .01, 'temperature_guard_C': 1.}
    if action == 'eis_grid':
        result.update(rc_branches=1,interpolation='linear',frequency_min_Hz=.5,frequency_max_Hz=1500.,max_train_relative_rms=.15,max_test_relative_rms=.2)
    if action == 'ecm_bms':
        result['filter_rc_mode'] = 'fixed'
        result['filter_ocv_mode'] = 'soc_only'
        result['enable_ukf'] = True
        result['soc_constraint'] = 'strict'
        result['soc_process_variance_per_step'] = 1e-8
    if action == 'frontier':
        result.update(algorithm='mobo_osd', batch_size=2, n_beta=4, train_iterations=80, same_quantity_across_fidelities=True)
    if action == 'batterylife':
        result = dict(action=action, seed=42, architecture='CPMLP', epochs=150, data_origin='public', source='https://data.mendeley.com/datasets/nsc7hnsg4s/2')
    if action in ['commercial_validation','commercial_adaptive','eis_audit']:
        result = dict(action=action, seed=42, data_origin='public', source='https://data.mendeley.com/datasets/wykht8y7tg/1')
    if action == 'calb_validation':
        result = dict(action=action, seed=42, data_origin='public', source='https://doi.org/10.17632/ycx459r5c3.2')
    if action == 'crosscell_validation':
        result = dict(action=action, seed=42, data_origin='public', source='https://doi.org/10.17632/ycx459r5c3.2')
    if action == 'tesla_refined':
        result = dict(action=action, seed=42, data_origin='public', source='https://doi.org/10.5683/SP3/ZVTR4B')
    if action == 'stanford_frozen':
        result = dict(action=action, seed=42, data_origin='public', source='https://osf.io/qsabn/',case='W8_2')
    if action == 'eis_hppc_ablation':
        result = dict(action=action,seed=42,data_origin='public',source='https://doi.org/10.17632/ycx459r5c3.2')
    if action == 'safety_bench':
        result = dict(action=action,seed=42,data_origin='synthetic',limits=dict(voltage_min_V=2.5,voltage_max_V=4.2,temperature_max_C=45.,current_max_A=2.9,stale_timeout_s=.5))
    return result


def finite(value, name, low=None, high=None):
    if isinstance(value, bool):
        raise ValueError(name + '必须为数值。')
    try:
        value = float(value)
    except (ValueError, TypeError):
        raise ValueError(name + '必须为有限数值。') from None
    if not math.isfinite(value) or (low is not None and value < low) or (high is not None and value > high):
        raise ValueError(name + '超出允许范围。')
    return value


def validate_cell(cell):
    if not isinstance(cell, dict):
        raise ValueError('cell必须为参数对象。')
    cell = copy.deepcopy(cell)
    if not str(cell.get('cell_id', '')).strip():
        raise ValueError('必须声明电芯编号/型号。')
    ranges = {'capacity_Ah': (.001, 1000), 'initial_soc': (.001, .999),
              'estimated_initial_soc': (0, 1), 'temperature_C': (-30, 60),
              'mass_kg': (.001, 100), 'heat_capacity_J_kgK': (10, 10000),
              'heat_transfer_W_K': (0, 1000), 'voltage_min_V': (.1, 5),
              'voltage_max_V': (.2, 6), 'temperature_max_C': (-20, 80),
              'current_max_A': (.001, 1000), 'R0_ohm': (1e-8, 10)}
    for key, (low, high) in ranges.items():
        cell[key] = finite(cell.get(key), key, low, high)
    if cell['voltage_min_V'] >= cell['voltage_max_V']:
        raise ValueError('电压下限必须小于上限。')
    if cell['temperature_C'] >= cell['temperature_max_C']:
        raise ValueError('初始温度必须低于温度上限。')
    for key in ['ocv_soc', 'ocv_V', 'R_ohm', 'C_F']:
        values = cell.get(key)
        if not isinstance(values, list) or not values:
            raise ValueError(key + '需要非空数值列表。')
        cell[key] = [finite(v, key) for v in values]
    x, y = cell['ocv_soc'], cell['ocv_V']
    if len(x) != len(y) or not 3 <= len(x) <= 1000 or x[0] != 0 or x[-1] != 1:
        raise ValueError('OCV表需要相同长度、覆盖SOC 0到1的至少3个点。')
    if any(b <= a for a, b in zip(x, x[1:])) or any(b < a for a, b in zip(y, y[1:])):
        raise ValueError('SOC需严格递增；本版OCV需单调不减。')
    if not 1 <= len(cell['R_ohm']) <= 2 or len(cell['R_ohm']) != len(cell['C_F']):
        raise ValueError('支持1RC/2RC，R与C支路数必须一致。')
    if any(v <= 0 for v in cell['R_ohm'] + cell['C_F']):
        raise ValueError('R/C必须为正。')
    if 'isothermal' in cell and not isinstance(cell['isothermal'], bool):
        raise ValueError('isothermal必须为true/false。')
    return cell


def csv_rows(raw):
    if not raw or len(raw) > 8_000_000:
        raise ValueError('CSV文件需非空且不超过8MB。')
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
    if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise ValueError('CSV表头缺失或重复。')
    rows = list(reader)
    if not 2 <= len(rows) <= 50000 or any(None in r or any(v is None for v in r.values()) for r in rows):
        raise ValueError('CSV需要2–50000行且每行列数一致。')
    return rows


def normalize(config, raw=None):
    if not isinstance(config, dict) or not isinstance(config.get('action'), str) or config.get('action') not in ACTIONS:
        raise ValueError('请选择已支持的工程任务。')
    action = config['action']
    result = defaults(action)
    result.update(copy.deepcopy(config))
    # Omitted fields may use demo defaults only for an explicitly synthetic run.
    if result['data_origin'] not in ['synthetic', 'user', 'public']:
        raise ValueError('数据来源只能synthetic/user/public。')
    if result['data_origin'] != 'synthetic' and not config.get('source'):
        raise ValueError('用户/公开数据必须填写来源source。')
    if 'source' in result and (not isinstance(result['source'],str) or not result['source'].strip() or len(result['source'])>2000):
        raise ValueError('source需为非空文字，最多2000字。')
    if action == 'safety_bench':
        if raw is not None or result['data_origin']!='synthetic':raise ValueError('保护逻辑SIL使用合成故障注入，不接收实物控制指令或CSV。')
        limits=result.get('limits')
        if not isinstance(limits,dict):raise ValueError('limits需为保护限值对象。')
        for key,lo,hi in [('voltage_min_V',2.,3.),('voltage_max_V',4.,4.3),('temperature_max_C',30.,60.),('current_max_A',.1,2.9),('stale_timeout_s',.01,10.)]:
            limits[key]=finite(limits.get(key),key,lo,hi)
        seed=finite(result['seed'],'seed',0,2**31-1)
        if seed!=int(seed):raise ValueError('seed必须为整数。')
        result['seed']=int(seed)
        return {k:result[k] for k in defaults(action)}
    if action in ['batterylife','commercial_validation','commercial_adaptive','eis_audit','calb_validation','crosscell_validation','tesla_refined','stanford_frozen','eis_hppc_ablation']:
        if raw is not None or result['data_origin'] != 'public':
            raise ValueError('该入口使用经哈希校验的本地公开数据，不接受CSV/合成数据。')
        if result['source'] != defaults(action)['source']:
            raise ValueError('固定公开数据入口的source需与已校验的数据集一致。')
        seed = finite(result['seed'], 'seed', 0, 2**31-1)
        if seed != int(seed): raise ValueError('seed必须为整数。')
        result['seed'] = int(seed)
        if action=='stanford_frozen' and result['case'] not in ('W8_1','W8_2','W8_3','W5_1'):
            raise ValueError('Stanford案例仅支持W8_1/W8_2/W8_3/W5_1。')
        if action == 'batterylife':
            if result['architecture'] not in ['CPMLP','CPTransformer']:
                raise ValueError('当前验证的BatteryLife架构为CPMLP、CPTransformer。')
            epochs = finite(result['epochs'], 'epochs', 5, 500)
            if epochs != int(epochs): raise ValueError('epochs必须为整数。')
            result['epochs'] = int(epochs)
        return {k:result[k] for k in defaults(action)}
    if result['data_origin'] != 'synthetic' and action in ['ecm_bms', 'mpc']:
        if set(default_cell()) - set(config.get('cell', {})):
            raise ValueError('非合成任务必须完整提供电芯参数与OCV表，不使用演示参数补缺。')
    result['cell'] = validate_cell(result['cell'])
    if action == 'ecm_bms' and result.get('filter_rc_mode') not in ('fixed', 'estimated_grid', 'estimated_grid_jacobian'):
        raise ValueError('filter_rc_mode仅支持fixed、estimated_grid或estimated_grid_jacobian。')
    if action == 'ecm_bms' and result.get('filter_ocv_mode') not in ('soc_only','soc_temperature'):
        raise ValueError('filter_ocv_mode仅支持soc_only或soc_temperature。')
    if action == 'ecm_bms':
        result['soc_process_variance_per_step']=finite(result['soc_process_variance_per_step'],'soc_process_variance_per_step',0.,1e-3)
        if not isinstance(result['enable_ukf'],bool):raise ValueError('enable_ukf必须为true或false。')
        if result.get('soc_constraint') not in ('strict','project'):
            raise ValueError('soc_constraint仅支持strict或project。')
        if result['soc_constraint']=='project' and result['enable_ukf']:
            raise ValueError('SOC投影当前仅支持EKF，请设置enable_ukf=false。')
    if result['data_origin'] != 'synthetic' and action in ['ecm_bms', 'mpc'] and result['cell']['cell_id'].startswith('synthetic-'):
        raise ValueError('用户电芯需要填写实际电芯编号，不能沿用合成电芯型号。')
    if action == 'pack' and result['data_origin'] == 'user':
        raise ValueError('电池包入口当前使用Chen2020参考电芯，请选择合成或公开参考模式；尚未校准用户电芯。')
    for key, low, high in [('steps', 5, 1000), ('horizon', 2, 30), ('Ns', 1, 8), ('Np', 1, 8), ('seed', 0, 2**31-1)]:
        value = finite(result[key], key, low, high)
        if value != int(value):
            raise ValueError(key + '必须为整数。')
        result[key] = int(value)
    for key, low, high in [('dt_s', .1, 120), ('duration_s', 20, 600), ('period_s', 1, 60),
                           ('voltage_noise_V', 1e-6, .2), ('current_noise_A', 0, 2),
                           ('voltage_guard_V', 0, .2), ('temperature_guard_C', 0, 10),
                           ('current_bias_A', -2, 2), ('target_soc', .01, .99), ('pack_current_A', .01, 50)]:
        result[key] = finite(result[key], key, low, high)
    if result['Ns'] * result['Np'] > 16:
        raise ValueError('本地交互电池包最多16个单体。')
    if action == 'mpc' and result['steps'] > 180:
        raise ValueError('交互MPC单次最多180步，请缩短时长或增加步长。')
    if action == 'optimize' and result['algorithm'] not in ['qlognehvi', 'hvkg', 'psbax', 'mfkg', 'mfmes', 'gibbon', 'qlogei', 'dynmeanbo', 'safeopt']:
        raise ValueError('未知实验选点算法。')
    if action == 'frontier':
        if result['algorithm'] not in ['mobo_osd', 'rmfbo', 'camo']:
            raise ValueError('未知前沿选点算法。')
        for key, low, high in [('batch_size', 1, 4), ('n_beta', 4, 12), ('train_iterations', 10, 300)]:
            result[key] = int(finite(result[key], key, low, high))
    if action == 'batterylife':
        if result['architecture'] not in ['CPMLP', 'CPTransformer']:
            raise ValueError('当前验证的BatteryLife架构为CPMLP、CPTransformer。')
        result['epochs'] = int(finite(result['epochs'], 'epochs', 5, 500))
    if action in ['batterylife', 'commercial_validation'] and (raw is not None or result['data_origin'] != 'public'):
        raise ValueError('该入口使用经哈希校验的本地公开数据，不接受CSV/合成数据。')
    if raw is not None:
        if action in ['mpc', 'pack']:
            raise ValueError('该仿真任务使用参数配置，不读取CSV。')
        csv_rows(raw)
    elif result['data_origin'] != 'synthetic' and action not in ['mpc', 'pack', 'can', 'batterylife', 'commercial_validation']:
        raise ValueError('该任务需要上传CSV原始数据。')
    # Device transport is deliberately named, not a free-form backend or command.
    if action == 'can' and result.get('interface', 'virtual') != 'virtual':
        raise ValueError('工作站目前只执行虚拟CAN和日志回放，实物驱动需另行设备配置。')
    return result


def catalog():
    return [{'action': key, 'name': label, 'defaults': defaults(key)} for key, label in ACTIONS.items()]

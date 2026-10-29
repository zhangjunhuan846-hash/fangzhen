"""Desktop-side engineering runtime selection and explicit EIS parameter bridge."""
import copy
import hashlib
import json
from pathlib import Path

from user_tools.workbench.engineering_contracts import ACTIONS, catalog, finite


RUNTIME_KEYS = {'pack': 'pack', 'batteryml': 'batteryml_legacy', 'frontier': 'frontier', 'batterylife': 'frontier'}


def runtime_manifest(project):
    if not project:
        return {}
    path = Path(project) / 'data/engineering_runtime.local.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def runtime_for(project, action):
    if action not in ACTIONS:
        raise ValueError('未知工程任务。')
    key = RUNTIME_KEYS.get(action, 'engineering')
    manifest = runtime_manifest(project)
    path = manifest.get('runtimes', {}).get(key, {}).get('python')
    if not path or not path.startswith('/home/') or not path.endswith('/bin/python') or any(c in path for c in ['\n', '\r', '\x00']):
        raise ValueError('工程环境尚未配置，请运行“安装工程仿真扩展.bat”。')
    return path


def public_catalog(project):
    entries = catalog()
    for entry in entries:
        try:
            runtime_for(project, entry['action'])
            entry['configured'] = True
        except (ValueError, OSError):
            entry['configured'] = False
    return entries


def bridge_adaptive_control(config,parent_result,parent_id,artifact,exported):
    if config.get('action')!='mpc' or parent_result.get('action')!='commercial_adaptive':
        raise ValueError('温度/SOH参数来源需为已完成的同电芯更新验证任务，目标需为MPC。')
    if hashlib.sha256(artifact).hexdigest()!=parent_result.get('frozen_model_sha256'):
        raise ValueError('冻结更新参数文件与父任务哈希不一致。')
    result=copy.deepcopy(exported)
    for key in ['seed','horizon','steps','target_soc','dt_s','voltage_guard_V','temperature_guard_C','voltage_noise_V','current_noise_A','current_bias_A']:
        if key in config:result[key]=copy.deepcopy(config[key])
    result['adaptive_parameter_source']={'job_id':parent_id,'frozen_model_sha256':hashlib.sha256(artifact).hexdigest(),
         'table_replay_source_verified':True,
         'scope':'prior completed discharge calibration; SOC-dependent RC plant, fixed operating-point controller;25C charging simulation only'}
    return result


def bridge_eis(config, result, parent_id, artifact):
    config = copy.deepcopy(config)
    if config.get('same_cell_eis_confirmed') is not True:
        raise ValueError('请核对EIS谱与电芯参数属于同一电芯。')
    if config['action'] not in ['ecm_bms', 'mpc']:
        raise ValueError('EIS参数桥接目前仅用于电热/SOC回放与MPC。')
    if result.get('kind') != 'eis_fit' or result.get('engine') != 'impedance.py':
        raise ValueError('请选择已完成的RC电路拟合。')
    soc = finite(config.get('eis_operating_soc'), 'EIS工况SOC', 0, 1)
    temp = finite(config.get('eis_operating_temperature_C'), 'EIS工况温度', -30, 60)
    if abs(config['cell']['initial_soc']-soc) > .05 or abs(config['cell']['temperature_C']-temp) > 1:
        raise ValueError('单谱RC桥接要求初始SOC距EIS工况不超过0.05，温度距工况不超过1°C；跨工况请提供参数表。')
    values = {p['name']: finite(p['value'], p['name'], 1e-15) for p in result['parameters']}
    branches = 2 if 'R2' in values else 1
    config['cell'].update(R0_ohm=values['R0'], R_ohm=[values[f'R{i}'] for i in range(1, branches+1)],
                          C_F=[values[f'C{i}'] for i in range(1, branches+1)])
    config['eis_parameter_source'] = {'job_id': parent_id, 'result_sha256': hashlib.sha256(artifact).hexdigest(),
         'source_sha256': result.get('source_sha256'), 'operating_soc': soc, 'operating_temperature_C': temp,
         'assumption': 'local fixed RC extrapolated over run; OCV/capacity/thermal parameters supplied separately',
         'lin_kk_status': result.get('lin_kk', {}).get('status'), 'identifiability': result.get('parameter_identifiability')}
    return config


def bridge_eis_grid(config,result,parent_id,artifact):
    """Use the verified EIS table only for open-loop/estimator replay, not MPC."""
    config=copy.deepcopy(config)
    if config.get('action')!='ecm_bms' or config.get('same_cell_eis_confirmed') is not True:
        raise ValueError('参数表仅能用于SOC回放，且需确认同一电芯。')
    if result.get('action')!='eis_grid' or not result.get('grid_usable_for_replay'):
        raise ValueError('EIS参数表尚未通过训练谱、留出谱及Lin-KK筛查。')
    if config.get('data_origin')!=result.get('data_origin'):
        raise ValueError('EIS参数表与回放的数据来源类型须一致。')
    digest=hashlib.sha256(artifact).hexdigest()
    if digest!=result.get('rc_grid_sha256'):raise ValueError('EIS参数表文件校验失败。')
    grid=json.loads(artifact.decode('utf-8'));cell=config['cell']
    if not grid.get('usable_for_replay') or grid['cell_id']!=cell.get('cell_id'):
        raise ValueError('参数表和SOC回放必须是同一电芯编号。')
    table=grid['table'];socs=sorted(set(float(r['soc']) for r in table));temps=sorted(set(float(r['temperature_C']) for r in table))
    if len(socs)*len(temps)!=len(table) or len(socs)<2:raise ValueError('回放需要至少2个SOC节点与完整网格。')
    soc=finite(cell.get('initial_soc'),'initial_soc',socs[0],socs[-1]);temp=finite(cell.get('temperature_C'),'temperature_C',temps[0],temps[-1])
    if len(temps)==1 and cell.get('isothermal') is not True:
        raise ValueError('单温度EIS表仅支持声明isothermal=true的回放。')
    branches=grid.get('rc_branches',1)
    if branches not in (1,2):raise ValueError('不支持的RC支路数。')
    from user_tools.workbench.engineering_rc_grid import make_rc_interpolator
    mode=grid.get('interpolation','linear')
    values=make_rc_interpolator(table,branches,mode)(soc,temp)
    cell.update(R0_ohm=values['R0_ohm'],R_ohm=[values[f'R{i}_ohm'] for i in range(1,branches+1)],
                C_F=[values[f'C{i}_F'] for i in range(1,branches+1)],rc_table=table,rc_interpolation=mode)
    config['eis_grid_source']={'job_id':parent_id,'rc_grid_sha256':digest,'cell_id':grid['cell_id'],
     'scope':'Plant interpolates in the measured SOC/temperature grid without extrapolation; filter mode is specified separately; EIS-only screening does not validate time-domain or safety.'}
    return config


def bridge_can(config, result, parent_id, artifact, samples):
    if config.get('action') != 'can' or result.get('action') not in ['ecm_bms', 'mpc']:
        raise ValueError('CAN遥测来源需为已完成的SOC估计或MPC任务。')
    if config.get('data_origin') != result.get('data_origin'):
        raise ValueError('CAN数据来源需与遥测父任务相同。')
    if not 2 <= len(samples) <= 1001:
        raise ValueError('CAN遥测需要2–1001个点。')
    config = copy.deepcopy(config)
    config['can_telemetry'] = [{'time_s': finite(r['time_s'], 'time_s', 0),
          'voltage_V': finite(r.get('sensor_voltage_V', r.get('voltage_V')), 'voltage_V', 0, 8.191)} for r in samples]
    config['telemetry_parameter_source'] = {'job_id': parent_id, 'result_sha256': hashlib.sha256(artifact).hexdigest(),
          'voltage_column': 'sensor_voltage_V' if result['action']=='ecm_bms' else 'voltage_V',
          'mapping': 'single cell -> CellVoltage_000 mV, multiplexer 0; other slots marked invalid'}
    return config

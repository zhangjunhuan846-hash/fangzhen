"""Tune SOC process noise on seen cells, then score two new held-out cells."""
from pathlib import Path
import hashlib
import json
import time
import numpy as np
from user_tools.workbench.engineering_common import ROOT,finish,save,write_csv
from user_tools.workbench import engineering_calb_validation as base
from user_tools.workbench.engineering_calb_validation_v2 import verify_extra,open_loop,audit_eis

DEV=base.DEVELOP+base.TEST+base.EXTRA_CELLS
TEST=base.EXTRA2_CELLS
CANDIDATES=(1e-10,1e-8,1e-7,1e-6)
SIGMA=.005


def verify_sources():
    verify_extra()
    path=base.EXTRA2_DATA/'manifest.json';manifest=json.loads(path.read_text(encoding='utf8'))
    if manifest['failures'] or tuple(manifest['cells'])!=TEST:raise ValueError('额外留出电芯清单不符。')
    for item in manifest['files']:
        f=ROOT/item['path']
        if not f.is_file() or hashlib.sha256(f.read_bytes()).hexdigest()!=item['sha256']:
            raise ValueError('额外留出文件缺失或哈希不符：'+str(f))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_calb_v3(config,out):
    started=time.perf_counter();base.TIME_AUDIT.clear();manifest_hash=verify_sources();out=Path(out);out.mkdir(parents=True,exist_ok=True)
    protocol_path=ROOT/'configs/calb_bms_protocol_v3_20261029.json'
    protocol=json.loads(protocol_path.read_text(encoding='utf8'))
    if (tuple(protocol['development_cells'])!=DEV or tuple(protocol['new_test_cells'])!=TEST or
        tuple(protocol['soc_process_variance_candidates_per_step'])!=CANDIDATES or protocol['voltage_noise_V']!=SIGMA):
        raise ValueError('CALB噪声选择协议与实现不一致。')
    models={};refs={};nodes={};eis=[]
    for cell in DEV+TEST:
        models[cell],refs[cell],nodes[cell]=base.fit_cell(cell)
        for temp in base.TEMPS:eis.extend(audit_eis(cell,temp,refs[cell][temp]))
    write_csv(out/'calb_eis_inventory.csv',eis)
    save(out/'calb_calibration.json',{'models':models,'hppc_nodes':nodes,'eis_inventory':eis,
        'dev_cells':DEV,'fresh_test_cells':TEST,'calibration':'each cell pre-driving HPPC and C20; not zero-shot',
        'soc_reference':'C20 voltage initial anchor plus integrated current; approximate SOC proxy',
        'eis_role':'after driving, inventory only; no EIS-derived parameters used for driving prediction'})
    # Select only using the six already-observed development cells. Limit voltage
    # regression to 10% compared with q=1e-8, then minimize SOC proxy error.
    candidates=[]
    for cell in DEV:
        for temp in base.TEMPS:
            for drive in base.DRIVES:
                for index,window in enumerate(base.windows(cell,temp,drive,refs[cell][temp])):
                    for q in CANDIDATES:
                        m,_=base.score_window(models[cell],temp,window,'fixed_start',SIGMA,q)
                        candidates.append({'cell_id':cell,'temperature_C':temp,'drive':drive,'window':index+1,
                            'soc_process_variance_per_step':q,'soc_proxy_rmse':m['ekf_rmse_soc'],
                            'prior_voltage_rmse_mV':m['ekf_prior_voltage_rmse_V']*1000})
                print('selection',cell,temp,drive,flush=True)
    summary=[]
    for q in CANDIDATES:
        group=[r for r in candidates if r['soc_process_variance_per_step']==q]
        summary.append({'soc_process_variance_per_step':q,'windows':len(group),
            'mean_soc_proxy_rmse':float(np.mean([r['soc_proxy_rmse'] for r in group])),
            'mean_prior_voltage_rmse_mV':float(np.mean([r['prior_voltage_rmse_mV'] for r in group]))})
    baseline=next(x for x in summary if x['soc_process_variance_per_step']==1e-8)
    eligible=[x for x in summary if x['mean_prior_voltage_rmse_mV']<=1.1*baseline['mean_prior_voltage_rmse_mV']]
    best=min(eligible,key=lambda x:x['mean_soc_proxy_rmse']);selected=best['soc_process_variance_per_step']
    save(out/'calb_pretest_freeze.json',{'selected_soc_process_variance_per_step':selected,
        'selection':'minimum mean development EKF SOC proxy RMSE subject to <=10% increase in one-step voltage RMSE',
        'candidates':summary,'voltage_noise_V':SIGMA,'mode_selection':'fixed_start frozen from preceding development experiment',
        'fresh_test_cells':TEST,'holdout_drive_signals_decoded':False,
        'protocol_sha256':hashlib.sha256(protocol_path.read_bytes()).hexdigest()})
    write_csv(out/'calb_development_candidates.csv',candidates)
    records=[];traces=[];pulse_records=[]
    for cell in TEST:
        for temp in base.TEMPS:
            for window in base.pulse_windows(cell,temp,refs[cell][temp]):
                for name,mode,q in [('fixed_baseline','fixed_start',1e-8),('fixed_tuned','fixed_start',selected),
                                    ('grid_tuned','estimated_grid',selected)]:
                    m,_=base.score_window(models[cell],temp,window,mode,SIGMA,q)
                    pulse_records.append({'cell_id':cell,'temperature_C':temp,'target_soc':window['target_soc'],
                        'start_s':window['start_s'],'pulse_amplitude_A':window['pulse_amplitude_A'],'mode':name,'ekf_prior_voltage_rmse_mV':m['ekf_prior_voltage_rmse_V']*1000,
                        'ekf_soc_proxy_rmse':m['ekf_rmse_soc'],'open_loop_voltage_rmse_mV':open_loop(models[cell],temp,window,mode)})
            for drive in base.DRIVES:
                for index,window in enumerate(base.windows(cell,temp,drive,refs[cell][temp])):
                    for name,mode,q in [('fixed_baseline','fixed_start',1e-8),('fixed_tuned','fixed_start',selected),
                                        ('grid_tuned','estimated_grid',selected)]:
                        m,rows=base.score_window(models[cell],temp,window,mode,SIGMA,q)
                        records.append({'cell_id':cell,'temperature_C':temp,'drive':drive,'window':index+1,'mode':name,
                            'start_s':window['start_s'],'initial_soc_proxy':float(window['soc_proxy'][0]),
                            'ekf_prior_voltage_rmse_mV':m['ekf_prior_voltage_rmse_V']*1000,
                            'ukf_prior_voltage_rmse_mV':m['ukf_prior_voltage_rmse_V']*1000,
                            'ekf_soc_proxy_rmse':m['ekf_rmse_soc'],'ukf_soc_proxy_rmse':m['ukf_rmse_soc'],
                            'open_loop_voltage_rmse_mV':open_loop(models[cell],temp,window,mode)})
                        traces.extend({'cell_id':cell,'temperature_C':temp,'drive':drive,'window':index+1,'mode':name,
                            'time_s':r['time_s'],'current_A':r['sensor_current_A'],'measured_voltage_V':r['sensor_voltage_V'],
                            'ekf_prior_voltage_V':r['voltage_ekf_prior_V'],'ukf_prior_voltage_V':r['voltage_ukf_prior_V'],
                            'soc_proxy':r['soc_reference'],'soc_ekf':r['soc_ekf'],'soc_ukf':r['soc_ukf']} for r in rows)
                print('fresh_test',cell,temp,drive,flush=True)
    write_csv(out/'calb_metrics.csv',records);write_csv(out/'calb_traces.csv',traces);write_csv(out/'calb_pulse_metrics.csv',pulse_records)
    keys=('ekf_prior_voltage_rmse_mV','ukf_prior_voltage_rmse_mV','ekf_soc_proxy_rmse','ukf_soc_proxy_rmse','open_loop_voltage_rmse_mV')
    results=[]
    for name in ('fixed_baseline','fixed_tuned','grid_tuned'):
        group=[r for r in records if r['mode']==name]
        results.append({'mode':name,'windows':len(group),**{key:float(np.mean([r[key] for r in group])) for key in keys}})
    pulse_summary=[{'mode':name,'windows':sum(r['mode']==name for r in pulse_records),
                    **{k:float(np.mean([r[k] for r in pulse_records if r['mode']==name])) for k in ('ekf_prior_voltage_rmse_mV','ekf_soc_proxy_rmse','open_loop_voltage_rmse_mV')}}
                   for name in ('fixed_baseline','fixed_tuned','grid_tuned')]
    save(out/'calb_validation.json',{'summary':results,'records':records,'pulse_summary':pulse_summary,'pulse_records':pulse_records,'selection':summary,'time_audit':base.TIME_AUDIT,
        'new_manifest_sha256':manifest_hash,'scope':'independent new driving cells after same-cell pulse calibration; SOC proxy, 600s windows; no hardware'})
    metrics={'fresh_test_cells':len(TEST),'fresh_test_windows':len(records)//3,'selected_soc_process_variance_per_step':selected,
             'elapsed_s':time.perf_counter()-started}
    for row in results:
        for key in ('ekf_soc_proxy_rmse','ekf_prior_voltage_rmse_mV','open_loop_voltage_rmse_mV'):
            metrics[row['mode']+'_'+key]=row[key]
    for row in pulse_summary:
        metrics[row['mode']+'_pulse_prior_voltage_rmse_mV']=row['ekf_prior_voltage_rmse_mV']
    return finish(config,out,{'kind':'engineering','title':'CALB脉冲/动态回放与滤波参数验证',
        'metrics':metrics,'comparisons':results,'details':{'scope':'先用同电芯HPPC和C/20标定；6个已见电芯选取滤波噪声，两个新电芯驾驶工况留出。SOC为近似代理，开环与在线预测分开计分。'}},
        records,packages=['sox','scipy','numpy'])

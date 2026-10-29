"""CALB benchmark with development-selected EKF and fresh cell holdouts."""
from pathlib import Path
import hashlib
import json
import time
import numpy as np
from scipy.io import loadmat
from user_tools.workbench.engineering_common import ROOT,finish,save,write_csv
from user_tools.workbench.engineering_bms import ocv_function
from user_tools.workbench.engineering_rc_grid import make_rc_interpolator
from user_tools.workbench import engineering_calb_validation as base

DEV=base.DEVELOP+base.TEST
TEST=base.EXTRA_CELLS
MODES=('fixed_start','estimated_grid','estimated_grid_jacobian')


def verify_extra():
    base.verify_data()
    file=base.EXTRA_DATA/'manifest.json';m=json.loads(file.read_text(encoding='utf8'))
    if m['failures'] or tuple(m['cells'])!=TEST:raise ValueError('新增留出电芯清单不符。')
    for item in m['files']:
        path=ROOT/item['path']
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
            raise ValueError('新增留出原始文件缺失或哈希不符：'+str(path))
    return hashlib.sha256(file.read_bytes()).hexdigest()


def open_loop(cell,temp,window,mode):
    """No measured voltage is consumed after initialization."""
    lookup=make_rc_interpolator(cell['rc_table'],1);ocv=ocv_function(cell)
    soc=float(window['soc_proxy'][0]-.04);eta=0.;fixed=lookup(soc,temp);pred=[]
    for k,current in enumerate(window['current']):
        if k:
            pars=fixed if mode=='fixed_start' else lookup(soc,temp)
            decay=np.exp(-1/(pars['R1_ohm']*pars['C1_F']))
            eta=decay*eta+pars['R1_ohm']*(1-decay)*current
            soc-=current/(3600*cell['capacity_Ah'])
        pars=fixed if mode=='fixed_start' else lookup(soc,temp)
        pred.append(ocv(soc)-eta-current*pars['R0_ohm'])
    return float(np.sqrt(np.mean((np.array(pred)-window['voltage'])**2))*1000)


def audit_eis(cell,temp,reference):
    root=(base.EXTRA3_DATA if cell in base.EXTRA3_CELLS else base.EXTRA2_DATA if cell in base.EXTRA2_CELLS
          else base.EXTRA_DATA if cell in base.EXTRA_CELLS else base.DATA)
    data=loadmat(root/f'Temperature_{temp}C'/'eis_test'/(cell+'.mat'),simplify_cells=True)['Data']
    spectra=data if isinstance(data,list) else [data]
    result=[]
    for index,spectrum in enumerate(spectra):
        if not isinstance(spectrum,dict):raise ValueError('EIS spectrum struct invalid')
        z=spectrum['meas'];f=np.asarray(z['Frequency'],float);re=np.asarray(z['Zreal'],float);im=np.asarray(z['Zimg'],float);mag=np.asarray(z['Zmod'],float)
        if len(f)<12 or not all(np.isfinite(a).all() for a in (f,re,im,mag)):raise ValueError('EIS measurement invalid')
        ocv=float(spectrum['OCV_value'])
        result.append({'cell_id':cell,'temperature_C':temp,'spectrum_index':index+1,'points':len(f),
            'reference_voltage_V':ocv,'inferred_soc_from_c20_voltage':float(np.interp(ocv,reference['reference_voltage'],reference['reference_soc'])),
            'max_abs_magnitude_consistency_ohm':float(np.max(abs(np.hypot(re,im)-mag)))})
    return result


def run_calb_v2(config,out):
    started=time.perf_counter();base.TIME_AUDIT.clear();extra_hash=verify_extra();out=Path(out);out.mkdir(parents=True,exist_ok=True)
    models={};refs={};nodes={};eis=[]
    # Same-cell pre-driving pulse calibration is permitted also for holdout cells;
    # holdout drive voltages remain unopened during calibration and selection.
    for cell in DEV+TEST:
        models[cell],refs[cell],nodes[cell]=base.fit_cell(cell)
        for temp in base.TEMPS:eis.extend(audit_eis(cell,temp,refs[cell][temp]))
    save(out/'calb_calibration.json',{'models':models,'hppc_nodes':nodes,'eis_inventory':eis,
        'dev_cells':DEV,'test_cells':TEST,'EIS_role':'EIS collected after drive cycle; metadata audit only, not used for prospective RC calibration',
        'temperature':'nominal chamber setpoint','reference':'C/20 voltage anchor and integrated current, proxy only'})
    # The noise value was frozen in the first experiment on 59294/25C/WLTP.
    protocol_path=ROOT/'configs/calb_bms_protocol_20261029.json'
    protocol=json.loads(protocol_path.read_text(encoding='utf8'))
    if tuple(protocol['development_cells'])!=DEV or tuple(protocol['fresh_test_cells'])!=TEST:
        raise ValueError('CALB协议电芯与实现不一致。')
    sigma=float(protocol['voltage_noise_V'])
    records=[];traces=[]
    def evaluate(role,cells):
        for cell in cells:
            for temp in base.TEMPS:
                for drive in base.DRIVES:
                    for index,window in enumerate(base.windows(cell,temp,drive,refs[cell][temp])):
                        for mode in MODES:
                            score,rows=base.score_window(models[cell],temp,window,mode,sigma)
                            results={'role':role,'cell_id':cell,'temperature_C':temp,'drive':drive,'window':index+1,
                                'mode':mode,'start_s':window['start_s'],'initial_soc_proxy':float(window['soc_proxy'][0]),
                                'ekf_prior_voltage_rmse_mV':score['ekf_prior_voltage_rmse_V']*1000,
                                'ukf_prior_voltage_rmse_mV':score['ukf_prior_voltage_rmse_V']*1000,
                                'ekf_soc_proxy_rmse':score['ekf_rmse_soc'],'ukf_soc_proxy_rmse':score['ukf_rmse_soc'],
                                'open_loop_voltage_rmse_mV':open_loop(models[cell],temp,window,mode)}
                            records.append(results)
                            traces.extend({'role':role,'cell_id':cell,'temperature_C':temp,'drive':drive,'window':index+1,
                                'mode':mode,'time_s':r['time_s'],'current_A':r['sensor_current_A'],
                                'measured_voltage_V':r['sensor_voltage_V'],'ekf_prior_voltage_V':r['voltage_ekf_prior_V'],
                                'ukf_prior_voltage_V':r['voltage_ukf_prior_V'],'soc_proxy':r['soc_reference'],
                                'soc_ekf':r['soc_ekf'],'soc_ukf':r['soc_ukf']} for r in rows)
                    print(role,cell,temp,drive,flush=True)
    evaluate('development',DEV)
    dev_means={mode:float(np.mean([r['ekf_prior_voltage_rmse_mV'] for r in records if r['mode']==mode])) for mode in MODES}
    chosen=min(dev_means,key=dev_means.get)
    frozen={'selection':'lowest mean development EKF one-step voltage RMSE','selected_mode':chosen,'development_means_mV':dev_means,
            'voltage_noise_V':sigma,'noise_frozen_source_sha256':protocol['previous_selection_artifact_sha256'],
            'protocol_sha256':hashlib.sha256(protocol_path.read_bytes()).hexdigest(),
            'new_test_cells':TEST,'test_drive_signals_decoded':False}
    save(out/'calb_pretest_freeze.json',frozen)
    evaluate('test',TEST)
    write_csv(out/'calb_metrics.csv',records);write_csv(out/'calb_traces.csv',traces);write_csv(out/'calb_eis_inventory.csv',eis)
    summaries=[]
    metrics_keys=('ekf_prior_voltage_rmse_mV','ukf_prior_voltage_rmse_mV','ekf_soc_proxy_rmse','ukf_soc_proxy_rmse','open_loop_voltage_rmse_mV')
    for role in ('development','test'):
        for mode in MODES:
            group=[r for r in records if r['role']==role and r['mode']==mode]
            summaries.append({'role':role,'mode':mode,'windows':len(group),**{k:float(np.mean([r[k] for r in group])) for k in metrics_keys}})
    save(out/'calb_validation.json',{'summary':summaries,'records':records,'selection':frozen,'time_audit':base.TIME_AUDIT,
        'original_manifest_sha256':hashlib.sha256((base.DATA/'manifest.json').read_bytes()).hexdigest(),
        'new_manifest_sha256':extra_hash,'eis_inventory':eis,
        'scope':'C20-based approximate SOC anchor; one-step filter voltage uses prior measured voltages; open loop uses none after initialization; independent held-out cells each have their own earlier HPPC/C20 calibration'})
    metrics={'new_test_cells':len(TEST),'new_test_windows':sum(r['role']=='test' for r in records)//len(MODES),
             'selected_mode':chosen,'selected_voltage_noise_V':sigma,'elapsed_s':time.perf_counter()-started}
    for s in summaries:
        if s['role']=='test':
            for k in ('ekf_prior_voltage_rmse_mV','ekf_soc_proxy_rmse','open_loop_voltage_rmse_mV'):
                metrics[s['mode']+'_'+k]=s[k]
    return finish(config,out,{'kind':'engineering','title':'CALB匹配脉冲/驾驶与电芯留出验证',
        'metrics':metrics,'comparisons':summaries,'details':{'scope':'先用各电芯C/20和HPPC标定，开发集选择滤波模式，再评价两个新电芯驾驶窗口。SOC为近似代理；开环和在线单步预测分开计分。EIS晚于驾驶，仅核对，不用于预测标定。'}},
        records,packages=['sox','scipy','numpy'])

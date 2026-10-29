"""Train on six CALB cells, select temperature dependence on two, test three."""
from pathlib import Path
import copy
import hashlib
import json
import time
import numpy as np
from user_tools.workbench import engineering_calb_validation as base
from user_tools.workbench.engineering_calb_validation_v2 import verify_extra,open_loop
from user_tools.workbench.engineering_calb_validation_v3 import verify_sources
from user_tools.workbench.engineering_bms import estimate_stream
from user_tools.workbench.engineering_contracts import defaults
from user_tools.workbench.engineering_common import ROOT,finish,save,write_csv
from user_tools.workbench.engineering_rc_grid import make_rc_interpolator

TRAIN=base.DEVELOP+base.TEST+base.EXTRA_CELLS
DEV=base.EXTRA2_CELLS
TEST=base.EXTRA3_CELLS
VARIANTS=('reference_25','ocv_temperature','rc_temperature','ocv_and_rc_temperature')


def verify_all():
    verify_sources()
    path=base.EXTRA3_DATA/'manifest.json';manifest=json.loads(path.read_text(encoding='utf8'))
    if manifest['failures'] or tuple(manifest['cells'])!=TEST:raise ValueError('CALB新留出清单不符。')
    for item in manifest['files']:
        file=ROOT/item['path']
        if not file.exists() or hashlib.sha256(file.read_bytes()).hexdigest()!=item['sha256']:
            raise ValueError('新电芯文件缺失或哈希不符：'+str(file))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pooled_model():
    nodes={};capacities=[]
    for cell in TRAIN:
        _,refs,per_temp=base.fit_cell(cell);nodes[cell]=per_temp;capacities.append(refs[25]['capacity'])
    all_nodes=[nodes[cell][temp] for cell in TRAIN for temp in base.TEMPS]
    lo=max(x[0]['soc'] for x in all_nodes)+1e-5;hi=min(x[-1]['soc'] for x in all_nodes)-1e-5
    if not lo<.25 or not hi>.9:raise ValueError('跨电芯标定的SOC覆盖不足。')
    grid=np.linspace(lo,hi,12);table=[];ocv_table=[]
    for soc in grid:
        for temp in base.TEMPS:
            vals={key:[] for key in ('R0_ohm','R1_ohm','C1_F','pseudo_ocv_V')}
            for cell in TRAIN:
                rows=nodes[cell][temp];sx=[r['soc'] for r in rows]
                for key in vals:vals[key].append(float(np.interp(soc,sx,[r[key] for r in rows])))
            table.append({'soc':float(soc),'temperature_C':float(temp),
                **{key:float(np.median(vals[key])) for key in ('R0_ohm','R1_ohm','C1_F')}})
            ocv_table.append({'soc':float(soc),'temperature_C':float(temp),'ocv_V':float(np.median(vals['pseudo_ocv_V']))})
    # Small noise in fitted local OCV values may create non-monotone curves.
    for temp in base.TEMPS:
        subset=[r for r in ocv_table if r['temperature_C']==temp]
        for row,v in zip(subset,np.maximum.accumulate([r['ocv_V'] for r in subset])):row['ocv_V']=float(v)
    ocv25=[r['ocv_V'] for r in ocv_table if r['temperature_C']==25]
    cfg=defaults('ecm_bms')['cell'];cfg.update(cell_id='CALB-pooled',capacity_Ah=float(np.median(capacities)),
        ocv_soc=[0.,*grid.tolist(),1.],ocv_V=[ocv25[0],*ocv25,ocv25[-1]],
        rc_table=table,ocv_temperature_table=ocv_table,rc_interpolation='linear')
    return cfg,nodes


def evaluate_window(model,temp,window,variant):
    cfg=defaults('ecm_bms');cfg['cell']=copy.deepcopy(model);cell=cfg['cell'];cell['temperature_C']=temp
    initial=float(window['soc_proxy'][0]-.04);cell['estimated_initial_soc']=initial
    use_rc=variant in ('rc_temperature','ocv_and_rc_temperature')
    use_ocv=variant in ('ocv_temperature','ocv_and_rc_temperature')
    p=make_rc_interpolator(cell['rc_table'],1)(initial,temp if use_rc else 25.)
    cell.update(R0_ohm=p['R0_ohm'],R_ohm=[p['R1_ohm']],C_F=[p['C1_F']])
    cfg['filter_rc_mode']='fixed';cfg['filter_ocv_mode']='soc_temperature' if use_ocv else 'soc_only'
    cfg['voltage_noise_V']=.005;cfg['current_noise_A']=0.
    rows=[{'time_s':float(k),'sensor_current_A':float(i),'sensor_voltage_V':float(v),
           'measured_temperature_C':float(temp),'soc_reference':float(s)}
          for k,(i,v,s) in enumerate(zip(window['current'],window['voltage'],window['soc_proxy']))]
    output,metrics=estimate_stream(cfg,rows)
    return metrics,output


def run_crosscell(config,out):
    start=time.perf_counter();hash_new=verify_all();out=Path(out);out.mkdir(parents=True,exist_ok=True)
    model,nodes=pooled_model()
    save(out/'pooled_model.json',{'training_cells':TRAIN,'development_cells':DEV,'test_cells':TEST,
        'model':model,'training_pulses':nodes,'scope':'pooled median of six cells; temperature OCV and RC derive solely from training-cell HPPC'})
    records=[];traces=[]
    def evaluate(role,cells):
        for cell in cells:
            for temp in base.TEMPS:
                reference=base.slow_reference(cell,temp)
                for drive in base.DRIVES:
                    for index,window in enumerate(base.windows(cell,temp,drive,reference)):
                        for variant in VARIANTS:
                            status='ok';failure='';rows=[]
                            try:metrics,rows=evaluate_window(model,temp,window,variant)
                            except ValueError as exc:
                                if '不支持外推' not in str(exc) and 'SOC超出' not in str(exc):raise
                                status='outside_calibrated_domain';failure=str(exc);metrics=None
                            records.append({'role':role,'cell_id':cell,'temperature_C':temp,'drive':drive,'window':index+1,
                                'variant':variant,'start_s':window['start_s'],'status':status,'failure':failure,
                                'ekf_prior_voltage_rmse_mV':metrics['ekf_prior_voltage_rmse_V']*1000 if metrics else None,
                                'ukf_prior_voltage_rmse_mV':metrics['ukf_prior_voltage_rmse_V']*1000 if metrics else None,
                                'ekf_soc_proxy_rmse':metrics['ekf_rmse_soc'] if metrics else None,'ukf_soc_proxy_rmse':metrics['ukf_rmse_soc'] if metrics else None})
                            traces.extend({'role':role,'cell_id':cell,'temperature_C':temp,'drive':drive,'window':index+1,'variant':variant,
                                'time_s':r['time_s'],'voltage_V':r['sensor_voltage_V'],'current_A':r['sensor_current_A'],
                                'ekf_prior_voltage_V':r['voltage_ekf_prior_V'],'soc_proxy':r['soc_reference'],'soc_ekf':r['soc_ekf']} for r in rows)
                    print(role,cell,temp,drive,flush=True)
    evaluate('development',DEV)
    if any(r['status']!='ok' for r in records):raise ValueError('开发工况有越界，不能选择候选。')
    scores=[{'variant':name,'mean_ekf_prior_voltage_rmse_mV':float(np.mean([r['ekf_prior_voltage_rmse_mV'] for r in records if r['variant']==name])),
              'mean_ekf_soc_proxy_rmse':float(np.mean([r['ekf_soc_proxy_rmse'] for r in records if r['variant']==name]))} for name in VARIANTS]
    chosen=min(scores,key=lambda r:r['mean_ekf_prior_voltage_rmse_mV'])['variant']
    save(out/'pretest_freeze.json',{'scores':scores,'selected_variant':chosen,'test_cells':TEST,
        'test_drive_signals_decoded':False,'selection':'minimum development one-step voltage RMSE; SOC proxy recorded separately'})
    evaluate('test',TEST)
    write_csv(out/'crosscell_metrics.csv',records);write_csv(out/'crosscell_traces.csv',traces)
    summaries=[]
    for role in ('development','test'):
        for variant in VARIANTS:
            group=[r for r in records if r['role']==role and r['variant']==variant]
            valid=[r for r in group if r['status']=='ok']
            summaries.append({'role':role,'variant':variant,'windows':len(group),'valid_windows':len(valid),'failed_windows':len(group)-len(valid),
                **{key:(float(np.mean([r[key] for r in valid])) if valid else None) for key in ('ekf_prior_voltage_rmse_mV','ukf_prior_voltage_rmse_mV','ekf_soc_proxy_rmse','ukf_soc_proxy_rmse')}})
    save(out/'crosscell_validation.json',{'summary':summaries,'records':records,'test_manifest_sha256':hash_new,
        'scope':'pooled source-cell HPPC only; target C20 used only to generate reference and controlled initial offset; no target HPPC used'})
    metrics={'test_cells':len(TEST),'test_windows':sum(r['role']=='test' for r in records)//len(VARIANTS),
             'selected_variant':chosen,'elapsed_s':time.perf_counter()-start}
    for entry in summaries:
        if entry['role']=='test':
            metrics[entry['variant']+'_ekf_prior_voltage_rmse_mV']=entry['ekf_prior_voltage_rmse_mV']
            metrics[entry['variant']+'_ekf_soc_proxy_rmse']=entry['ekf_soc_proxy_rmse']
    return finish(config,out,{'kind':'engineering','title':'CALB跨电芯温度OCV与RC回放验证','metrics':metrics,
        'comparisons':summaries,'details':{'scope':'6个源电芯HPPC池化，2个开发电芯选择，3个新电芯驾驶工况留出；新电芯C/20用于SOC代理与初始偏差，非完全盲初态。'}},
        records,packages=['sox','scipy','numpy'])

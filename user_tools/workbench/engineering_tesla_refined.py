"""Select low-temperature OCV calibration on m448-N, score new m1000 drives."""
import hashlib
import json
import time
import numpy as np
from user_tools.workbench.engineering_common import ROOT,finish,save,write_csv
from user_tools.workbench import engineering_tesla_validation as base

SOURCES=('c20','c20_corrected','c20_corrected_double','hppc_rest')
MODES=('reference_25',)+SOURCES


def verify():
    a=base.verify_data();path=base.DATA/'manifest_holdout2.json';manifest=json.loads(path.read_text(encoding='utf8'))
    if manifest['failures'] or len(manifest['files'])!=12:raise ValueError('Tesla额外留出文件清单不完整。')
    for item in manifest['files']:
        raw=(ROOT/item['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('Tesla额外留出文件SHA256不符。')
    return a,hashlib.sha256(path.read_bytes()).hexdigest()


def run_tesla_refined(config,out):
    started=time.perf_counter();original_hash,extra_hash=verify();out=base.Path(out);out.mkdir(parents=True,exist_ok=True)
    models={};audits={}
    for name in SOURCES:models[name],audits[name]=base.train_model(name)
    save(out/'tesla_calibration.json',{'training_cell':'m80','ocv_sources':audits,'models':models,
        'candidate_c20_corrections':'median C20 discharge current times pulse-fitted R0+R1, multiplier 0/1/2; heuristic, not verified equilibrium OCV',
        'soc_projection':'EKF state clipped to physical and measured OCV grid; count every affected step; covariance not corrected for truncation',
        'source_role':'target characterization files are checksum-verified only and not decoded'})
    records=[];traces=[]
    def evaluate(role,cell,drives):
        for temp in base.TEMPS:
            for drive in drives:
                for wi,window in enumerate(base.windows(cell,temp,drive)):
                    for name in MODES:
                        model=models['c20' if name=='reference_25' else name]
                        variant='reference_25' if name=='reference_25' else 'ocv_and_rc_temperature'
                        status='ok';error='';rows=[]
                        try:
                            m,rows=base.score(model,temp,window,variant,use_ukf=False,voltage_noise=.01,soc_q=1e-8,constraint='project')
                        except ValueError as exc:
                            if '不支持外推' not in str(exc) and 'SOC超出' not in str(exc):raise
                            status='outside_domain';error=str(exc);m=None
                        records.append({'role':role,'cell_id':cell,'temperature_C':temp,'drive':drive,'window':wi+1,'variant':name,
                            'status':status,'reason':error,'start_s':window['start_s'],
                            'ekf_prior_voltage_rmse_mV':m['ekf_prior_voltage_rmse_V']*1000 if m else None,
                            'ekf_soc_reference_rmse':m['ekf_rmse_soc'] if m else None,
                            'open_loop_voltage_rmse_mV':m['open_loop_voltage_rmse_mV'] if m else None,
                            'open_loop_status':m['open_loop_status'] if m else 'not_run',
                            'soc_projection_steps':m['soc_projection_steps'] if m else None,
                            'total_steps':len(rows)})
                        traces.extend({'role':role,'cell_id':cell,'temperature_C':temp,'drive':drive,'window':wi+1,'variant':name,
                            'time_s':r['time_s'],'current_A':r['sensor_current_A'],'voltage_V':r['sensor_voltage_V'],
                            'soc_reference':r['soc_reference'],'soc_ekf':r['soc_ekf'],'soc_ekf_projected':r['soc_ekf_projected'],
                            'ekf_prior_voltage_V':r['voltage_ekf_prior_V']} for r in rows)
                print(role,cell,temp,drive,flush=True)
    evaluate('development','m448-N',('drive1','drive2'))
    dev=[]
    for variant in MODES:
        group=[r for r in records if r['role']=='development' and r['variant']==variant];valid=[r for r in group if r['status']=='ok']
        total=sum(r['total_steps'] for r in valid);projections=sum(r['soc_projection_steps'] for r in valid)
        dev.append({'variant':variant,'windows':len(group),'valid_windows':len(valid),'projection_fraction':projections/total if total else None,
            'prior_mV':float(np.mean([r['ekf_prior_voltage_rmse_mV'] for r in valid])) if valid else None})
    eligible=[r for r in dev if r['valid_windows']==r['windows'] and r['projection_fraction']<=.05]
    selected=min(eligible,key=lambda x:x['prior_mV'])['variant'] if eligible else None
    save(out/'tesla_pretest_freeze.json',{'development':dev,'selected_variant':selected,
        'selection':'minimum development prior voltage RMSE among variants with full coverage and <=5% projected steps',
        'test_cell':'m1000','test_drives':['drive7','drive8'],'test_signals_decoded':False,
        'previously_seen':'same target cell was used for earlier drive5/6 evaluation; new records only, not a new independent cell'})
    evaluate('test','m1000',('drive7','drive8'))
    write_csv(out/'tesla_metrics.csv',records);write_csv(out/'tesla_traces.csv',traces)
    summary=[]
    for role in ('development','test'):
        for variant in MODES:
            group=[r for r in records if r['role']==role and r['variant']==variant];valid=[r for r in group if r['status']=='ok']
            total=sum(r['total_steps'] for r in valid);projections=sum(r['soc_projection_steps'] for r in valid)
            entry={'role':role,'variant':variant,'total_windows':len(group),'valid_windows':len(valid),
                   'projection_fraction':projections/total if total else None,
                   'open_loop_valid_windows':sum(r['open_loop_status']=='ok' for r in valid)}
            for key in ('ekf_prior_voltage_rmse_mV','ekf_soc_reference_rmse','open_loop_voltage_rmse_mV'):
                vals=[r[key] for r in valid if r[key] is not None];entry[key]=float(np.mean(vals)) if vals else None
            summary.append(entry)
    save(out/'tesla_validation.json',{'summary':summary,'records':records,'source_manifest_sha256':original_hash,
        'test_manifest_sha256':extra_hash,'projection_is_heuristic':True,
        'scope':'source-only m80 calibration; m1000 is same target cell seen in prior test, but reordered drive 7/8 not previously scored'})
    metrics={'selected_variant':selected,'test_cell':'m1000','elapsed_s':time.perf_counter()-started}
    for r in summary:
        if r['role']=='test':
            for key in ('valid_windows','projection_fraction','ekf_prior_voltage_rmse_mV','ekf_soc_reference_rmse','open_loop_voltage_rmse_mV'):
                metrics[r['variant']+'_'+key]=r[key]
    return finish(config,out,{'kind':'engineering','title':'Tesla低温OCV补偿与跨电芯验证',
        'metrics':metrics,'comparisons':summary,'details':{'scope':'m80 C/20与HPPC产生候选，m448-N开发选择，m1000新的驾驶记录验证；投影次数公开，目标电芯未参与标定；SOC为容量/积分参考。'}},records,packages=['sox','scipy','numpy'])

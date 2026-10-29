"""Prior-cycle SOH calibration and fresh temperature-record validation, with frozen splits."""
import copy
import hashlib
import json
from pathlib import Path
import time
import numpy as np

from user_tools.workbench.engineering_common import ROOT,finish,save,write_csv
from user_tools.workbench.engineering_commercial import DATA,load_measurement,resample,rc_voltage,predict
from user_tools.workbench.engineering_adaptive_math import arrays,predict_fast,predict_thevenin,observe

TEMP_DATA=ROOT/'data/public/panasonic_pf_multitemp_v1'
PROTOCOL=ROOT/'configs/commercial_pf_adaptive_20261029.json'
REFERENCE=ROOT/'configs/panasonic_pf_reference_v0313.json'


def prepare_stream(raw,nominal_temp,lo=0,hi=None):
    stream=resample(raw,lo,hi)
    for key in ['t','current','v','temp','cumulative_charge_As']:
        if not np.isfinite(stream[key]).all():raise ValueError('Missing/non-finite measured channel: '+key)
    missing=~np.isfinite(stream['ambient'])
    stream['chamber_missing_fraction']=float(np.mean(missing))
    stream['ambient_source']='recorded chamber' if not missing.any() else 'missing chamber values replaced by declared dataset-folder nominal setpoint'
    stream['ambient'][missing]=float(nominal_temp)
    # Sparse rest logs are genuine one-minute samples, not 60 invented sensor updates.
    hi=len(raw['Time']) if hi is None else hi
    original_t=raw['Time'][lo:hi];keep=np.r_[np.diff(original_t)>1e-9,True]
    original_t=original_t[keep];original_t=original_t-original_t[0]
    right=np.minimum(np.searchsorted(original_t,stream['t']),len(original_t)-1);left=np.maximum(right-1,0)
    nearest=np.minimum(abs(stream['t']-original_t[left]),abs(stream['t']-original_t[right]))
    stream['measurement_mask']=((original_t[right]-original_t[left])<=2.)|(nearest<=.5)
    past=np.maximum(np.searchsorted(original_t,stream['t'],side='right')-1,0)
    stream['sensor_temp_C']=raw['Battery_Temp_degC'][lo:hi][keep][past]
    return stream


def reference():
    raw=REFERENCE.read_bytes();obj=json.loads(raw)
    return obj['reference']['model'],hashlib.sha256(raw).hexdigest()


def verify_sources():
    result=[]
    for root in [DATA,TEMP_DATA]:
        manifest=json.loads((root/'download_manifest.json').read_text(encoding='utf-8'))
        for item in manifest['files']:
            path=Path(item['path']);path=ROOT/path if item['path'].startswith('data/') else root/path
            expected=item.get('expected_sha256',item.get('sha256'))
            if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:raise ValueError('Public source checksum mismatch: '+str(path))
            result.append(dict(path=path.relative_to(ROOT).as_posix(),sha256=expected))
    return result


def fit_temperature_hppc(path,nominal_temp):
    from scipy.optimize import least_squares
    raw=load_measurement(path);t=raw['Time'];edges=np.r_[0,np.flatnonzero(np.diff(t)>2)+1,len(t)]
    rests=[];streams=[]
    for lo,hi in zip(edges[:-1],edges[1:]):
        if hi-lo<30:continue
        s=prepare_stream(raw,nominal_temp,int(lo),int(hi));s['soc']=1+s['ah']/2.9
        rests.append([float(s['soc'][0]),float(np.median(raw['Voltage'][lo:lo+10]))]);streams.append(s)
    if len(streams)<5:raise ValueError('Insufficient HPPC calibration groups')
    rests.sort(key=lambda r:r[0]);ocv_soc=np.r_[0.,[r[0] for r in rests]];ocv_v=np.maximum.accumulate(np.r_[2.5,[r[1] for r in rests]])
    # Duplicate full-SOC groups would make the interpolation invalid, so fail explicitly.
    if np.any(np.diff(ocv_soc)<=0):raise ValueError('HPPC rest SOC nodes are not unique/increasing')
    rows=[];fits=[]
    for s in streams:
        ocv=np.interp(s['soc'],ocv_soc,ocv_v)
        fit=least_squares(lambda p:rc_voltage(p,s,ocv,1)-s['v'],[np.log(.03),np.log(.02),np.log(30.),0.],
            bounds=([np.log(.001),np.log(.0001),np.log(1.),-.15],[np.log(.6),np.log(.6),np.log(3000.),.15]),
            max_nfev=150,loss='soft_l1',f_scale=.02)
        r0,r1,tau=np.exp(fit.x[:3]);rows.append(dict(soc=float(np.mean(s['soc'])),R0_ohm=r0,R1_ohm=r1,C1_F=tau/r1))
        fits.append(dict(soc=rows[-1]['soc'],rmse_mV=float(np.sqrt(np.mean(fit.fun**2))*1000),local_offset_V=float(fit.x[-1]),success=bool(fit.success)))
    rows.sort(key=lambda r:r['soc'])
    return dict(nominal_temperature_C=nominal_temp,ocv_soc=ocv_soc,ocv_V=ocv_v,table=rows,fits=fits,
          measured_temperature_range_C=[float(raw['Battery_Temp_degC'].min()),float(raw['Battery_Temp_degC'].max())],
          path=path.relative_to(ROOT).as_posix())


def build_model(base,calibrations):
    entries=[dict(nominal_temperature_C=25.,ocv_soc=base['ocv_soc'],ocv_V=base['ocv_V'],table=base['table'])]+calibrations
    entries.sort(key=lambda r:r['nominal_temperature_C'])
    grid=np.unique(np.r_[0.,1.,*[e['ocv_soc'] for e in entries],*[np.array([r['soc'] for r in e['table']]) for e in entries]])
    if grid[0]<0 or grid[-1]>1:raise ValueError('Calibration SOC table outside[0,1]')
    table=np.empty((4,len(entries),len(grid)))
    for k,e in enumerate(entries):
        table[0,k]=np.interp(grid,e['ocv_soc'],e['ocv_V'])
        for j,key in enumerate(['R0_ohm','R1_ohm','C1_F'],1):table[j,k]=np.interp(grid,[r['soc'] for r in e['table']],[r[key] for r in e['table']])
    return dict(capacity_Ah=2.9,soc_grid=grid,temperature_nodes_C=np.array([e['nominal_temperature_C'] for e in entries]),
        tables=table,thermal_capacity_J_K=base['thermal_capacity_J_K'],heat_transfer_W_K=base['heat_transfer_W_K'],
        aging_scales=[1.,1.,1.],dynamic_case_temperature=False,
        temperature_axis='nominal HPPC chamber temperature; applying the RC table to case temperature is a selection candidate')


def split_segments(path,nominal_temp=25.):
    raw=load_measurement(path);bounds=np.r_[0,np.flatnonzero(np.diff(raw['Time'])>90)+1,len(raw['Time'])]
    return [prepare_stream(raw,nominal_temp,int(lo),int(hi)) for lo,hi in zip(bounds[:-1],bounds[1:])]


def select_and_freeze(out):
    from scipy.optimize import least_squares
    base,base_sha=reference();sources=verify_sources()
    save(out/'baseline_reference.json',json.loads(REFERENCE.read_text(encoding='utf-8')))
    calibrations=[]
    for temp in [0,10]:
        path=next((TEMP_DATA/f'{temp}degC/pulses').glob('*HPPC*.mat'))
        calibrations.append(fit_temperature_hppc(path,float(temp)))
    model=build_model(base,calibrations)
    selection=[prepare_stream(load_measurement(next((DATA/'25degC/Drive cycles').glob('*Cycle_1_*.mat'))),25.)]
    selection += [prepare_stream(load_measurement(next((TEMP_DATA/f'{t}degC/drives').glob('*Cycle_1_*.mat'))),float(t)) for t in [0,10]]
    losses=[]
    for dynamic in [False,True]:
        model['dynamic_case_temperature']=dynamic
        errors=[float(np.sqrt(np.mean((predict_fast(model,s)[:,0]-s['v'])**2))*1000) for s in selection]
        losses.append(dict(dynamic_case_temperature=dynamic,selection_voltage_rmse_mV=errors,mean_rmse_mV=float(np.mean(errors))))
    model['dynamic_case_temperature']=min(losses,key=lambda x:x['mean_rmse_mV'])['dynamic_case_temperature']
    age_train=split_segments(next((DATA/'25degC/C20 OCV Test_end_of_tests').glob('*Dis1C_1.mat')))[0]
    age_selection=split_segments(next((DATA/'25degC/C20 OCV Test_end_of_tests').glob('*Dis1C_Rp.mat')))[0]
    usable=float(age_train['cumulative_charge_As'][-1]/3600)
    if not 1.5<usable<3.5 or min(age_train['v'])>2.55 or min(age_train['current'])<-.05:
        raise ValueError('Aging calibration requires discharge to2.5V, allowing the recorded subsequent relaxation')
    aged=copy.deepcopy(model)
    def residual(p):
        aged['capacity_Ah']=float(p[0]);aged['aging_scales']=np.exp(p[1:])
        return (predict_fast(aged,age_train)[:,0]-age_train['v'])[::3]
    bounds=([usable,np.log(.25),np.log(.25),np.log(.25)],[min(3.5,usable*1.15),np.log(6.),np.log(6.),np.log(4.)])
    fit=least_squares(residual,[usable*1.01,np.log(1.5),np.log(1.5),0.],bounds=bounds,max_nfev=150,loss='soft_l1',f_scale=.02)
    residual(fit.x)
    singular=np.linalg.svd(fit.jac,compute_uv=False)
    age_fit=dict(usable_discharge_capacity_Ah=usable,model_capacity_Ah=aged['capacity_Ah'],model_capacity_ratio_to_nominal=aged['capacity_Ah']/2.9,
        aging_scales=aged['aging_scales'],prior_cycle_delivered_capacity_ratio=usable/2.9,
        parameter_at_bound=[bool(abs(p-lo)<1e-5 or abs(p-hi)<1e-5) for p,lo,hi in zip(fit.x,*bounds)],
        training_voltage_rmse_mV=float(np.sqrt(np.mean((predict_fast(aged,age_train)[:,0]-age_train['v'])**2))*1000),
        jacobian_condition_number=float(singular[0]/max(singular[-1],1e-20)),optimizer_success=bool(fit.success),
        identifiability='single constant-current discharge, coupled parameters; no unique degradation-mechanism claim',
        capacity_policy='model capacity bounded between observed prior-cycle delivered charge and1.15x that charge; not inferred from a held-out endpoint')
    # Residual scales and process setting are chosen only on selection records.
    noises=[float(np.clip(np.sqrt(np.mean((predict_fast(model,s)[:,0]-s['v'])**2)),.005,.15)) for s in selection]
    noise=float(np.mean(noises));age_noise=float(np.clip(np.sqrt(np.mean((predict_fast(aged,age_selection)[:,0]-age_selection['v'])**2)),.005,.15))
    candidates=[]
    for q in [0.,1e-7,1e-6]:
        streams=[(model,selection[0],noise),(model,selection[1],noise),(model,selection[2],noise),(aged,age_selection,age_noise)]
        innovation=[]
        for m,s,sigma in streams:
            predicted,_=observe(m,s,sigma,q)
            innovation.append(float(np.sqrt(np.mean(predicted[s['measurement_mask'],3]**2))*1000))
        candidates.append(dict(log_r_process=q,selection_innovation_rmse_mV=innovation,mean_rmse_mV=float(np.mean(innovation))))
    selected=min(candidates,key=lambda r:r['mean_rmse_mV'])['log_r_process']
    freeze=dict(model=model,aged_model=aged,voltage_noise_V=noise,aged_voltage_noise_V=age_noise,log_r_process=selected,
          temperature_selection=losses,observer_selection=candidates,aging_fit=age_fit,
          reference_sha256=base_sha,source_files=sources,protocol_sha256=hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
          development_exposed_records=['0degC_US06','0degC_UDDS'],new_scored_records=7,
          fresh_holdout_signals_decoded_during_calibration=False)
    save(out/'temperature_calibration.json',calibrations);save(out/'adaptive_frozen_model.json',freeze)
    save(out/'pre_holdout_freeze.json',dict(adaptive_frozen_sha256=hashlib.sha256((out/'adaptive_frozen_model.json').read_bytes()).hexdigest(),fresh_signals_opened=False))
    save(out/'validation_protocol.json',json.loads(PROTOCOL.read_text(encoding='utf-8')))
    return freeze


def open_loop_metrics(pred,stream):
    observed=stream['measurement_mask'];delta=pred[observed,0]-stream['v'][observed]
    return dict(voltage_rmse_mV=float(np.sqrt(np.mean(delta**2))*1000),voltage_mae_mV=float(np.mean(abs(delta))*1000),
                temperature_rmse_C=float(np.sqrt(np.mean((pred[observed,1]-stream['temp'][observed])**2))),points=len(delta),simulation_points=len(pred),coverage=1.)


def control_configuration(model,source):
    from user_tools.workbench.engineering_contracts import default_cell
    from user_tools.workbench.engineering_adaptive_math import interpolation
    grid,temps,tables,thermal,scales=arrays(model);cell=default_cell()
    lookup=lambda soc,index,scale=1.:float(interpolation(float(soc),25.,grid,temps,tables[index])*scale)
    cell.update(cell_id='Panasonic-NCR18650PF-prior-cycle-calibrated',capacity_Ah=float(model['capacity_Ah']),
         initial_soc=.3,estimated_initial_soc=.3,temperature_C=25.,mass_kg=.048,heat_capacity_J_kgK=float(thermal[0]/.048),
         heat_transfer_W_K=float(thermal[1]),voltage_min_V=2.5,current_max_A=2.9,
         ocv_soc=grid.tolist(),ocv_V=[lookup(s,0) for s in grid],R0_ohm=lookup(.5,1,scales[0]),
         R_ohm=[lookup(.5,2,scales[1])],C_F=[lookup(.5,3,scales[2]/scales[1])])
    cell['rc_table']=[dict(soc=float(s),temperature_C=float(t),R0_ohm=lookup(s,1,scales[0]),R1_ohm=lookup(s,2,scales[1]),C1_F=lookup(s,3,scales[2]/scales[1])) for s in grid for t in [0.,60.]]
    cell['rc_temperature_scope']='SOC-dependent prior-cycle parameters at25C held constant over simulation temperature; not a measured0..60C aging map'
    return dict(action='mpc',data_origin='public',source=source,cell=cell,steps=180,dt_s=12.,horizon=8,target_soc=.8,
          voltage_noise_V=.005,current_noise_A=0.,current_bias_A=0.,seed=42)


def run_adaptive(config,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True);start=time.perf_counter()
    frozen=select_and_freeze(out);base,_=reference();fixed_sha=hashlib.sha256((out/'adaptive_frozen_model.json').read_bytes()).hexdigest()
    save(out/'adaptive_control_config.json',control_configuration(frozen['aged_model'],config['source']))
    # No test signal is opened above this line. The following lists come from the predeclared protocol.
    tasks=[]
    for temp in [0,10]:
        for kind in ['US06','UDDS','LA92']:
            path=next((TEMP_DATA/f'{temp}degC/drives').glob('*'+kind+'_Pan*.mat'))
            role='development_exposed_regression' if temp==0 and kind in ['US06','UDDS'] else 'fresh_condition_holdout'
            tasks.append((path,0,role,float(temp),False))
    for kind in ['HWFTa','HWFTb','NN']:
        path=next((DATA/'25degC/Drive cycles').glob('*'+kind+'_Pan*.mat'))
        tasks.append((path,0,'fresh_condition_holdout',25.,False))
    repeated=next((DATA/'25degC/C20 OCV Test_end_of_tests').glob('*Dis1C_Rp.mat'))
    tasks += [(repeated,i,'historical_aging_regression',25.,True) for i in range(1,10)]
    tasks.append((next((DATA/'25degC/C20 OCV Test_end_of_tests').glob('*Dis1C_2.mat')),0,'historical_aging_regression',25.,True))
    # Construct a baseline observer with exactly the original25C table, not a temperature fit.
    original=build_model(base,[]);rows=[];metrics=[];curves=[];numerical=[]
    for path,index,role,temp,aged in tasks:
        parts=split_segments(path,temp)
        if role in ['fresh_condition_holdout','development_exposed_regression'] and len(parts)!=1:raise ValueError('Fresh record has unplanned gaps; revise protocol explicitly before scoring')
        stream=parts[index];name=path.stem+(f'__segment{index+1}' if path==repeated else '')
        model=frozen['aged_model'] if aged else frozen['model'];noise=frozen['aged_voltage_noise_V'] if aged else frozen['voltage_noise_V']
        updated=predict_thevenin(model,stream);legacy=np.column_stack(predict(base,stream))
        fast=predict_fast(model,stream)
        numerical.append(dict(test=name,max_voltage_difference_V=float(np.max(abs(updated[:,0]-fast[:,0]))),max_temperature_difference_C=float(np.max(abs(updated[:,1]-fast[:,1])))))
        estimated,filter_info=observe(model,stream,noise,frozen['log_r_process'])
        old_estimated,_=observe(original,stream,noise,0.)
        ref=1-stream['cumulative_charge_As']/(3600*model['capacity_Ah']);observed=stream['measurement_mask']
        new_score=open_loop_metrics(updated,stream);old_score=open_loop_metrics(legacy,stream)
        record=dict(test=name,role=role,nominal_temperature_C=temp,**new_score,
              baseline_voltage_rmse_mV=old_score['voltage_rmse_mV'],baseline_temperature_rmse_C=old_score['temperature_rmse_C'],
              ekf_soc_proxy_rmse=float(np.sqrt(np.mean((estimated[observed,0]-ref[observed])**2))),baseline_ekf_soc_proxy_rmse=float(np.sqrt(np.mean((old_estimated[observed,0]-ref[observed])**2))),
              innovation_rmse_mV=float(np.sqrt(np.mean(estimated[observed,3]**2))*1000),final_R0_online_scale=float(estimated[-1,1]),
              baseline_innovation_rmse_mV=float(np.sqrt(np.mean(old_estimated[observed,3]**2))*1000),
              measured_discharge_Ah=float(stream['cumulative_charge_As'][-1]/3600),**filter_info)
        record.update(chamber_missing_fraction=stream['chamber_missing_fraction'],ambient_source=stream['ambient_source'])
        metrics.append(record)
        for i,t in enumerate(stream['t']):rows.append(dict(test=name,role=role,time_s=t,current_A=stream['current'][i],measurement_used=bool(observed[i]),measured_voltage_V=stream['v'][i] if observed[i] else None,
              baseline_voltage_V=legacy[i,0],updated_voltage_V=updated[i,0],measured_temperature_C=stream['temp'][i] if observed[i] else None,updated_temperature_C=updated[i,1],
              soc_proxy_reference=ref[i],soc_ekf=estimated[i,0],baseline_soc_ekf=old_estimated[i,0],pre_update_voltage_V=estimated[i,2],
              innovation_V=estimated[i,3] if observed[i] else None,R0_online_scale=estimated[i,1],parameter_update_excited=estimated[i,5]))
        stride=max(1,len(stream['t'])//400)
        if role=='fresh_condition_holdout' or index in [1,9]:curves.append(dict(name=name+' 更新模型电压',y_label='电压 (V)',primary='温度/老化更新模型',secondary='实测',
              points=[[stream['t'][i],updated[i,0],stream['v'][i]] for i in np.flatnonzero(observed)[::stride]]))
        print(role,name,round(old_score['voltage_rmse_mV'],2),'->',round(new_score['voltage_rmse_mV'],2),'mV',flush=True)
    if hashlib.sha256((out/'adaptive_frozen_model.json').read_bytes()).hexdigest()!=fixed_sha:raise RuntimeError('Frozen model changed during validation')
    write_csv(out/'adaptive_metrics.csv',metrics);save(out/'adaptive_numerical_audit.json',numerical)
    save(out/'adaptive_validation.json',dict(tests=metrics,freeze_sha256=fixed_sha,fresh_condition_records=7,development_exposed_records=2,historical_aging_records=10,
        physical_cells=1,cross_cell_validated=False,holdout_parameter_refit=False,observer_voltage_is_online_input=True,
        open_loop_and_observer_metrics_separate=True,capacity_update='completed prior-cycle calibration, not blind on-line capacity discovery',
        soc_reference='current integral/training capacity proxy, no independent absolute SOC',numerical_audit=numerical,aging_fit=frozen['aging_fit']))
    fresh=[r for r in metrics if r['role']=='fresh_condition_holdout'];aging=[r for r in metrics if r['role']=='historical_aging_regression']
    return finish(config,out,dict(kind='engineering',title='Panasonic PF · 温度/SOH更新与新工况验证',engine='Thevenin + SOX augmented EKF + bounded prior-cycle calibration',
       frozen_model_sha256=fixed_sha,control_config_sha256=hashlib.sha256((out/'adaptive_control_config.json').read_bytes()).hexdigest(),
       metrics=dict(fresh_records=7,development_exposed_records=2,historical_aging_records=10,calibrated_capacity_Ah=frozen['aged_model']['capacity_Ah'],
         fresh_mean_voltage_rmse_mV=float(np.mean([r['voltage_rmse_mV'] for r in fresh])),fresh_baseline_mean_voltage_rmse_mV=float(np.mean([r['baseline_voltage_rmse_mV'] for r in fresh])),
         aging_mean_voltage_rmse_mV=float(np.mean([r['voltage_rmse_mV'] for r in aging])),aging_baseline_mean_voltage_rmse_mV=float(np.mean([r['baseline_voltage_rmse_mV'] for r in aging])),
         fresh_voltage_tests_passed=sum(r['voltage_rmse_mV']<=50 for r in fresh),aging_voltage_tests_passed=sum(r['voltage_rmse_mV']<=50 for r in aging),
         log_R0_process=frozen['log_r_process'],elapsed_s=time.perf_counter()-start),tests=metrics,
       details={'scope':'同一PF电芯：0/10/25°C参数表、上一完整循环容量/阻抗更新、SOX增广EKF。7条新评分记录作工况留出；2条开发时已评分、10段老化为历史回归。稀疏休息记录不生成虚假的1Hz电压更新。开环预测与在线估计分开计分；未跨电芯或硬件验证。'}),rows,curves,['thevenin','sox','scipy','numpy','numba'])

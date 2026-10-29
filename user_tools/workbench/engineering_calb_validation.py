"""Cell-matched public pulse calibration and held-out driving replay.

The driving records never calibrate the RC tables. SOC is an approximate proxy:
the initial point comes from the same-cell slow-discharge voltage curve and is
then coulomb-counted with that cell's measured capacity. It is not true SOC.
"""
from pathlib import Path
import copy
import hashlib
import json
import time
import numpy as np
from scipy.io import loadmat
from scipy.integrate import cumulative_trapezoid
from scipy.optimize import least_squares
from scipy.signal import lfilter
from user_tools.workbench.engineering_common import ROOT, finish, save, write_csv
from user_tools.workbench.engineering_contracts import defaults
from user_tools.workbench.engineering_rc_grid import make_rc_interpolator
from user_tools.workbench.engineering_bms import estimate_stream

DATA=ROOT/'data/public/calb_matched_v2'
EXTRA_DATA=ROOT/'data/public/calb_matched_extra_v2'
EXTRA_CELLS=('60129','60403')
EXTRA2_DATA=ROOT/'data/public/calb_matched_extra2_v2'
EXTRA2_CELLS=('60644','60710')
EXTRA3_DATA=ROOT/'data/public/calb_matched_extra3_v2'
EXTRA3_CELLS=('59861','60031','60195')
DEVELOP=('59294','59485')
TEST=('59627','59690')
TEMPS=(10,25,40)
DRIVES=('dv_wltp','dv_udds','dv_us06')
TIME_AUDIT=[]


def verify_data():
    manifest=json.loads((DATA/'manifest.json').read_text(encoding='utf8'))
    if manifest['failures'] or tuple(manifest['cells'])!=DEVELOP+TEST:raise ValueError('CALB清单不完整或电芯划分不一致。')
    for x in manifest['files']:
        path=ROOT/x['path']
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=x['sha256']:
            raise ValueError('CALB原始文件缺失或哈希不符：'+str(path))
    return manifest


def load(cell,temp,group):
    root=(EXTRA3_DATA if cell in EXTRA3_CELLS else EXTRA2_DATA if cell in EXTRA2_CELLS
          else EXTRA_DATA if cell in EXTRA_CELLS else DATA)
    data=loadmat(root/f'Temperature_{temp}C'/group/(cell+'.mat'),simplify_cells=True)['Data']
    if not isinstance(data,dict):raise ValueError(f'{cell}/{temp}/{group}: expected a time-series struct')
    t=np.asarray(data['Times'],float);current=np.asarray(data['CurrentA'],float)
    voltage=np.asarray(data['VoltageV'],float);surface=np.asarray(data['TempC'],float)
    if len(t)<10 or not all(np.isfinite(x).all() for x in (t,current,voltage,surface)):
        raise ValueError(f'{cell}/{temp}/{group}: missing or non-finite samples')
    differences=np.diff(t)
    if np.any(differences<0):raise ValueError(f'{cell}/{temp}/{group}: timestamp reversal')
    duplicates=int(np.sum(differences==0))
    if duplicates:
        keep=np.r_[differences>0,True]
        t,current,voltage,surface=(values[keep] for values in (t,current,voltage,surface))
        TIME_AUDIT.append({'cell_id':cell,'temperature_C':temp,'group':group,'duplicate_timestamps':duplicates,'policy':'keep last at equal timestamp'})
    return {'t':t,'i':current,'v':voltage,'temp':surface}


def slow_reference(cell,temp):
    x=load(cell,temp,'c20_discharge')
    q=-cumulative_trapezoid(x['i'],x['t'],initial=0)/3600
    capacity=float(q[-1]);soc=1-q/capacity
    if not 30<capacity<70 or x['v'][-1]>2.55:raise ValueError('C/20容量或终止电压异常。')
    # C/20 terminal voltage is a pseudo-OCV: includes hysteresis and IR drop.
    v=np.maximum.accumulate(x['v'][::-1]);s=soc[::-1]
    v,indices=np.unique(v,return_index=True)
    return {'capacity':capacity,'reference_voltage':v,'reference_soc':s[indices]}


def fit_hppc(cell,temp,capacity):
    x=load(cell,temp,'hppc_1c');t,i,v=x['t'],x['i'],x['v']
    charge=cumulative_trapezoid(i,t,initial=0)/3600
    active=i < -10.; edges=np.diff(np.r_[False,active,False].astype(int))
    starts=np.flatnonzero(edges==1);ends=np.flatnonzero(edges==-1)-1
    nodes=[]
    for a,b in zip(starts,ends):
        duration=t[b]-t[a]
        pulse_amplitude=-float(np.median(i[a:b+1]))
        if not 8<=duration<=12 or not 40<=pulse_amplitude<=70 or t[a]+120>t[-1]:continue
        s=float(1+charge[a]/capacity)
        if not 0<=s<=1.001:continue
        times=t[a]+np.arange(1.,121.)
        measured=np.interp(times,t,v)
        q=cumulative_trapezoid(-i,t,initial=0)
        sample_q=np.interp(np.r_[t[a],times],t,q);current=np.diff(sample_q)
        before=float(v[max(0,a-1)])
        def predict(p):
            r0,r1,tau=np.exp(p[:3]);a0=np.exp(-1/tau)
            eta=lfilter([r1*(1-a0)],[1.,-a0],current)
            return p[3]-r0*current-eta
        fit=least_squares(lambda p:predict(p)-measured,
            [np.log(.001),np.log(.0005),np.log(10.),before],
            bounds=([np.log(.00001),np.log(.000001),np.log(.25),before-.05],
                    [np.log(.05),np.log(.05),np.log(600.),before+.05]),max_nfev=160,loss='soft_l1',f_scale=.004)
        r0,r1,tau=np.exp(fit.x[:3])
        nodes.append({'soc':min(s,1.),'R0_ohm':float(r0),'R1_ohm':float(r1),'C1_F':float(tau/r1),
                      'pseudo_ocv_V':float(fit.x[3]),'fit_rmse_mV':float(np.sqrt(np.mean(fit.fun**2))*1000),
                      'pulse_start_s':float(t[a]),'fit_success':bool(fit.success),'at_bound':bool(np.any(fit.active_mask!=0))})
    nodes.sort(key=lambda row:row['soc'])
    if len(nodes)<6 or any(not row['fit_success'] for row in nodes):raise ValueError(f'{cell}/{temp}: 可用HPPC脉冲不足。')
    if np.any(np.diff([x['soc'] for x in nodes])<=0):raise ValueError('HPPC SOC节点重复。')
    return nodes


def fit_cell(cell):
    refs={t:slow_reference(cell,t) for t in TEMPS}
    nodes={t:fit_hppc(cell,t,refs[t]['capacity']) for t in TEMPS}
    lower=max(rows[0]['soc'] for rows in nodes.values());upper=min(rows[-1]['soc'] for rows in nodes.values())
    if lower>=.25 or upper<=.9:raise ValueError(f'{cell}: HPPC共同SOC覆盖不足。')
    # Rectangular grid is made strictly inside all three measured SOC ranges.
    grid=np.linspace(lower+1e-6,upper-1e-6,10)
    table=[]
    for s in grid:
        for temp in TEMPS:
            x=nodes[temp];soc=[row['soc'] for row in x]
            table.append({'soc':float(s),'temperature_C':float(temp),
                          **{key:float(np.interp(s,soc,[row[key] for row in x])) for key in ('R0_ohm','R1_ohm','C1_F')}})
    base=nodes[25];sx=np.array([row['soc'] for row in base]);vv=np.maximum.accumulate([row['pseudo_ocv_V'] for row in base])
    # Endpoint holds allow the common OCV contract; scored SOC stays in table domain.
    ocv_soc=np.r_[0.,sx,1.] if sx[-1]<1 else np.r_[0.,sx]
    ocv_v=np.r_[vv[0],vv,vv[-1]] if sx[-1]<1 else np.r_[vv[0],vv]
    # Avoid duplicate exact 1.0 or zero nodes.
    unique=np.r_[True,np.diff(ocv_soc)>1e-10];ocv_soc=ocv_soc[unique];ocv_v=ocv_v[unique]
    cell_config=defaults('ecm_bms')['cell']
    cell_config.update(cell_id='CALB-'+cell,capacity_Ah=refs[25]['capacity'],
        ocv_soc=ocv_soc.tolist(),ocv_V=ocv_v.tolist(),rc_table=table,rc_interpolation='linear')
    return cell_config,refs,nodes


def windows(cell,temp,drive,reference):
    x=load(cell,temp,drive);t=x['t'];q=-cumulative_trapezoid(x['i'],t,initial=0)/3600
    initial=float(np.interp(x['v'][0],reference['reference_voltage'],reference['reference_soc']))
    soc=initial-q/reference['capacity']
    active=np.flatnonzero(np.abs(x['i'])>5.)
    if not len(active):raise ValueError('Driving record contains no current excitation')
    active_end=float(t[active[-1]])
    output=[]
    # Predeclared windows: 20% and 60% of active-record duration, 600s each.
    for fraction in (.2,.6):
        start=float(t[0]+fraction*(active_end-t[0]));times=start+np.arange(601.)
        if times[-1]>t[-1]:raise ValueError('Driving record too short for predeclared window')
        qs=np.interp(times,t,q); current=np.r_[0.,np.diff(qs)*3600]
        current[0]=-float(np.interp(times[0],t,x['i']))
        volt=np.interp(times,t,x['v']);proxy=initial-qs/reference['capacity']
        # Interpolate voltage but count only seconds close to a true sample.
        right=np.minimum(np.searchsorted(t,times),len(t)-1);left=np.maximum(right-1,0)
        nearest=np.minimum(abs(times-t[left]),abs(times-t[right]))
        if np.max(nearest)>.51:raise ValueError('Selected window contains sparse voltage logging')
        output.append({'start_s':start,'soc_proxy':proxy,'voltage':volt,'current':current,
                       'surface':np.interp(times,t,x['temp']),'soc_anchor':initial})
    return output


def pulse_windows(cell,temp,reference):
    """Independent C/3 pulses (HPPC 1C was used for fitting), 3 SOC targets."""
    x=load(cell,temp,'hppc_c3');t=x['t'];q=-cumulative_trapezoid(x['i'],t,initial=0)/3600
    active=x['i'] < -10.;edges=np.diff(np.r_[False,active,False].astype(int))
    starts=np.flatnonzero(edges==1);ends=np.flatnonzero(edges==-1)-1
    pulses=[]
    for a,b in zip(starts,ends):
        if 8<=t[b]-t[a]<=12 and t[a]>=5 and t[a]+115<=t[-1]:
            amplitude=-float(np.median(x['i'][a:b+1]))
            if 10<=amplitude<=30:pulses.append((float(1-q[a]/reference['capacity']),float(t[a]),amplitude))
    out=[];used=set()
    for target in (.3,.5,.7):
        if not pulses:raise ValueError('C/3留出脉冲不足。')
        idx=min(range(len(pulses)),key=lambda i:abs(pulses[i][0]-target))
        if idx in used or abs(pulses[idx][0]-target)>.12:raise ValueError('C/3留出脉冲SOC覆盖不足。')
        used.add(idx);start=pulses[idx][1]-5;times=start+np.arange(121.)
        qs=np.interp(times,t,q);current=np.r_[0.,np.diff(qs)*3600]
        current[0]=-float(np.interp(times[0],t,x['i']))
        right=np.minimum(np.searchsorted(t,times),len(t)-1);left=np.maximum(right-1,0)
        if np.max(np.minimum(abs(times-t[left]),abs(times-t[right])))>.51:
            raise ValueError('C/3留出脉冲采样稀疏。')
        out.append({'start_s':float(start),'soc_proxy':1-qs/reference['capacity'],
                    'voltage':np.interp(times,t,x['v']),'current':current,'target_soc':target,
                    'pulse_amplitude_A':pulses[idx][2]})
    return out


def score_window(cell_config,temp,window,mode,noise,soc_q=1e-8):
    cfg=defaults('ecm_bms');cfg['cell']=copy.deepcopy(cell_config)
    cfg['cell']['temperature_C']=float(temp)
    initial=float(window['soc_proxy'][0]-.04)
    cfg['cell']['estimated_initial_soc']=initial
    interpolation=make_rc_interpolator(cfg['cell']['rc_table'],1)
    p=interpolation(initial,temp)
    cfg['cell'].update(R0_ohm=p['R0_ohm'],R_ohm=[p['R1_ohm']],C_F=[p['C1_F']])
    cfg['filter_rc_mode']='fixed' if mode=='fixed_start' else mode
    cfg['voltage_noise_V']=noise;cfg['current_noise_A']=0.
    cfg['soc_process_variance_per_step']=soc_q
    rows=[{'time_s':float(k),'sensor_current_A':float(current),'sensor_voltage_V':float(voltage),
           'measured_temperature_C':float(temp),'soc_reference':float(soc)}
          for k,(current,voltage,soc) in enumerate(zip(window['current'],window['voltage'],window['soc_proxy']))]
    out,metrics=estimate_stream(cfg,rows)
    return metrics, out


def run_calb(config,out):
    TIME_AUDIT.clear()
    start=time.perf_counter();manifest=verify_data();out=Path(out);out.mkdir(parents=True,exist_ok=True)
    results=[];candidate_rows=[];traces=[];models={};references={};calibrations={}
    # HPPC/C20 calibration for all four cells, before loading any drive values.
    for cell in DEVELOP+TEST:
        cfg,refs,nodes=fit_cell(cell);models[cell]=cfg;references[cell]=refs;calibrations[cell]=nodes
    save(out/'calb_calibration.json',{'models':models,'hppc_nodes':calibrations,
         'train':'same-cell HPPC 1C, pre-driving C/20; no drive signals',
         'window_protocol':'600s starting at 20% and 60% of the active duration',
         'soc_reference':'C/20 voltage anchor at drive start plus integrated current; approximate SOC proxy',
         'temperature':'nominal chamber setpoint, not measured surface temperature',
         'dev_cells':DEVELOP,'test_cells':TEST})
    # Select measurement noise on one development cell / one temperature / one drive.
    dev_windows=windows(DEVELOP[0],25,'dv_wltp',references[DEVELOP[0]][25])
    for sigma in (.005,.02,.05):
        losses=[]
        for window in dev_windows:
            score,_=score_window(models[DEVELOP[0]],25,window,'estimated_grid',sigma)
            losses.append(score['ekf_prior_voltage_rmse_V'])
        candidate_rows.append({'voltage_noise_V':sigma,'development_ekf_prior_rmse_V':float(np.mean(losses))})
    selected=min(candidate_rows,key=lambda row:row['development_ekf_prior_rmse_V'])['voltage_noise_V']
    save(out/'calb_pretest_freeze.json',{'voltage_noise_V':selected,'candidates':candidate_rows,
        'selection_cell':DEVELOP[0],'selection_temperature_C':25,'selection_drive':'dv_wltp',
        'holdout_cells':TEST,'method':'min EKF prior voltage RMSE; fixed and grid use same noise'})
    for role,cells in [('development',DEVELOP),('test',TEST)]:
        for cell in cells:
            for temp in TEMPS:
                for drive in DRIVES:
                    for index,window in enumerate(windows(cell,temp,drive,references[cell][temp])):
                        for mode in ('fixed_start','estimated_grid'):
                            score,series=score_window(models[cell],temp,window,mode,selected)
                            results.append({'role':role,'cell_id':cell,'temperature_C':temp,'drive':drive,'window':index+1,
                                'mode':mode,'start_s':window['start_s'],'initial_soc_proxy':float(window['soc_proxy'][0]),
                                'soc_anchor_proxy':window['soc_anchor'],
                                'ekf_prior_voltage_rmse_mV':score['ekf_prior_voltage_rmse_V']*1000,
                                'ukf_prior_voltage_rmse_mV':score['ukf_prior_voltage_rmse_V']*1000,
                                'ekf_soc_proxy_rmse':score['ekf_rmse_soc'],'ukf_soc_proxy_rmse':score['ukf_rmse_soc']})
                            # Keep every sampled timepoint; a scoreable prediction precedes its observation.
                            traces.extend({'role':role,'cell_id':cell,'temperature_C':temp,'drive':drive,'window':index+1,
                                'mode':mode,'time_s':row['time_s'],'current_A':row['sensor_current_A'],
                                'measured_voltage_V':row['sensor_voltage_V'],'ekf_prior_voltage_V':row['voltage_ekf_prior_V'],
                                'ukf_prior_voltage_V':row['voltage_ukf_prior_V'],'soc_proxy':row['soc_reference'],
                                'soc_ekf':row['soc_ekf'],'soc_ukf':row['soc_ukf']} for row in series)
                    print(role,cell,temp,drive,flush=True)
    write_csv(out/'calb_metrics.csv',results);write_csv(out/'calb_traces.csv',traces)
    summary=[]
    for role in ('development','test'):
        for mode in ('fixed_start','estimated_grid'):
            group=[r for r in results if r['role']==role and r['mode']==mode]
            summary.append({'role':role,'mode':mode,'windows':len(group),
                **{key:float(np.mean([r[key] for r in group])) for key in ('ekf_prior_voltage_rmse_mV','ukf_prior_voltage_rmse_mV','ekf_soc_proxy_rmse','ukf_soc_proxy_rmse')}})
    save(out/'calb_validation.json',{'summary':summary,'records':results,'candidate_selection':candidate_rows,'time_audit':TIME_AUDIT,
        'source_manifest_sha256':hashlib.sha256((DATA/'manifest.json').read_bytes()).hexdigest(),
        'one_step_voltage':'filter prediction before current observation; not open-loop voltage',
        'limitations':'same-cell pulse-calibrated per-cell models; 2 development and 2 held-out cells; temperature setpoint; SOC proxy; not hardware validation'})
    metrics={'selected_voltage_noise_V':selected,'test_windows':sum(r['role']=='test' for r in results)//2,
             'elapsed_s':time.perf_counter()-start}
    for r in summary:
        if r['role']=='test':
            for key in ('ekf_prior_voltage_rmse_mV','ekf_soc_proxy_rmse'):
                metrics[r['mode']+'_'+key]=r[key]
    return finish(config,out,{'kind':'engineering','title':'CALB同电芯脉冲与驾驶工况滤波器验证',
        'metrics':metrics,'comparisons':summary,'details':{'scope':'HPPC与C/20按同一电芯和温度标定；驾驶记录留出，后验前电压单步预测；SOC是近似代理参考；仅软件回放。'}},
        results,packages=['sox','scipy','numpy'])

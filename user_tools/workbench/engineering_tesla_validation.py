"""Open Tesla benchmark: cold-temperature OCV/RC transfer across cells."""
from pathlib import Path
import copy
import hashlib
import json
import time
import zlib
import numpy as np
from scipy.io import loadmat
from scipy.integrate import cumulative_trapezoid
from scipy.optimize import least_squares
from scipy.signal import lfilter
from user_tools.workbench.engineering_common import ROOT,finish,save,write_csv
from user_tools.workbench.engineering_contracts import defaults
from user_tools.workbench.engineering_bms import estimate_stream,ocv_function
from user_tools.workbench.engineering_rc_grid import make_rc_interpolator,make_ocv_interpolator

DATA=ROOT/'data/public/tesla_soc_benchmark_v3'
SOURCE='https://doi.org/10.5683/SP3/ZVTR4B'
TEMPS=(-20,-10,0,10,25)
VARIANTS=('reference_25','ocv_temperature','rc_temperature','ocv_and_rc_temperature')


def verify_data():
    path=DATA/'manifest.json';manifest=json.loads(path.read_text(encoding='utf8'))
    if manifest['failures'] or len(manifest['files'])!=126:raise ValueError('Tesla数据清单不完整。')
    for item in manifest['files']:
        raw=(ROOT/item['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=item['sha256'] or f'{zlib.crc32(raw)&0xffffffff:08x}'!=item['crc32']:
            raise ValueError('Tesla数据文件校验失败：'+item['path'])
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(cell,temp,kind):
    path=DATA/cell/f'{temp}C'/(kind+'.mat')
    x=loadmat(path,simplify_cells=True)['meas']
    required=('Time','Current','Voltage','SOC','Battery_Temp_degC')
    out={k:np.asarray(x[k],float) for k in required}
    if len(out['Time'])<100 or not all(np.isfinite(v).all() for v in out.values()):raise ValueError('Tesla数据非有限或过短：'+str(path))
    if np.any(np.diff(out['Time'])<=0):raise ValueError('Tesla时间戳非递增：'+str(path))
    if np.min(out['SOC'])<-.02 or np.max(out['SOC'])>1.02:raise ValueError('Tesla SOC参考范围异常：'+str(path))
    return out


def ocv_from_c20(temp):
    x=load('m80',temp,'c20')
    mask=(x['Current']<-.1)&(np.abs(x['Battery_Temp_degC']-temp)<7)&(x['SOC']>=0)&(x['SOC']<=1)
    s=x['SOC'][mask];v=x['Voltage'][mask]
    if len(s)<200 or np.min(s)>.16 or np.max(s)<.95:raise ValueError(f'{temp}°C C/20放电SOC或温度覆盖不足')
    # Use narrow SOC bins, then enforce monotonicity rather than fitting drive data.
    bins=np.round(s*1000).astype(int);ids=np.unique(bins)
    soc=ids/1000.;values=np.array([np.median(v[bins==i]) for i in ids])
    return soc,np.maximum.accumulate(values)


def pulse_fit(temp):
    x=load('m80',temp,'hppc');t=x['Time'];i=x['Current'];v=x['Voltage'];s=x['SOC']
    active=i < -3.;edge=np.diff(np.r_[False,active,False].astype(int));starts=np.flatnonzero(edge==1);ends=np.flatnonzero(edge==-1)-1
    nodes=[];cum=cumulative_trapezoid(-i,t,initial=0)
    for a,b in zip(starts,ends):
        dur=t[b]-t[a];amp=-float(np.median(i[a:b+1]))
        if not 7<=dur<=12 or not 3<=amp<=6.5 or t[a]+120>t[-1]:continue
        soc=float(s[a]);times=t[a]+np.arange(1.,121.)
        if not 0<=soc<=1.001:continue
        voltage=np.interp(times,t,v);charge=np.interp(np.r_[t[a],times],t,cum);current=np.diff(charge)
        before=float(v[max(0,a-1)])
        def prediction(p):
            r0,r1,tau=np.exp(p[:3]);decay=np.exp(-1/tau)
            return p[3]-r0*current-lfilter([r1*(1-decay)],[1.,-decay],current)
        fit=least_squares(lambda p:prediction(p)-voltage,[np.log(.03),np.log(.02),np.log(15.),before],
            bounds=([np.log(.0001),np.log(.00001),np.log(.25),before-.1],
                    [np.log(.8),np.log(.8),np.log(600.),before+.1]),max_nfev=180,loss='soft_l1',f_scale=.01)
        r0,r1,tau=np.exp(fit.x[:3]);nodes.append({'soc':min(soc,1.),'R0_ohm':float(r0),'R1_ohm':float(r1),'C1_F':float(tau/r1),
            'ocv_V':float(fit.x[3]),'fit_rmse_mV':float(np.sqrt(np.mean(fit.fun**2))*1000),'at_bound':bool(np.any(fit.active_mask!=0))})
    nodes.sort(key=lambda row:row['soc'])
    # Multiple experiments at the same SOC are summarized instead of inventing nodes.
    grouped={}
    for node in nodes:grouped.setdefault(round(node['soc'],4),[]).append(node)
    result=[{'soc':float(soc),**{key:float(np.median([r[key] for r in group])) for key in ('R0_ohm','R1_ohm','C1_F','ocv_V','fit_rmse_mV')},
             'at_bound':any(r['at_bound'] for r in group)} for soc,group in sorted(grouped.items())]
    if len(result)<4:raise ValueError(f'{temp}°C HPPC短脉冲节点不足')
    return result


def train_model(ocv_source='c20'):
    slow={temp:ocv_from_c20(temp) for temp in TEMPS};pulses={temp:pulse_fit(temp) for temp in TEMPS}
    if ocv_source=='hppc_rest':
        slow={temp:(np.array([x['soc'] for x in pulses[temp]]),np.maximum.accumulate([x['ocv_V'] for x in pulses[temp]])) for temp in TEMPS}
    elif ocv_source in ('c20_corrected_half','c20_corrected','c20_corrected_double'):
        factor={'c20_corrected_half':.5,'c20_corrected':1.,'c20_corrected_double':2.}[ocv_source]
        corrected={}
        for temp in TEMPS:
            x=load('m80',temp,'c20');mask=(x['Current']<-.1)&(np.abs(x['Battery_Temp_degC']-temp)<7)
            current=float(np.median(-x['Current'][mask]));s,v=slow[temp];nodes=pulses[temp];sn=[r['soc'] for r in nodes]
            # Only compare on the intersection of C20 and pulse SOC coverage.
            inside=(s>=sn[0])&(s<=sn[-1]);s=s[inside];v=v[inside]
            resistance=np.interp(s,sn,[r['R0_ohm']+r['R1_ohm'] for r in nodes])
            corrected[temp]=(s,np.maximum.accumulate(v+factor*current*resistance))
        slow=corrected
    elif ocv_source!='c20':raise ValueError('Unknown OCV source')
    lo=max(max(slow[t][0][0],pulses[t][0]['soc']) for t in TEMPS)+.0001
    hi=min(min(slow[t][0][-1],pulses[t][-1]['soc']) for t in TEMPS)-.0001
    if lo>=.3 or hi<=.8:raise ValueError(f'Tesla source SOC coverage insufficient [{lo},{hi}]')
    grid=np.linspace(lo,hi,14);rc=[];ocv=[]
    for s in grid:
        for temp in TEMPS:
            x=pulses[temp];sx=[v['soc'] for v in x]
            rc.append({'soc':float(s),'temperature_C':float(temp),**{key:float(np.interp(s,sx,[v[key] for v in x])) for key in ('R0_ohm','R1_ohm','C1_F')}})
            ocv.append({'soc':float(s),'temperature_C':float(temp),'ocv_V':float(np.interp(s,*slow[temp]))})
    cap=load('m80',25,'capacity40');aux=loadmat(DATA/'m80'/'25C'/'capacity40.mat',simplify_cells=True)['meas']
    capacity=float(np.max(np.abs(np.asarray(aux['Ah'],float))))
    if not 2<capacity<6:raise ValueError('Tesla标定容量异常')
    o25=[v['ocv_V'] for v in ocv if v['temperature_C']==25]
    cfg=defaults('ecm_bms')['cell'];cfg.update(cell_id='Tesla-pooled-m80',capacity_Ah=capacity,
        ocv_soc=[0.,*grid.tolist(),1.],ocv_V=[o25[0],*o25,o25[-1]],rc_table=rc,ocv_temperature_table=ocv,rc_interpolation='linear')
    return cfg,{'training_cell':'m80','hpcc_nodes':pulses,'ocv_source':ocv_source,'ocv_soc_ranges':{str(t):[float(slow[t][0][0]),float(slow[t][0][-1])] for t in TEMPS},
               'common_soc_range':[float(lo),float(hi)],'capacity_Ah':capacity}


def windows(cell,temp,kind):
    x=load(cell,temp,kind);t=x['Time'];q=cumulative_trapezoid(-x['Current'],t,initial=0)
    output=[]
    for fraction in (.2,.6):
        start=float(t[0]+fraction*(t[-1]-t[0]-1800.));times=start+np.arange(1801.)
        if times[-1]>t[-1]:raise ValueError('Tesla驾驶记录不够长')
        right=np.minimum(np.searchsorted(t,times),len(t)-1);left=np.maximum(right-1,0)
        if np.max(np.minimum(abs(times-t[left]),abs(times-t[right])))>.51:raise ValueError('Tesla窗口采样稀疏')
        charge=np.interp(times,t,q);current=np.r_[-float(np.interp(times[0],t,x['Current'])),np.diff(charge)]
        output.append({'start_s':start,'current':current,'voltage':np.interp(times,t,x['Voltage']),
            'soc_reference':np.interp(times,t,x['SOC']),'surface':np.interp(times,t,x['Battery_Temp_degC'])})
    return output


def score(model,temp,window,variant,*,use_ukf=True,voltage_noise=.01,soc_q=1e-8,constraint='strict'):
    cfg=defaults('ecm_bms');cfg['cell']=copy.deepcopy(model);cell=cfg['cell'];cell['temperature_C']=temp
    initial=float(window['soc_reference'][0]-.04);cell['estimated_initial_soc']=initial
    use_rc=variant in ('rc_temperature','ocv_and_rc_temperature');use_ocv=variant in ('ocv_temperature','ocv_and_rc_temperature')
    p=make_rc_interpolator(cell['rc_table'],1)(initial,temp if use_rc else 25.)
    cell.update(R0_ohm=p['R0_ohm'],R_ohm=[p['R1_ohm']],C_F=[p['C1_F']])
    cfg['filter_rc_mode']='fixed';cfg['filter_ocv_mode']='soc_temperature' if use_ocv else 'soc_only'
    cfg['voltage_noise_V']=voltage_noise;cfg['current_noise_A']=0.;cfg['enable_ukf']=use_ukf
    cfg['soc_constraint']=constraint
    cfg['soc_process_variance_per_step']=soc_q
    rows=[{'time_s':float(k),'sensor_current_A':float(i),'sensor_voltage_V':float(v),
           'measured_temperature_C':float(temp),'soc_reference':float(s)}
          for k,(i,v,s) in enumerate(zip(window['current'],window['voltage'],window['soc_reference']))]
    output,metrics=estimate_stream(cfg,rows)
    # Open-loop voltage: same initial SOC as filter, no later measured voltage.
    ocv=make_ocv_interpolator(cell['ocv_temperature_table']) if use_ocv else None
    reference_ocv=ocv_function(cell);soc=initial;eta=0.;pred=[]
    try:
        for k,current in enumerate(window['current']):
            if k:
                a=np.exp(-1/(p['R1_ohm']*p['C1_F']));eta=a*eta+p['R1_ohm']*(1-a)*current
                soc-=current/(3600*cell['capacity_Ah'])
            value=ocv(soc,temp) if use_ocv else reference_ocv(soc)
            pred.append(value-eta-current*p['R0_ohm'])
        metrics['open_loop_voltage_rmse_mV']=float(np.sqrt(np.mean((np.array(pred)-window['voltage'])**2))*1000)
        metrics['open_loop_status']='ok'
    except ValueError as exc:
        if '不支持外推' not in str(exc):raise
        metrics['open_loop_voltage_rmse_mV']=None;metrics['open_loop_status']='outside_domain'
    return metrics,output


def run_tesla(config,out):
    started=time.perf_counter();digest=verify_data();out=Path(out);out.mkdir(parents=True,exist_ok=True)
    model,audit=train_model();save(out/'tesla_model.json',{'model':model,'calibration':audit,
        'reference':'published capacity-corrected SOC field, a coulomb-count reference, not direct SOC sensing',
        'temperature':'nominal chamber setpoint; 40C C20 was not used due inconsistent recorded case temperature'})
    records=[];traces=[]
    def evaluate(role,cell,drives):
        for temp in TEMPS:
            for drive in drives:
                for wi,window in enumerate(windows(cell,temp,drive)):
                    for variant in VARIANTS:
                        status='ok';err='';rows=[]
                        try:m,rows=score(model,temp,window,variant)
                        except ValueError as exc:
                            if '不支持外推' not in str(exc) and 'SOC超出' not in str(exc):raise
                            status='outside_domain';err=str(exc);m=None
                        records.append({'role':role,'cell_id':cell,'temperature_C':temp,'drive':drive,'window':wi+1,'variant':variant,
                            'status':status,'reason':err,'start_s':window['start_s'],
                            'ekf_prior_voltage_rmse_mV':m['ekf_prior_voltage_rmse_V']*1000 if m else None,
                            'ekf_soc_reference_rmse':m['ekf_rmse_soc'] if m else None,
                            'open_loop_voltage_rmse_mV':m['open_loop_voltage_rmse_mV'] if m else None,
                            'ekf_outside_physical_soc_points':sum(not 0<=r['soc_ekf']<=1 for r in rows) if m else None,
                            'ukf_outside_physical_soc_points':sum(not 0<=r['soc_ukf']<=1 for r in rows) if m else None})
                        traces.extend({'role':role,'cell_id':cell,'temperature_C':temp,'drive':drive,'window':wi+1,'variant':variant,
                            'time_s':r['time_s'],'current_A':r['sensor_current_A'],'voltage_V':r['sensor_voltage_V'],
                            'soc_reference':r['soc_reference'],'soc_ekf':r['soc_ekf'],'ekf_prior_voltage_V':r['voltage_ekf_prior_V']} for r in rows)
                print(role,cell,temp,drive,flush=True)
    evaluate('development','m448-N',('drive1','drive2'))
    dev=[]
    for variant in VARIANTS:
        group=[r for r in records if r['variant']==variant];valid=[r for r in group if r['status']=='ok']
        dev.append({'variant':variant,'windows':len(group),'valid_windows':len(valid),
                    'prior_mV':float(np.mean([r['ekf_prior_voltage_rmse_mV'] for r in valid])) if valid else None})
    eligible=[d for d in dev if d['valid_windows']==d['windows']]
    if not eligible:raise ValueError('所有Tesla开发候选存在越界，不能选择方法。')
    chosen=min(eligible,key=lambda d:d['prior_mV'])['variant']
    save(out/'tesla_pretest_freeze.json',{'development':dev,'selected_variant':chosen,'test_cell':'m1000',
        'test_drives':['drive5','drive6'],'test_signals_decoded':False,'archive_scope':'per-entry ZIP CRC and local SHA256; full archive MD5 not checked'})
    evaluate('test','m1000',('drive5','drive6'))
    write_csv(out/'tesla_metrics.csv',records);write_csv(out/'tesla_traces.csv',traces)
    summary=[]
    for role in ('development','test'):
        for variant in VARIANTS:
            group=[r for r in records if r['role']==role and r['variant']==variant];valid=[r for r in group if r['status']=='ok']
            summary.append({'role':role,'variant':variant,'total_windows':len(group),'valid_windows':len(valid),
                **{key:(float(np.mean([r[key] for r in valid if r[key] is not None])) if any(r[key] is not None for r in valid) else None) for key in ('ekf_prior_voltage_rmse_mV','ekf_soc_reference_rmse','open_loop_voltage_rmse_mV')}})
    save(out/'tesla_validation.json',{'summary':summary,'records':records,'manifest_sha256':digest,
         'scope':'unseen target cell, source-only model, reference-informed -4pp window initialization; status/coverage retained'})
    metrics={'test_cell':'m1000','selected_variant':chosen,'elapsed_s':time.perf_counter()-started}
    for r in summary:
        if r['role']=='test':
            for key in ('valid_windows','ekf_prior_voltage_rmse_mV','ekf_soc_reference_rmse','open_loop_voltage_rmse_mV'):
                metrics[r['variant']+'_'+key]=r[key]
    return finish(config,out,{'kind':'engineering','title':'Tesla低温跨电芯OCV与RC公开验证','metrics':metrics,
       'comparisons':summary,'details':{'scope':'以m80的C/20和HPPC构建模型；m448-N开发选择、m1000工况留出。SOC参考由作者的容量和电流积分构造，不是直接SOC测量。'}},records,packages=['sox','scipy','numpy'])

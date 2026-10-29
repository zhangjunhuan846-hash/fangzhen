"""Retrospective EIS increment test on already-inspected CALB records.

This deliberately cannot establish prospective benefit: EIS was measured later.
"""
from pathlib import Path
import copy,hashlib,json
import numpy as np
from scipy.io import loadmat
from scipy.integrate import cumulative_trapezoid
from user_tools.workbench import engineering_calb_validation as base
from user_tools.workbench.engineering_calb_validation_v2 import verify_extra
from user_tools.workbench.engineering_common import ROOT,save,write_csv,finish
from user_tools.workbench.engineering_contracts import defaults
from user_tools.workbench.engineering_eis_audit import lin_kk
from user_tools.workbench.engineering_eis_hppc_joint import fit_methods
from user_tools.workbench.engineering_bms import estimate_stream,ocv_function
from user_tools.workbench.engineering_rc_grid import make_rc_interpolator
from user_tools.workbench.engineering_eis_hppc_report import write_report

OUT=ROOT/'outputs/eis_bms_validation/calb_eis_hppc_ablation_20261029'
CELL='60129';TEMP=25
METHODS=('hppc_only','eis_initial','joint')

def pulse_from_node(raw,node):
    t,i,v=raw['t'],raw['i'],raw['v'];start=node['pulse_start_s'];times=start+np.arange(1.,121.)
    a=int(np.searchsorted(t,start));q=cumulative_trapezoid(-i,t,initial=0)
    return {'current':np.diff(np.interp(np.r_[start,times],t,q)),
            'voltage':np.interp(times,t,v),'pre_voltage':float(v[max(0,a-1)])}

def table_for(nodes,method):
    # Fixed endpoint hold is explicit and identical for all three approaches.
    ordered=sorted(nodes,key=lambda x:x['soc']);entries=[]
    for soc,row in [(0.,ordered[0])]+[(x['soc'],x) for x in ordered]+[(1.,ordered[-1])]:
        p=row['fit'][method];entries.append({'soc':float(soc),'temperature_C':float(TEMP),
            'R0_ohm':p['R0_ohm'],'R1_ohm':p['R1_ohm'],'C1_F':p['tau_s']/p['R1_ohm']})
    return entries

def evaluate(cell,window):
    cfg=defaults('ecm_bms');cfg['cell']=copy.deepcopy(cell);cfg['cell']['estimated_initial_soc']=float(window['soc_proxy'][0]-.04)
    cfg.update(filter_rc_mode='estimated_grid',voltage_noise_V=.005,current_noise_A=0.,enable_ukf=False,soc_constraint='strict')
    lookup=make_rc_interpolator(cell['rc_table'],1);ocv=ocv_function(cell)
    rows=[{'time_s':float(k),'sensor_current_A':float(i),'sensor_voltage_V':float(v),'measured_temperature_C':float(TEMP),
           'soc_reference':float(s)} for k,(i,v,s) in enumerate(zip(window['current'],window['voltage'],window['soc_proxy']))]
    out,met=estimate_stream(cfg,rows)
    soc=float(window['soc_proxy'][0]-.04);eta=0.;pred=[];post=[];held=0
    previous_filter_soc=float(window['soc_proxy'][0]-.04)
    for k,(cur,r) in enumerate(zip(window['current'],out)):
        if k:
            p=lookup(soc,TEMP);a=np.exp(-1/(p['R1_ohm']*p['C1_F']));eta=a*eta+p['R1_ohm']*(1-a)*cur;soc-=cur/(3600*cell['capacity_Ah'])
        p=lookup(soc,TEMP);pred.append(ocv(soc)-eta-cur*p['R0_ohm'])
        # estimated_grid uses R0 from the prior filter state for the whole
        # measurement update; reproduce that same measurement equation.
        rpost=lookup(previous_filter_soc,TEMP)['R0_ohm']
        post.append(ocv(float(r['soc_ekf']))-r['eta_ekf_1_V']-cur*rpost)
        previous_filter_soc=float(r['soc_ekf'])
        held+=int(soc<.2 or soc>.8)
    v=window['voltage'];prior=np.array([r['voltage_ekf_prior_V'] for r in out]);posterior=np.array(post)
    def rms(delta):return float(np.sqrt(np.mean(np.asarray(delta)**2))*1000)
    return {'open_loop_rmse_mV':rms(np.array(pred)-v),'ekf_prior_rmse_mV':rms(prior-v),
         'ekf_posterior_residual_rmse_mV':rms(posterior-v),'soc_proxy_rmse_pp':met['ekf_rmse_soc']*100,
         'endpoint_hold_fraction':held/len(v)},pred,prior,posterior,out

def run_ablation(config,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True);manifest=verify_extra()
    ref=base.slow_reference(CELL,TEMP);raw=base.load(CELL,TEMP,'hppc_1c');hppc=base.fit_hppc(CELL,TEMP,ref['capacity'])
    eis=loadmat(base.EXTRA_DATA/'Temperature_25C/eis_test/60129.mat',simplify_cells=True)['Data']
    if not isinstance(eis,list) or len(eis)!=4:raise ValueError('期望四条EIS谱')
    nodes=[];audit=[];used=set()
    for nominal,spectrum in zip((.8,.6,.4,.2),eis):
        j=min(range(len(hppc)),key=lambda k:abs(hppc[k]['soc']-nominal))
        if j in used or abs(hppc[j]['soc']-nominal)>.06:raise ValueError('HPPC SOC匹配不足，停止。')
        used.add(j);m=spectrum['meas'];f=np.asarray(m['Frequency'],float);z=np.asarray(m['Zreal'],float)+1j*np.asarray(m['Zimg'],float)
        keep=(f>=.5)&(f<=1000);f,z=f[keep],z[keep];_,kk=lin_kk(f,z,True)
        inferred=float(np.interp(float(spectrum['OCV_value']),ref['reference_voltage'],ref['reference_soc']))
        audit.append({'nominal_eis_soc':nominal,'hppc_soc_proxy':hppc[j]['soc'],'eis_c20_voltage_inferred_soc':inferred,
                      'points':len(f),'lin_kk':kk,'timestamp_order':'EIS later than HPPC and drive'})
        if not kk['screening_pass']:
            save(out/'screening_rejected.json',{'spectra':audit,'reason':'Lin-KK screen failed'});raise ValueError('EIS质量筛查未通过')
        fits=fit_methods(pulse_from_node(raw,hppc[j]),{'frequency_Hz':f,'impedance':z},kk['screening_pass'])
        nodes.append({'soc':float(nominal),'hppc_soc_proxy':hppc[j]['soc'],'fit':fits})
    # OCV and capacity are identical across all methods and from HPPC/C20.
    model,_,_=base.fit_cell(CELL)
    models={}
    for method in METHODS:
        cell=copy.deepcopy(model);cell['temperature_C']=TEMP;cell['rc_table']=table_for(nodes,method);cell['rc_interpolation']='linear';models[method]=cell
    frozen={'cell':CELL,'temperature_C':TEMP,'models':models,'node_fits':nodes,'eis_audit':audit,'manifest_sha256':manifest,
       'procedure':{'spectrum_band_Hz':[.5,1000.],'time_scale_V':.005,'frequency_scale':'pointwise |Z|',
          'joint_weights':'1/2 per normalized group','starts_per_method':3,'tau_bounds_s':[.25,600],
          'common_initial_soc':'C/20 based window proxy minus 4 percentage points','ocv_and_capacity':'same HPPC/C20 per method',
          'evaluation':'3 C/3 pulse and six 600s driving windows; outputs have previously been examined',
          'eis_temporal_order':'later than all scored signals: retrospective, not prospective',
          'quality':'Lin-KK screen per spectrum; not proof of physical identity or state match'}}
    save(out/'frozen_models.json',frozen)
    # All choices/models saved before this run loads the comparison signals.
    records=[];traces=[]
    windows=[('pulse_C3',k+1,w) for k,w in enumerate(base.pulse_windows(CELL,TEMP,ref))]
    for drive in base.DRIVES:windows.extend((drive,k+1,w) for k,w in enumerate(base.windows(CELL,TEMP,drive,ref)))
    for kind,index,window in windows:
        for method in METHODS:
            metrics,pred,prior,post,rows=evaluate(models[method],window)
            records.append({'cell':CELL,'temperature_C':TEMP,'window_type':kind,'window':index,'method':method,
                'start_s':window['start_s'],'duration_s':len(window['current'])-1,**metrics})
            traces.extend({'window_type':kind,'window':index,'method':method,'time_s':r['time_s'],
                'measured_voltage_V':r['sensor_voltage_V'],'current_A':r['sensor_current_A'],
                'open_loop_voltage_V':float(pred[k]),'ekf_prior_voltage_V':float(prior[k]),
                'ekf_posterior_voltage_V':float(post[k]),'soc_proxy':r['soc_reference'],'soc_ekf':r['soc_ekf']}
                for k,r in enumerate(rows))
    write_csv(out/'window_metrics.csv',records);write_csv(out/'window_traces.csv',traces)
    summary=[]
    for method in METHODS:
        for kind in ('pulse_C3','driving'):
            r=[x for x in records if x['method']==method and (x['window_type']=='pulse_C3')==(kind=='pulse_C3')]
            summary.append({'method':method,'group':kind,'n_windows':len(r),
               **{key:float(np.mean([x[key] for x in r])) for key in ('open_loop_rmse_mV','ekf_prior_rmse_mV','ekf_posterior_residual_rmse_mV','soc_proxy_rmse_pp','endpoint_hold_fraction')}})
    save(out/'summary.json',{'summary':summary,'records':records,
         'qualification':'回顾性、已暴露数据；非新电芯、非独立盲测；EIS与HPPC SOC/老化状态匹配不能完全确认；禁止自动用于硬件/BMS。'})
    # One representative 600s window for UI; all traces are separately saved.
    chosen=[x for x in traces if x['window_type']=='dv_wltp' and x['window']==1 and x['method']=='hppc_only']
    write_report(out/'ablation_report.html',summary,chosen)
    curve={'name':'HPPC基线：开环与实测','y_label':'电压 (V)','primary':'开环预测','secondary':'实测',
       'points':[[r['time_s'],r['open_loop_voltage_V'],r['measured_voltage_V']] for r in chosen]}
    demo={s['method']:s for s in summary if s['group']=='driving'}
    metrics={}
    for method,row in demo.items():
        for key in ('open_loop_rmse_mV','ekf_prior_rmse_mV','ekf_posterior_residual_rmse_mV','soc_proxy_rmse_pp'):
            metrics[method+'_'+key]=row[key]
    source_code=Path(__file__).read_bytes();(out/'ablation_runner.py').write_bytes(source_code)
    result={'kind':'engineering','title':'CALB EIS与HPPC回顾性对照','metrics':metrics,'comparisons':summary,
       'runner_sha256':hashlib.sha256(source_code).hexdigest(),
       'details':{'scope':'同电芯25°C，EIS在被回放工况之后测得，SOC与老化状态不完全匹配；此前记录已被查看。结果仅为回顾性方法对照，不能说明事前预测或自动导入BMS；SOC是代理参考。'},
       'eis_used':True,'physical_hardware':False}
    return finish(config,out,result,records,[curve],packages=['numpy','scipy','sox','impedance'])

def main():
    config=defaults('eis_hppc_ablation');result=run_ablation(config,OUT);print(json.dumps(result['comparisons'],indent=2))
if __name__=='__main__':main()

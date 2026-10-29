"""W8 earlier HPPC -> later drive open loop; SOC and RC state are estimates."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from scipy.integrate import cumulative_trapezoid
from scipy.optimize import least_squares

OUT=Path('outputs/eis_bms_validation/stanford_w8_openloop_20261029')

def unique_time(df):
    df=df.drop_duplicates('time_s',keep='last').copy()
    if (np.diff(df.time_s.to_numpy())<=0).any():raise ValueError('timestamp order invalid')
    return df

def weighted_rmse(error,t):
    duration=t[-1]-t[0]
    return float(np.sqrt(np.trapezoid(error**2,t)/duration)) if duration>0 else None

def main():
    cap=unique_time(pd.read_csv(OUT/'capacity_source.csv.gz'))
    h=unique_time(pd.read_csv(OUT/'hppc_source.csv.gz'))
    cycle=cap[cap.step==5];capacity=float(cycle.discharge_Ah.iloc[-1]-cycle.discharge_Ah.iloc[0])
    if not 4<capacity<6:raise ValueError('Unexpected measured capacity')
    # Starting state after 1 h rest at end of HPPC CC-CV charge is SOC=1.
    top=h[(h.step==4)&(h.cycle==1)].iloc[-1]
    h=h[h.time_s>=top.time_s].copy().reset_index(drop=True)
    t=h.time_s.to_numpy(); dis=-h.current_A.to_numpy();q=cumulative_trapezoid(dis,t,initial=0)/3600
    h['soc_proxy']=1-q/capacity
    ocv=[{'soc':1.,'voltage_V':float(top.voltage_V),'source':'HPPC post-charge 1h rest'}]
    nodes=[]
    for cyc in sorted(h.cycle.unique()):
        rest=h[(h.cycle==cyc)&(h.step==6)];pulse=h[(h.cycle==cyc)&(h.step==7)];relax=h[(h.cycle==cyc)&(h.step==8)]
        if min(len(rest),len(pulse),len(relax))<2:continue
        anchor=rest.iloc[-1];s=float(anchor.soc_proxy)
        if not 0<=s<=1:continue
        ocv.append({'soc':s,'voltage_V':float(rest.tail(30).voltage_V.median()),'source':'HPPC rest tail'})
        seg=pd.concat([rest.tail(1),pulse,relax]);tt=seg.time_s.to_numpy();ii=-seg.current_A.to_numpy();vv=seg.voltage_V.to_numpy()
        # Input during each interval is approximated by its left-hand sample;
        # R0 is applied at each observation, with unobserved sub-sample edges.
        def predict(p):
            r0,r1,tau=np.exp(p[:3]);eta=np.zeros(len(tt))
            for k in range(1,len(tt)):
                a=np.exp(-(tt[k]-tt[k-1])/tau);eta[k]=a*eta[k-1]+r1*(1-a)*ii[k-1]
            return p[3]-r0*ii-eta
        initial=np.array([.02,.01,10.,float(anchor.voltage_V)])
        fit=least_squares(lambda x:predict(x)-vv,[*np.log(initial[:3]),initial[3]],
            bounds=([*np.log([.0001,.0001,.1]),initial[3]-.05],[*np.log([.2,.2,1000]),initial[3]+.05]),max_nfev=300)
        r0,r1,tau=np.exp(fit.x[:3]);nodes.append({'soc':s,'R0_ohm':float(r0),'R1_ohm':float(r1),'tau_s':float(tau),
            'fit_rmse_mV':float(np.sqrt(np.mean(fit.fun**2))*1000),'at_bound':bool(np.any(fit.active_mask)),'success':bool(fit.success),'cycle':int(cyc)})
    ocv.sort(key=lambda x:x['soc']);nodes.sort(key=lambda x:x['soc'])
    if len(nodes)<5 or not all(n['success'] for n in nodes):raise ValueError('Insufficient valid HPPC nodes')
    for rows in (ocv,nodes):
        if np.any(np.diff([r['soc'] for r in rows])<=0):raise ValueError('duplicate SOC nodes')
    model={'source':'HPPC only; EIS not used','capacity_Ah':capacity,'ocv_points':ocv,'rc_nodes':nodes,
       'soc_definition':'1 at end of HPPC 1h post-CCCV rest, Coulomb counting at measured C/20 capacity',
       'scope':'1RC pulses with 1h pre-rest; temperature 23C nominal, no thermal model; effective parameters',
       'outside_rc_grid':'hold nearest endpoint and count; no SOC extrapolation for OCV',
       'freeze':'written before reading dynamic source file'}
    (OUT/'frozen_hppc_model.json').write_text(json.dumps(model,indent=2),encoding='utf8')
    # First read later dynamic measurements only after model has been written.
    drive=unique_time(pd.read_csv(OUT/'drive_source.csv.gz'))
    start=drive[drive.step==4].iloc[-1]; drive=drive[drive.time_s>=start.time_s].copy().reset_index(drop=True)
    tt=drive.time_s.to_numpy();tt=tt-tt[0];ii=-drive.current_A.to_numpy();v=drive.voltage_V.to_numpy()
    soc=1-cumulative_trapezoid(ii,tt,initial=0)/(3600*capacity)
    os=np.array([r['soc'] for r in ocv]);ov=np.array([r['voltage_V'] for r in ocv]);ns=np.array([r['soc'] for r in nodes])
    if soc.min()<os[0]-1e-5 or soc.max()>os[-1]+1e-5:raise ValueError('dynamic SOC outside OCV data: refusing extrapolation')
    r0=np.interp(soc,ns,[r['R0_ohm'] for r in nodes]);r1=np.interp(soc,ns,[r['R1_ohm'] for r in nodes]);tau=np.interp(soc,ns,[r['tau_s'] for r in nodes])
    eta=np.zeros(len(tt)) # after one-hour rest; slower residual polarization is unknown
    for k in range(1,len(tt)):
        a=np.exp(-(tt[k]-tt[k-1])/tau[k-1]);eta[k]=a*eta[k-1]+r1[k-1]*(1-a)*ii[k-1]
    predicted=np.interp(soc,os,ov)-r0*ii-eta;error=predicted-v
    traces=pd.DataFrame({'time_s':tt,'step':drive.step,'current_discharge_A':ii,'measured_V':v,'model_V':predicted,
         'residual_V':error,'soc_proxy':soc,'polarization_V':eta,'surface_C':drive.surface_C,
         'rc_endpoint_hold':(soc<ns[0])|(soc>ns[-1])})
    traces.to_csv(OUT/'openloop_trace.csv.gz',index=False,compression='gzip')
    metrics=[]
    for label,mask in [('pre_discharge_and_dynamic',drive.step.isin([13,14]).to_numpy()),('dynamic_only',drive.step.eq(14).to_numpy())]:
        a=traces[mask];at=a.time_s.to_numpy();e=a.residual_V.to_numpy()
        metrics.append({'segment':label,'rmse_mV_time_weighted':1000*weighted_rmse(e,at),'mae_mV_time_weighted':float(1000*np.trapezoid(abs(e),at)/(at[-1]-at[0])),
           'max_abs_error_mV':float(1000*max(abs(e))),'duration_s':float(at[-1]-at[0]),'target_coverage':1.0,
           'endpoint_hold_time_fraction':float(np.trapezoid(a.rc_endpoint_hold.astype(float),at)/(at[-1]-at[0])),
           'charge_integral_Ah':float(np.trapezoid(a.current_discharge_A,at)/3600),
           'voltage_cutoff_metric':'not applicable: this segment is not a discharge-to-cutoff test'})
    pd.DataFrame(metrics).to_csv(OUT/'openloop_metrics.csv',index=False)
    print(json.dumps(metrics,indent=2))
if __name__=='__main__':main()

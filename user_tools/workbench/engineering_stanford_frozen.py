"""Reusable frozen W8 1RC replay. This module never fits on replay voltage."""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.integrate import cumulative_trapezoid
from scipy.optimize import least_squares


def fit_hppc(cap,h):
    """The frozen W8 calibration procedure, also usable on a new cell."""
    cap=cap.drop_duplicates('time_s',keep='last');h=h.drop_duplicates('time_s',keep='last')
    c=cap[cap.step==5];capacity=float(c.discharge_Ah.iloc[-1]-c.discharge_Ah.iloc[0])
    if not 4<capacity<6:raise ValueError('Unexpected measured capacity')
    top=h[(h.step==4)&(h.cycle==1)].iloc[-1];h=h[h.time_s>=top.time_s].copy().reset_index(drop=True)
    h['soc_proxy']=1-cumulative_trapezoid(-h.current_A.to_numpy(),h.time_s.to_numpy(),initial=0)/(3600*capacity)
    ocv=[{'soc':1.,'voltage_V':float(top.voltage_V),'source':'HPPC post-charge 1h rest'}];nodes=[]
    for cyc in sorted(h.cycle.unique()):
        rest=h[(h.cycle==cyc)&(h.step==6)];pulse=h[(h.cycle==cyc)&(h.step==7)];relax=h[(h.cycle==cyc)&(h.step==8)]
        if min(len(rest),len(pulse),len(relax))<2:continue
        anchor=rest.iloc[-1];s=float(anchor.soc_proxy)
        if not 0<=s<=1:continue
        ocv.append({'soc':s,'voltage_V':float(rest.tail(30).voltage_V.median()),'source':'HPPC rest tail'})
        seg=pd.concat([rest.tail(1),pulse,relax]);t=seg.time_s.to_numpy();i=-seg.current_A.to_numpy();v=seg.voltage_V.to_numpy()
        def predict(p):
            r0,r1,tau=np.exp(p[:3]);eta=np.zeros(len(t))
            for k in range(1,len(t)):
                a=np.exp(-(t[k]-t[k-1])/tau);eta[k]=a*eta[k-1]+r1*(1-a)*i[k-1]
            return p[3]-r0*i-eta
        initial=np.array([.02,.01,10.,float(anchor.voltage_V)])
        fit=least_squares(lambda x:predict(x)-v,[*np.log(initial[:3]),initial[3]],
            bounds=([*np.log([.0001,.0001,.1]),initial[3]-.05],[*np.log([.2,.2,1000]),initial[3]+.05]),max_nfev=300)
        r0,r1,tau=np.exp(fit.x[:3]);nodes.append({'soc':s,'R0_ohm':float(r0),'R1_ohm':float(r1),'tau_s':float(tau),
            'fit_rmse_mV':float(np.sqrt(np.mean(fit.fun**2))*1000),'at_bound':bool(np.any(fit.active_mask)),'success':bool(fit.success),'cycle':int(cyc)})
    ocv.sort(key=lambda x:x['soc']);nodes.sort(key=lambda x:x['soc'])
    if len(nodes)<5 or not all(x['success'] for x in nodes):raise ValueError('Insufficient valid HPPC nodes')
    for values in (ocv,nodes):
        if np.any(np.diff([x['soc'] for x in values])<=0):raise ValueError('duplicate SOC nodes')
    return {'source':'HPPC only; EIS not used','capacity_Ah':capacity,'ocv_points':ocv,'rc_nodes':nodes,
        'soc_definition':'1 at end of HPPC 1h post-CCCV rest, Coulomb counting at measured C/20 capacity',
        'scope':'1RC pulses with 1h pre-rest; temperature 23C nominal, no thermal model; effective parameters',
        'outside_rc_grid':'hold nearest endpoint and count; no SOC extrapolation for OCV',
        'freeze':'written before reading dynamic source file'}


def replay_frozen(model,frame,initial_soc=1.,initial_eta_V=0.):
    """Replay a *preselected* rest-end -> predischarge -> drive segment."""
    frame=frame.drop_duplicates('time_s',keep='last').reset_index(drop=True)
    t=frame.time_s.to_numpy(dtype=float);t=t-t[0]
    if len(t)<2 or np.any(np.diff(t)<=0):raise ValueError('time must increase')
    current=-frame.current_A.to_numpy(dtype=float)
    soc=float(initial_soc)-cumulative_trapezoid(current,t,initial=0)/(3600*model['capacity_Ah'])
    o=model['ocv_points'];n=model['rc_nodes'];os=np.array([x['soc'] for x in o]);ns=np.array([x['soc'] for x in n])
    if soc.min()<os[0]-1e-5 or soc.max()>os[-1]+1e-5:raise ValueError('SOC outside measured OCV range')
    r0=np.interp(soc,ns,[x['R0_ohm'] for x in n]);r1=np.interp(soc,ns,[x['R1_ohm'] for x in n]);tau=np.interp(soc,ns,[x['tau_s'] for x in n]);eta=np.zeros(len(t));eta[0]=float(initial_eta_V)
    for k in range(1,len(t)):
        decay=np.exp(-(t[k]-t[k-1])/tau[k-1]);eta[k]=decay*eta[k-1]+r1[k-1]*(1-decay)*current[k-1]
    voltage=np.interp(soc,os,[x['voltage_V'] for x in o])-r0*current-eta
    return pd.DataFrame({'time_s':t,'step':frame.step.to_numpy(),'cycle':frame.cycle.to_numpy(),
       'current_discharge_A':current,'measured_V':frame.voltage_V.to_numpy(),'model_V':voltage,
       'residual_V':voltage-frame.voltage_V.to_numpy(),'soc_proxy':soc,'polarization_V':eta,
       'surface_C':frame.surface_C.to_numpy(),'rc_endpoint_hold':(soc<ns[0])|(soc>ns[-1])})


def time_metrics(trace):
    t=trace.time_s.to_numpy();e=trace.residual_V.to_numpy();duration=t[-1]-t[0]
    if duration<=0:raise ValueError('need positive scoring duration')
    mean=float(np.trapezoid(e,t)/duration);var=float(np.trapezoid((e-mean)**2,t)/duration)
    return {'duration_s':float(duration),'bias_mV':mean*1000,'centered_rmse_mV':1000*np.sqrt(var),
       'rmse_mV':1000*np.sqrt(float(np.trapezoid(e**2,t)/duration)),
       'mae_mV':1000*float(np.trapezoid(abs(e),t)/duration),'max_abs_mV':1000*float(max(abs(e))),
       'endpoint_hold_time_fraction':float(np.trapezoid(trace.rc_endpoint_hold.to_numpy(dtype=float),t)/duration)}

"""Comparable 1RC pulse/EIS estimators; not a CPE-to-RC converter."""
from __future__ import annotations
import numpy as np
from scipy.optimize import least_squares
from scipy.signal import lfilter

LOW=np.array([1e-5,1e-6,.25]);HIGH=np.array([.05,.05,600.])

def pulse_voltage(parameters,current):
    r0,r1,tau,v0=parameters
    a=np.exp(-1./tau);polarization=lfilter([r1*(1-a)],[1.,-a],current)
    return v0-r0*current-polarization

def eis_impedance(parameters,frequencies):
    r0,r1,tau=parameters[:3]
    return r0+r1/(1+2j*np.pi*frequencies*tau)

def fit_methods(pulse,eis,quality_pass,voltage_scale=.005,max_nfev=250):
    """Three starts each, fixed bounds; EIS is gated by caller's spectrum screen.

    Pulse current is average over each preceding 1 second interval, matching
    the existing CALB fitter. Each objective term has equal *group* weighting.
    """
    if not quality_pass:raise ValueError('EIS未通过指定质量筛查，不允许参与辨识。')
    i=np.asarray(pulse['current'],float);v=np.asarray(pulse['voltage'],float)
    f=np.asarray(eis['frequency_Hz'],float);z=np.asarray(eis['impedance'],complex)
    if len(i)!=len(v) or len(i)<10 or len(f)<12 or np.any(f<=0) or np.any(abs(z)==0):raise ValueError('脉冲或阻抗数据无效。')
    if not all(np.isfinite(x).all() for x in (i,v,f,z.real,z.imag)):raise ValueError('输入存在非有限数。')
    v0=float(pulse['pre_voltage']);lower=np.r_[np.log(LOW),v0-.05];upper=np.r_[np.log(HIGH),v0+.05]
    def ep(p):return (pulse_voltage([*np.exp(p[:3]),p[3]],i)-v)/(voltage_scale*np.sqrt(len(v)))
    def ez(p):
        delta=(eis_impedance(np.exp(p[:3]),f)-z)/abs(z)
        return np.r_[delta.real,delta.imag]/np.sqrt(len(z))
    def eonly(p):return ez(p)
    # EIS-only initialization uses identical bounds to the final RC model;
    # the time-scale bound expresses time-domain resolution, not physics proof.
    initials=[np.r_[np.log(x),v0] for x in ([.001,.0005,10.],[.002,.002,1.],[.0003,.0003,100.])]
    efits=[least_squares(eonly,x,bounds=(lower,upper),max_nfev=max_nfev) for x in initials]
    efit=min(efits,key=lambda x:np.sum(x.fun**2));eseed=efit.x.copy();eseed[3]=v0
    # Small, fixed deterministic multipliers preserve equal search budgets.
    def shifted(seed,factor):
        x=seed.copy();x[:3]=np.clip(x[:3]+np.log(factor),lower[:3]+1e-8,upper[:3]-1e-8);return x
    guesses={'hppc_only':initials,'eis_initial':[shifted(eseed,v) for v in (1.,.5,2.)]}
    fits={}
    for name,starts in guesses.items():
        results=[least_squares(ep,p,bounds=(lower,upper),max_nfev=max_nfev) for p in starts]
        fits[name]=results
    starts=[f.x for f in fits['hppc_only']]
    fits['joint']=[least_squares(lambda p:np.r_[ep(p)/np.sqrt(2),ez(p)/np.sqrt(2)],p,
                   bounds=(lower,upper),max_nfev=max_nfev) for p in starts]
    report={}
    for name,results in fits.items():
        best=min(results,key=lambda x:np.sum(x.fun**2));p=best.x;sv=np.linalg.svd(best.jac,compute_uv=False)
        report[name]={'R0_ohm':float(np.exp(p[0])),'R1_ohm':float(np.exp(p[1])),'tau_s':float(np.exp(p[2])),
            'pulse_baseline_V':float(p[3]),'pulse_rmse_mV':float(np.sqrt(np.mean((ep(p)*voltage_scale*np.sqrt(len(v)))**2))*1000),
            'eis_relative_rms':float(np.sqrt(np.mean(abs((eis_impedance(np.exp(p[:3]),f)-z)/abs(z))**2))),
            'fit_success':bool(best.success),'at_bound':bool(np.any(best.active_mask)),
            'jacobian_condition':float(sv[0]/sv[-1]) if len(sv) and sv[-1]>1e-12 else None,
            'starts':[{'success':bool(x.success),'cost':float(np.sum(x.fun**2)),
                       'parameters':[*np.exp(x.x[:3]).tolist(),float(x.x[3])],
                       'at_bound':bool(np.any(x.active_mask))} for x in results]}
    report['eis_initialization']={'R0_ohm':float(np.exp(eseed[0])),'R1_ohm':float(np.exp(eseed[1])),
        'tau_s':float(np.exp(eseed[2])),'at_bound':bool(np.any(efit.active_mask[:3])),
        'note':'time-domain tau bounds applied also to EIS initialization; lower bound is not a measured physical limit'}
    return report

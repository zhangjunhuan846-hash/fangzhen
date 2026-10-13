"""Scientific algebra never grants identifiability to a derived quantity."""
from __future__ import annotations
import math
import random
from user_tools.rg_workstation import solve_constraints


def diffusion_relation(radius_m=None, diffusivity_m2_s=None, tau_s=None, evidence="declared"):
    values={k:v for k,v in {'radius_m':radius_m,'diffusivity_m2_s':diffusivity_m2_s,'tau_s':tau_s}.items() if v is not None}
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0 for v in values.values()):
        return {'status':'conflict','issues':['R、D、tau 都须是有限正数'],'values':values,'evidence':evidence}
    trace=[]
    if len(values)==3:
        predicted=radius_m**2/diffusivity_m2_s
        if not math.isclose(predicted,tau_s,rel_tol=1e-6):
            return {'status':'conflict','issues':['tau=R²/D 与已知量矛盾'],'values':values,'evidence':evidence}
    elif len(values)==2:
        if radius_m is None: key,value='radius_m',math.sqrt(tau_s*diffusivity_m2_s)
        elif diffusivity_m2_s is None: key,value='diffusivity_m2_s',radius_m**2/tau_s
        else: key,value='tau_s',radius_m**2/diffusivity_m2_s
        values[key]=value;trace=[{'rule':'tau=R²/D','solved':key,'value':value}]
    return {'status':'solved' if len(values)==3 else 'partial','values':values,'trace':trace,
            'unknown':sorted({'radius_m','diffusivity_m2_s','tau_s'}-set(values)),
            'evidence':evidence,'parameter_verdict':'not_assessed',
            'note':'由已声明输入派生；没有新增实验信息，不能据此宣布Ds本征或可辨识。'}


def benchmark_cases(n=600,seed=412):
    rng=random.Random(seed);rows=[]
    for i in range(n):
        a=rng.uniform(.5,3);l=rng.uniform(1,8);w=rng.uniform(.75,.98);q=rng.uniform(250,360)
        capacity=a*l*w*q/1000
        kind=i%4
        if kind==0:
            known={'area_cm2':a,'total_loading_mg_cm2':l,'active_fraction':w,'q_ref_mAh_g':q};r=solve_constraints(known)
            passed=math.isclose(r['values']['capacity_mAh'],capacity,rel_tol=1e-9)
        elif kind==1:
            known={'area_cm2':a,'active_fraction':w,'q_ref_mAh_g':q,'capacity_mAh':capacity};r=solve_constraints(known)
            passed=math.isclose(r['values']['total_loading_mg_cm2'],l,rel_tol=1e-9)
        elif kind==2:
            known={'area_cm2':a,'total_loading_mg_cm2':l,'active_fraction':w,'q_ref_mAh_g':q,'capacity_mAh':capacity*1.3};r=solve_constraints(known)
            passed=r['status']=='conflict' and r['values']['capacity_mAh']==known['capacity_mAh']
        else:
            known={'capacity_mAh':capacity};r=solve_constraints(known)
            passed=r['status']=='partial' and 'total_loading_mg_cm2' not in r['values']
        rows.append({'case':i,'kind':['forward','reverse','conflict','underdetermined'][kind],'passed':bool(passed)})
    return {'evidence_type':'synthetic_design','seed':seed,'n':n,'passed':sum(r['passed'] for r in rows),'rows':rows}

"""Adapters over the existing PyBaMM kernel, PyBOP and L4 prediction path."""
from __future__ import annotations
import json
import math
import os
from contextlib import contextmanager
from pathlib import Path
import numpy as np


def clean(value):
    if isinstance(value,dict): return {str(k):clean(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)): return [clean(v) for v in value]
    if isinstance(value,np.ndarray): return clean(value.tolist())
    if isinstance(value,(np.integer,np.bool_)): return value.item()
    if isinstance(value,(np.floating,float)): return float(value) if math.isfinite(float(value)) else None
    if isinstance(value,Path): return str(value)
    if callable(value): return getattr(value,"__name__",str(value))
    return value


def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(clean(value),ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")


def workbook_data_path(value,base_dir):
    raw=str(value).strip()
    if os.name!='nt' and len(raw)>2 and raw[1]==':' and raw[2] in ('/','\\'):
        raw='/mnt/'+raw[0].lower()+'/'+raw[3:].replace('\\','/')
    path=Path(raw)
    return path if path.is_absolute() else Path(base_dir)/path


@contextmanager
def isolated_outputs(root):
    import battery_sim.paths as paths
    original=paths.PLATFORM_OUTPUT_ROOT
    paths.PLATFORM_OUTPUT_ROOT=Path(root)
    try: yield
    finally: paths.PLATFORM_OUTPUT_ROOT=original


def parameter_bundle(parameter_set,rows,base_dir):
    from battery_sim.models.pybamm_factory import load_parameter_values
    pv=load_parameter_values(parameter_set)
    values,sources={},{}
    for row in rows:
        key=str(row["key"])
        if key not in pv: raise KeyError(f"parameter not in set: {key}")
        if key in values: raise ValueError(f"duplicate parameter: {key}")
        mode=row.get("mode") or "scalar"
        if mode=="scalar":
            value=float(row["value"])
            if not math.isfinite(value): raise ValueError("finite scalar required")
        elif mode=="log_multiplier":
            amplitude=float(row["value"]);ref=pv[key]
            if not math.isfinite(amplitude): raise ValueError("finite multiplier required")
            if callable(ref):
                def value(*args,_ref=ref,_m=10**amplitude): return _m*_ref(*args)
                value.__name__=f"declared_multiplier_{amplitude:+.4f}"
            else: value=float(ref)*10**amplitude
        elif mode=="OCP_table":
            import pybamm
            path=workbook_data_path(row['source_path'],base_dir)
            data=np.genfromtxt(path,delimiter=",",names=True,encoding="utf-8")
            x=np.atleast_1d(np.asarray(data["stoichiometry"],float));y=np.atleast_1d(np.asarray(data["voltage_V"],float))
            if len(x)<3 or not np.isfinite(x).all() or not np.isfinite(y).all() or not (np.diff(x)>0).all() or x[0]<0 or x[-1]>1:
                raise ValueError("OCP requires finite sorted stoichiometry/voltage table within [0,1]")
            def value(sto,_x=x,_y=y): return pybamm.Interpolant(_x,_y,sto,extrapolate=False)
            value.__name__="declared_measured_ocp"
            value._rg_ocp_points=(x,y)
        else: raise ValueError(f"unsupported parameter mode {mode}")
        values[key]=value
        sources[key]={"source":row.get("source") or "Excel declared input","kind":row.get("kind") or "declared",
                      "parameter_id":row.get("parameter_id"),"mode":mode,"declared_value":row.get("value"),
                      "source_path":row.get("source_path"),"verdict":row.get("verdict") or "not_assessed"}
    return values,sources


def _rebase_ocp_initialisation(frame,overrides):
    """Half-cell initial state and forward solve consume the same declared OCP."""
    block=frame.attrs.get('initialisation') or {}
    if block.get('method')!='fixed_initial_concentration': return frame
    slot='positive' if 'positive' in block.get('concentration_parameter','') else 'negative'
    replacement=(overrides or {}).get(f'{slot.capitalize()} electrode OCP [V]')
    points=getattr(replacement,'_rg_ocp_points',None)
    if points is None: return frame
    x,y=points;v0=float(block['ocp_voltage_V'])
    if not ((np.diff(y)>=0).all() or (np.diff(y)<=0).all()):
        raise ValueError('OCP inverse is non-monotone; explicit branch/state mapping required')
    if not min(y)<=v0<=max(y): raise ValueError('rest OCV outside declared OCP table')
    if np.sum(np.isclose(y,v0,atol=1e-9,rtol=0))>1: raise ValueError('OCP plateau cannot uniquely determine x0')
    order=np.argsort(y);x0=float(np.interp(v0,y[order],x[order]))
    if not 0<x0<1: raise ValueError('initial state falls at an invalid OCP endpoint')
    copy=frame.copy();copy.attrs=dict(frame.attrs)
    copy.attrs['initialisation']={**block,'stoichiometry_from_ocp':x0,'mapping_reason':'inverse of the same declared OCP used by forward solver'}
    return copy


class _TaskAdapter:
    def __init__(self,adapter,overrides): self._adapter=adapter;self._overrides=overrides
    def __getattr__(self,name): return getattr(self._adapter,name)
    def load_processed_discharge(self,cell,rate):
        return _rebase_ocp_initialisation(self._adapter.load_processed_discharge(cell,rate),self._overrides)
    def load_processed_protocol(self,cell,protocol):
        return _rebase_ocp_initialisation(self._adapter.load_processed_protocol(cell,protocol),self._overrides)


def baseline_task(dataset,cell,rate,model,parameter_set,out,overrides=None,sources=None):
    from battery_sim.registry import get_dataset
    from battery_sim.simulation.baseline import run_baseline_cell
    adapter=get_dataset(dataset);ps=parameter_set or adapter.config.parameter_set
    adapter=_TaskAdapter(adapter,overrides)
    with isolated_outputs(Path(out)/"platform"):
        res=run_baseline_cell(adapter,model,str(cell),rate=rate,parameter_set=ps,
                             plot=False,quiet=True,parameter_overrides=overrides,parameter_override_sources=sources)
    row=clean(res["metrics"].iloc[0].to_dict())
    result={"evidence_type":"public_replay","dataset":dataset,"cell":str(cell),"rate":rate,
            "model":model,"parameter_set":ps,"metrics":row,
            "applied":clean(res.get("parameter_overrides_applied") or []),"output_dir":str(res["output_dir"]),
            "capacity_is_predictive":False,"scope":"voltage replay against measured data, not independent material validation"}
    save(Path(out)/"result.json",result)
    return result


def fit_measured(dataset,cell,rate,model,out,*,parameter_set=None,key="Positive particle diffusivity [m2.s-1]",
                 mode="scalar",bounds=(-15.3,-13.0),initial=None,fixed=None,sources=None,sigma_mV=1.0,
                 coverage_min=.98,limit_dex=.30,maxiter=90,profile_n=21):
    from battery_sim.registry import get_dataset
    from battery_sim.models.pybamm_factory import load_parameter_values,resolve_model_options
    from battery_sim.simulation.baseline import _run_one_replay,_filter_and_downsample
    from governance.dataset_roles import assert_calibration_allowed
    from governance.analysis_mode import classify_band
    from identification.recovery_stats import band_width
    import pybop
    assert_calibration_allowed(dataset,rate,what="v0.2 actual measured fitting")
    if sigma_mV<=0 or profile_n<3: raise ValueError("positive declared sigma and profile_n>=3 required")
    adapter=get_dataset(dataset);ps=parameter_set or adapter.config.parameter_set
    frame=_rebase_ocp_initialisation(adapter.load_processed_discharge(str(cell),rate),fixed)
    t,_,v=_filter_and_downsample(frame["time_s"].to_numpy(float),frame["current_A"].to_numpy(float),frame["voltage_V"].to_numpy(float))
    if not 0<coverage_min<=1: raise ValueError('fixed comparison fraction must be in (0,1]')
    raw_observation_end=float(t[-1])
    comparison_end=float(t[0]+coverage_min*(t[-1]-t[0]))
    window=t<=comparison_end
    t,v=t[window],v[window]
    if len(t)<5: raise ValueError('fixed observed comparison window is too short')
    pv=load_parameter_values(ps);ref=pv[key]
    if mode not in ("scalar","log_multiplier"): raise ValueError("only scalar/log-multiplier inverse supported")
    if mode=="scalar" and callable(ref): raise ValueError("curve diffusivity must use log_multiplier, not an invented scalar")
    initial=float(initial if initial is not None else (math.log10(float(ref)) if mode=="scalar" else 0.0))
    if not bounds[0]<=initial<=bounds[1]: raise ValueError("initial value outside declared bounds")
    options=resolve_model_options(adapter);fixed=dict(fixed or {});sources=dict(sources or {})
    if key in fixed: raise ValueError("optimized parameter cannot also be fixed")
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    audit=[];cache={}
    def evaluate(z):
        z=float(z);cachekey=round(z,9)
        if cachekey in cache: return cache[cachekey]
        if mode=="scalar": candidate=10**z
        elif callable(ref):
            def candidate(*args,_r=ref,_m=10**z): return _m*_r(*args)
            candidate.__name__=f"fit_multiplier_{z:+.4f}"
        else: candidate=float(ref)*10**z
        entry={"z":z,"dataset":dataset,"cell":str(cell),"rate":rate,"parameter_key":key,
               "mode":mode,"source":"public measured voltage residual"}
        try:
            res=_run_one_replay(frame,model,ps,options,{**fixed,key:candidate},
                               {**sources,key:{"source":"PyBOP candidate","z":z,"mode":mode}})
            ts=np.asarray(res["_t_common"],float);vs=np.asarray(res["_V_sim_common"],float)
            valid=(t>=ts[0]-1e-9)&(t<=ts[-1]+1e-9)
            coverage=float(res['coverage_fraction'])
            if not valid.all():
                values=np.full(len(t),np.nan)
                cost=float("inf")
            else:
                values=np.interp(t,ts,vs)
                cost=float(np.sum((values-v)**2))
            entry.update({"coverage":coverage,"sse_V2":cost,"applied":res.get("_applied_overrides") or [],
                          "comparison_window_fully_covered":bool(valid.all()),
                          "rmse_mV":float(np.sqrt(cost/len(v))*1000) if np.isfinite(cost) else None})
        except Exception as exc:
            values=np.full(len(t),np.nan);cost=float("inf")
            entry.update({"coverage":0.0,"sse_V2":cost,"error":f"{type(exc).__name__}: {exc}"})
        audit.append(clean(entry));cache[cachekey]=(values,cost,entry)
        return cache[cachekey]
    parameters=pybop.Parameters({"z":pybop.Parameter(initial_value=initial,bounds=list(bounds))})
    class Simulator(pybop.BaseSimulator):
        def __init__(self): super().__init__(parameters=parameters)
        def solve(self,inputs=None,calculate_sensitivities=False):
            voltage,_,_=evaluate(inputs["z"])
            sol=pybop.Solution(inputs=inputs);sol.set_solution_variable("Voltage [V]",data=voltage);return sol
        def solve_batch(self,inputs=None,calculate_sensitivities=False):
            return [self.solve(x,calculate_sensitivities) for x in inputs]
        @property
        def has_sensitivities(self): return False
    dataset_object=pybop.Dataset({"Time [s]":t,"Voltage [V]":v},domain="Time [s]")
    cost=pybop.SumSquaredError(dataset=dataset_object,target="Voltage [V]")
    problem=pybop.Problem(simulator=Simulator(),cost=cost)
    optimizer=pybop.SciPyMinimize(problem,options=pybop.SciPyMinimizeOptions(method="Nelder-Mead",maxiter=int(maxiter)))
    fitted=optimizer.run()
    zfit=float(np.atleast_1d(np.asarray(fitted.x,float))[0]);vf,sse,last=evaluate(zfit)
    if not np.isfinite(sse):
        save(out/"audit.json",audit)
        raise RuntimeError("fit has no full-coverage finite solution")
    grid=np.unique(np.r_[np.linspace(max(bounds[0],zfit-.5),min(bounds[1],zfit+.5),profile_n),zfit])
    costs=np.array([evaluate(z)[1] for z in grid])
    j_min=float(np.min(costs[np.isfinite(costs)]))
    z_hat=float(grid[np.argmin(costs)])
    delta=(costs-j_min)/(sigma_mV/1000)**2
    # Non-finite holes cannot be silently bridged into a narrow confidence band.
    complete=bool(np.isfinite(costs).all())
    center=int(np.argmin(costs));left=right=center
    while left>0 and np.isfinite(costs[left-1]): left-=1
    while right<len(costs)-1 and np.isfinite(costs[right+1]): right+=1
    band=band_width(grid[left:right+1],delta[left:right+1],z_hat,3.841458820694124) if right>left else None
    verdict=classify_band(band,level_mV=sigma_mV,limit_dex=limit_dex,scan_range_dex=float(grid[-1]-grid[0]))
    rmse=float(np.sqrt(sse/len(v))*1000)
    result={"evidence_type":"public_identification","dataset":dataset,"cell":str(cell),"fit_rate":rate,
            "model":model,"parameter_set":ps,"parameter_key":key,"parameter_mode":mode,
            "fit_z":zfit,"fit_value":10**zfit if mode=="scalar" else None,
            "fit_multiplier":10**zfit if mode=="log_multiplier" else None,
            "effective_candidate_only":True,"parameter_verdict":verdict["verdict"],
            "band":clean(band),"profile_grid":grid.tolist(),"profile_delta_chi2":clean(delta),
            "profile_complete":complete,"profile_definition":"measured-data SSE likelihood increment; declared IID sigma, all other parameters fixed",
            "profile_confidence":.95,"delta_chi2_threshold":3.841458820694124,
            "profile_band_kind":"conditional local 95% likelihood band; no bridging unreachable points",
            "comparison_window_end_s":float(t[-1]),"raw_observation_end_s":raw_observation_end,
            "predeclared_comparison_fraction":coverage_min,"all_candidates_use_same_comparison_points":True,
            "declared_sigma_mV":sigma_mV,"rmse_mV":rmse,"coverage":last["coverage"],
            "model_consistency_pass":bool(rmse<=3*sigma_mV),
            "consistency_rule":"engineering diagnostic: fit RMS <= 3 * declared sigma; not proof of correct model form",
            "optimizer_message":str(getattr(fitted,"message","")),
            "fixed_overrides":clean(fixed),"applied":clean(last.get("applied",[])),
            "conditional_uncertainty_only":True,
            "scope":"effective parameter under frozen nuisance values; Chen positive key concerns positive material, not intrinsic graphite Ds"}
    save(out/"result.json",result);save(out/"audit.json",audit)
    np.savetxt(out/"profile.csv",np.c_[grid,costs,delta],delimiter=",",header="z,sse_V2,delta_chi2",comments="")
    np.savetxt(out/"fit_curve.csv",np.c_[t,v,vf],delimiter=",",header="time_s,voltage_exp_V,voltage_sim_V",comments="")
    return result


def holdout_rate_guard(adapter,fit_rate,target_rate):
    if adapter.rate_info(fit_rate)['rate_slug']==adapter.rate_info(target_rate)['rate_slug']:
        raise ValueError('canonical training rate cannot be reused as a holdout under another alias')


def heldout_prediction(fit,dataset,cell,rate,out,*,overrides=None,sources=None,coverage_min=.98,voltage_limit_mV=20):
    if dataset!=fit["dataset"] or str(cell)!=fit["cell"]:
        raise ValueError("different dataset/cell is a cross-material/cell exploration, not this protocol holdout")
    if rate==fit["fit_rate"]: raise ValueError("training rate cannot be a holdout")
    from battery_sim.registry import get_dataset
    holdout_rate_guard(get_dataset(dataset),fit['fit_rate'],rate)
    from identification.rate_prediction import rate_prediction,OverrideBundle
    from battery_sim.models.pybamm_factory import load_parameter_values
    import yaml
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    # Rate-local roles accompany the task without changing global registry declarations.
    roles={dataset:{"dataset_role":"identification","rates_meta":{
        fit["fit_rate"]:{"dataset_role":"identification"},rate:{"dataset_role":"validation"}}}}
    role_path=out/"task_local_roles.yaml"
    role_path.write_text(yaml.safe_dump(roles,allow_unicode=True),encoding="utf-8")
    key=fit["parameter_key"];values=dict(overrides or {})
    if fit["parameter_mode"]=="scalar": value=fit["fit_value"]
    else:
        ref=load_parameter_values(fit["parameter_set"])[key];m=fit["fit_multiplier"]
        if callable(ref):
            def value(*args,_r=ref,_m=m): return _m*_r(*args)
            value.__name__="frozen_fit_multiplier"
        else: value=float(ref)*m
    values[key]=value
    src={**dict(sources or {}),key:{"source":"frozen measured fit","fit_rate":fit["fit_rate"]}}
    bundle=OverrideBundle(overrides=values,sources=src,provenance="public measured fit; no target refitting")
    adapter=_TaskAdapter(get_dataset(dataset),values)
    with isolated_outputs(out/"platform"):
        record=rate_prediction(fit_adapter=adapter,target_adapter=adapter,cell=str(cell),
                               fit_rate=fit["fit_rate"],target_rate=rate,model_name=fit["model"],
                               parameter_set=fit["parameter_set"],bundle=bundle,
                               fit_dataset=dataset,target_dataset=dataset,roles_config=role_path,
                               coverage_min=coverage_min,alignment="check")
    metric=record["target"]["metrics"];rmse=float(metric["rmse_time_aligned_mV"])
    coverage=float(metric["coverage_fraction"])
    failures=record.get("failures") or []
    result={"evidence_type":"public_protocol_holdout","dataset":dataset,"cell":str(cell),
            "fit_rate":fit["fit_rate"],"target_rate":rate,"model":fit["model"],"parameter_set":fit["parameter_set"],
            "rmse_mV":rmse,"coverage":coverage,"holdout_pass":bool(not failures and coverage>=coverage_min and rmse<=voltage_limit_mV),
            "engineering_limit_mV":voltage_limit_mV,"failures":failures,"parameter_frozen":True,
            "scale":clean(record.get('scale')),
            "applied":clean(record["target"].get("applied_overrides")),
            "scope":"same-cell unused protocol; not independent material validation; capacity remains forced-window",
            "capacity_is_predictive":False}
    save(out/"result.json",result);save(out/"l4_record.json",record)
    return result


def forward_protocol(out,*,parameter_set="Chen2020",model="SPM",c_rate=1,initial_soc=.9,temperature_C=25,
                     duration_limit_s=20000,overrides=None,sources=None,working_electrode=None,halfcell_x0=None):
    """Autonomous predefined-current solve to voltage event, with no target trace."""
    import pybamm
    from battery_sim.models.pybamm_factory import build_model,load_parameter_values
    if c_rate<=0 or duration_limit_s<=0: raise ValueError("positive C-rate and horizon required")
    if 'halfcell' in parameter_set.lower() and working_electrode is None:
        raise ValueError('half-cell parameter set requires an explicit working-electrode slot and x0')
    pv=load_parameter_values(parameter_set);overrides=dict(overrides or {});applied=[]
    for key,value in overrides.items():
        if key not in pv: raise KeyError(key)
        applied.append({'key':key,'old':clean(pv[key]),'new':clean(value),'source':(sources or {}).get(key)})
        pv[key]=value
    for key in ('Ambient temperature [K]','Initial temperature [K]'):
        applied.append({'key':key,'old':clean(pv[key]),'new':float(temperature_C)+273.15,'source':'declared ForwardProtocol temperature'})
        pv[key]=float(temperature_C)+273.15
    options={"working electrode":working_electrode} if working_electrode else None
    built=build_model(model,options)
    if working_electrode:
        if halfcell_x0 is None or not 0<float(halfcell_x0)<1:
            raise ValueError("half-cell requires explicit x0 from the same OCP mapping")
        pv[f"Initial concentration in {working_electrode} electrode [mol.m-3]"]=float(halfcell_x0)*float(pv[f"Maximum concentration in {working_electrode} electrode [mol.m-3]"])
    nominal=float(pv["Nominal cell capacity [A.h]"])
    current=nominal*float(c_rate);pv["Current function [A]"]=current
    sim=pybamm.Simulation(built,parameter_values=pv)
    kwargs={} if working_electrode else {"initial_soc":float(initial_soc)}
    solution=sim.solve(np.linspace(0,float(duration_limit_s),300),**kwargs)
    t=np.asarray(solution["Time [s]"].entries,float).ravel()
    v=np.asarray(solution["Voltage [V]"].entries,float).ravel()
    q=np.asarray(solution["Discharge capacity [A.h]"].entries,float).ravel()
    terminated=str(solution.termination)
    reached_cutoff="voltage" in terminated.lower() and "event" in terminated.lower()
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    np.savetxt(out/"forward_curve.csv",np.c_[t,v,q],delimiter=",",header="time_s,voltage_sim_V,capacity_sim_Ah",comments="")
    result={"evidence_type":"model_only_forward","parameter_set":parameter_set,"model":model,"c_rate":c_rate,
            "current_A":current,"initial_soc":initial_soc if not working_electrode else None,"halfcell_x0":halfcell_x0,
            "temperature_C":temperature_C,"termination":terminated,"reached_cutoff":reached_cutoff,
            "capacity_is_predictive":True,"predicted_capacity_Ah":float(q[-1]-q[0]) if reached_cutoff else None,
            "partial_horizon_charge_Ah":float(q[-1]-q[0]),"target_measurements_read":False,
            "parameter_overrides":clean(overrides),"sources":sources or {},
            "parameter_overrides_applied":applied,
            "scope":"model-only forward estimate; no validation of an unseen recycled material"}
    save(out/"result.json",result)
    return result


def protocol_probe(dataset,cell,protocol_id,out,*,grid_n=21):
    from battery_sim.registry import get_dataset
    from battery_sim.models.pybamm_factory import resolve_model_options
    from governance.scale_alignment import alignment_overrides
    from identification.replay_scan import MultiplierScan
    from identification.recovery_stats import band_width
    from governance.analysis_mode import classify_band
    adapter=get_dataset(dataset);ps=adapter.config.parameter_set
    alignment=alignment_overrides(adapter,protocol_id,cell=str(cell))
    df=adapter.load_processed_protocol(str(cell),protocol_id)
    protocol=adapter.load_protocol(protocol_id)
    scan=MultiplierScan(adapter,str(cell),protocol_id,df,protocol,ps,resolve_model_options(adapter),alignment)
    grid=np.linspace(-1,1,int(grid_n));rows=[]
    for a in grid:
        rec=scan.evaluate(float(a))
        value=scan.cost(float(a),0) if scan.reachable(rec) else float("inf")
        rows.append({"a_dex":float(a),"model_cost_mV2":value,"coverage":rec["coverage_fraction"],
                     "rmse_vs_measured_mV":rec["rmse_vs_measured_mV"]})
    costs=np.array([r["model_cost_mV2"] for r in rows])
    band=band_width(grid,costs,0,1.0) if np.isfinite(costs).all() else None
    verdict=classify_band(band,level_mV=1,limit_dex=.30,scan_range_dex=2)
    result={"evidence_type":"model_to_model_ideal","dataset":dataset,"cell":str(cell),"protocol_id":protocol_id,
            "parameter_set":ps,"parameter_verdict":verdict["verdict"],"band":clean(band),
            "n_unreachable":int((~np.isfinite(costs)).sum()),"n_simulations":scan.n_sim,
            "minimum_coverage":min(r["coverage"] for r in rows),"alignment":clean(alignment),
            "rows":clean(rows),"scope":"real recorded excitation, ideal model-to-model identifiability; not measured parameter recovery"}
    save(Path(out)/"result.json",result)
    return result


def synthetic_recovery(out):
    from identification.synthetic import generate
    from identification.recovery import recover_from
    out=Path(out);observation=generate("chen2020","02","C2",2e-15,out/"truth")
    fit=recover_from(observation,out/"inverse",out/"audit",z_init=math.log10(4e-15),maxiter=90)
    result={"evidence_type":"synthetic_recovery","ds_true":2e-15,"ds_fit":fit.ds_fit,"relative_error":fit.rel_error,
            "passed":bool(fit.rel_error<.05),"evaluations":fit.n_evaluations,
            "scope":"same-model synthetic recovery/inverse crime, software integration only"}
    save(out/"result.json",result)
    return result

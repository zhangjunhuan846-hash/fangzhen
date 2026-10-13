"""Workbook task orchestration; results are saved separately from inputs."""
from __future__ import annotations
import argparse
import csv
import json
import math
import time
from datetime import datetime,timezone,timedelta
from pathlib import Path
from user_tools.rg_workstation import read_xlsx,column,load_records,normalize_and_validate,design_from_cells
from . import VERSION
from .physics import clean,save

TABLES={
"仿真任务":[
("task_id","任务编号"),("enabled","启用"),("action","任务类型"),("dataset","数据集"),
("cell","电芯编号"),("model","模型"),("parameter_set","参数集"),("rate","倍率 / 协议编号"),
("parent_task","冻结参数来源任务"),("sigma_mV","声明噪声 (mV)"),("z_min","辨识下界 (log10)"),("z_max","辨识上界 (log10)"),
("coverage_min","最低覆盖率"),("voltage_limit_mV","留出电压误差阈值 (mV)"),("c_rate","前向倍率 (C)"),
("initial_soc","前向初始 SOC"),("temperature_C","前向温度 (°C)"),("notes","用途与限制"),
("working_electrode","半电池工作电极槽位"),("halfcell_x0","半电池初始 x0")],
"科学参数":[
("parameter_id","参数编号"),("task_id","任务编号"),("key","PyBaMM 参数名"),("mode","取值方式"),
("value","数值 / log10 倍数"),("kind","科学类别"),("verdict","辨识判定"),("source","来源"),
("source_path","OCP 曲线路径"),("role","输入角色"),("notes","备注")]
}
ACTIONS=("baseline","identify","predict","protocol_probe","forward","synthetic_recovery")


def task_records(workbook):
    grids=read_xlsx(workbook);rows={}
    for sheet,fields in TABLES.items():
        if sheet not in grids: raise ValueError(f"missing v0.2 sheet: {sheet}")
        grid=grids[sheet]
        for i,(_,label) in enumerate(fields,1):
            if grid.get(f"{column(i)}6")!=label: raise ValueError(f"{sheet} column mismatch: {label}")
        selected=[]
        for row in range(7,207):
            rec={key:grid.get(f"{column(i)}{row}") for i,(key,_) in enumerate(fields,1)}
            if any(v not in (None,"") for v in rec.values()):
                if any(isinstance(v,dict) for v in rec.values()): raise ValueError(f"{sheet} input formula not allowed")
                rec={k:(v.strip() if isinstance(v,str) else v) for k,v in rec.items()}
                rec["_row"]=row;selected.append(rec)
        rows[sheet]=selected
    tasks=rows["仿真任务"];params=rows["科学参数"]
    ids=[t["task_id"] for t in tasks]
    pids=[r["parameter_id"] for r in params]
    if any(not isinstance(v,str) or not v for v in ids) or len(ids)!=len(set(ids)): raise ValueError("task IDs missing/duplicated")
    if any(not isinstance(v,str) or not v for v in pids) or len(pids)!=len(set(pids)): raise ValueError("parameter IDs missing/duplicated")
    for t in tasks:
        if t["enabled"] not in ("是","否"): raise ValueError("task enable field must be 是/否")
        if t["action"] not in ACTIONS: raise ValueError("unknown task action")
        if t["parent_task"] and t["parent_task"] not in ids: raise ValueError("parent task missing")
    for p in params:
        if p["task_id"] not in ids: raise ValueError("parameter refers to missing task")
        if p["role"] not in ("fixed","free","target","bounded"): raise ValueError("parameter role required")
        if p["mode"] not in ("scalar","log_multiplier","OCP_table"): raise ValueError("unknown parameter mode")
        if not p["key"] or not p["source"]: raise ValueError("parameter key and source required")
    return grids,tasks,params


def _num(task,key,default):
    value=task.get(key)
    return default if value in (None,"") else float(value)


def run_workbook(workbook,out,*,process_benchmark=True,seeds=None,budget=None):
    from .physics import parameter_bundle,baseline_task,fit_measured,heldout_prediction,forward_protocol,protocol_probe,synthetic_recovery
    from .optimization import benchmark
    from .constraints import benchmark_cases
    from .credibility import gate_ablation
    workbook=Path(workbook).resolve();grids,tasks,params=task_records(workbook)
    setup=grids.get('优化设置',{})
    if setup.get('B5')=='否': process_benchmark=False
    if setup.get('B6') not in (None,'synthetic_process'):
        raise ValueError('v0.2 benchmark requires synthetic_process; actual-material campaign must be separately calibrated')
    setting=lambda key,default: default if setup.get(key) in (None,'') else setup[key]
    seed_count=int(setting('B8',5))
    seeds=range(seed_count) if seeds is None else seeds
    seeds=list(seeds)
    batches=tuple(str(setting('B7','A,B')).split(','))
    batches=tuple(b.strip() for b in batches if b.strip())
    if not batches or len(batches)!=len(set(batches)) or any(b not in ('A','B') for b in batches):
        raise ValueError('synthetic batch selection supports A and/or B')
    budget=int(setting('B10',18)) if budget is None else budget
    initial_n=int(setting('B9',5));grid_n=int(setting('B11',11))
    thresholds={'ice':float(setting('B12',.88)),'yield':float(setting('B13',.84))}
    noise_std=[float(setting('B14',2.5)),float(setting('B15',.005)),float(setting('B16',.005))]
    if not 1<=seed_count<=30 or not 1<=len(seeds)<=30 or not 3<=initial_n<=budget or not 3<=grid_n<=40:
        raise ValueError('invalid simulation budget / seed / grid settings')
    if not all(math.isfinite(v) and 0<=v<=1 for v in thresholds.values()) or not all(math.isfinite(v) and v>0 for v in noise_std):
        raise ValueError('invalid process constraints/noise')
    source_records,issues=load_records(grids)
    source_records,more=normalize_and_validate(source_records);issues.extend(more)
    if any(i["severity"]=="error" for i in issues):
        raise ValueError("source records have errors; run workstation check first")
    out=Path(out).resolve()
    session=out/datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d_%H%M%S_%f")
    session.mkdir(parents=True,exist_ok=False)
    save(session/"input_records.json",source_records)
    save(session/"tasks.json",tasks);save(session/"scientific_parameters.json",params)
    save(session/'process_settings.json',{'batches':batches,'seeds':seeds,'budget':budget,'initial_n':initial_n,'grid_n':grid_n,'thresholds':thresholds,'noise_std':noise_std})
    (session/"input_snapshot.xlsx").write_bytes(workbook.read_bytes())
    save(session/"design_result.json",design_from_cells(grids,source_records))
    results=[];by_id={}
    # Strict topological order: enabled parent must already have completed.
    for task in tasks:
        if task["enabled"]!="是": continue
        tid=task["task_id"]
        if not isinstance(tid,str) or any(ch in tid for ch in "/\\:"):
            raise ValueError("task ID must be a plain filename-safe text identifier")
        action=task["action"];target=session/"physics"/tid
        print(f"TASK {tid}: {action}",flush=True);started=time.perf_counter()
        selected=[p for p in params if p["task_id"]==tid]
        result={"task_id":tid,"action":action,"status":"FAILED"}
        try:
            ps=task.get("parameter_set")
            if not ps and task.get("dataset"):
                from battery_sim.registry import get_dataset
                ps=get_dataset(task["dataset"]).config.parameter_set
            fixed=[r for r in selected if r["role"]=="fixed"]
            if action in ('baseline','forward') and len(fixed)!=len(selected):
                raise ValueError('baseline/forward only consume fixed inputs; free/target/bounded rows need a solve/identify task')
            if action=='identify' and any(r['role']=='target' for r in selected):
                raise ValueError('identify targets are measured voltage; target-role parameter rows are unsupported')
            values,sources=parameter_bundle(ps,fixed,workbook.parent) if fixed else ({},{})
            base=dict(dataset=task.get("dataset"),cell=str(task.get("cell") or ""),
                      model=task.get("model") or "SPM",parameter_set=ps)
            if action=="baseline":
                data=baseline_task(**base,rate=task["rate"],out=target,overrides=values,sources=sources)
            elif action=="identify":
                free=[r for r in selected if r["role"] in ("free","bounded")]
                if len(free)!=1: raise ValueError("v0.2 measured inverse requires one explicitly free parameter")
                p=free[0]
                bounds=(_num(task,"z_min",-15.3),_num(task,"z_max",-13))
                data=fit_measured(**base,rate=task["rate"],out=target,key=p["key"],mode=p["mode"],
                                  bounds=bounds,initial=(math.log10(float(p['value'])) if p['mode']=='scalar' else float(p['value'])) if p.get('value') is not None else None,
                                  fixed=values,sources=sources,sigma_mV=_num(task,"sigma_mV",1),
                                  coverage_min=_num(task,"coverage_min",.98))
            elif action=="predict":
                parent=by_id.get(task.get("parent_task"))
                if not parent or parent.get("status")!="COMPLETED" or parent["action"]!="identify":
                    raise ValueError("prediction needs a completed identify parent")
                # Additions cannot quietly change frozen calibration parameters.
                if selected: raise ValueError("prediction must use the frozen parent bundle; new parameter rows not allowed")
                if base['model']!=parent['data']['model'] or (ps and ps!=parent['data']['parameter_set']):
                    raise ValueError('holdout model/parameter set must equal the frozen identification parent')
                parent_task=next(t for t in tasks if t["task_id"]==task["parent_task"])
                rows_fixed=[p for p in params if p["task_id"]==parent_task["task_id"] and p["role"]=="fixed"]
                frozen,frozen_sources=parameter_bundle(parent["data"]["parameter_set"],rows_fixed,workbook.parent) if rows_fixed else ({},{})
                data=heldout_prediction(parent["data"],base["dataset"],base["cell"],task["rate"],target,
                                        overrides=frozen,sources=frozen_sources,
                                        coverage_min=_num(task,"coverage_min",.98),
                                        voltage_limit_mV=_num(task,"voltage_limit_mV",20))
            elif action=="protocol_probe":
                if selected: raise ValueError("protocol probe uses the frozen reference parameterization")
                data=protocol_probe(base["dataset"],base["cell"],task["rate"],target)
            elif action=="forward":
                data=forward_protocol(target,parameter_set=ps or "Chen2020",model=base["model"],
                                      c_rate=_num(task,"c_rate",1),initial_soc=_num(task,"initial_soc",.9),
                                      temperature_C=_num(task,"temperature_C",25),overrides=values,sources=sources,
                                      working_electrode=task.get('working_electrode') or None,
                                      halfcell_x0=_num(task,'halfcell_x0',None))
            elif action=="synthetic_recovery":
                if selected: raise ValueError("synthetic recovery uses its declared benchmark fixture")
                data=synthetic_recovery(target)
            result.update({"status":"COMPLETED","data":data})
        except Exception as exc:
            result["error"]=f"{type(exc).__name__}: {exc}"
            print(f"TASK FAILURE {tid}: {result['error']}",flush=True)
        result["runtime_s"]=time.perf_counter()-started
        results.append(result);by_id[tid]=result
        save(session/"task_results.json",results)
    constraints=benchmark_cases();save(session/"constraint_benchmark.json",constraints)
    gate=gate_ablation();save(session/"credibility_ablation.json",gate)
    probes=[r["data"] for r in results if r.get("action")=="protocol_probe" and r.get("status")=="COMPLETED"]
    from .credibility import physical_decision
    decisions=[]
    for result in results:
        if result.get('action')!='identify' or result.get('status')!='COMPLETED': continue
        fit=result['data'];children=[r['data'] for r in results if r.get('action')=='predict' and r.get('status')=='COMPLETED' and r['data']['fit_rate']==fit['fit_rate'] and r['data']['dataset']==fit['dataset'] and r['data']['cell']==fit['cell']]
        evidence={'evidence_type':fit['evidence_type'],'parameter_verdict':fit['parameter_verdict'],
                  'scale_aligned':bool(children and all(c.get('scale',{}).get('verdict')=='aligned' for c in children)),
                  'geometry_measured':False,'holdout_pass':bool(children and all(c['holdout_pass'] for c in children)),
                  'model_consistency_pass':fit['model_consistency_pass']}
        decisions.append({'task_id':result['task_id'],'evidence':evidence,'decision':physical_decision(evidence),
                          'geometry_note':'public parameter-set defaults are not independent measurements for a new recycled material'})
    save(session/'model_decisions.json',decisions)
    ranked=sorted([p for p in probes if p.get("band")],key=lambda p:p["band"]["width_dex"])
    save(session/"active_protocol_recommendation.json",{
        "evidence_type":"model_to_model_ideal","candidate_protocols":[p["protocol_id"] for p in ranked],
        "recommended":ranked[0]["protocol_id"] if ranked and ranked[0]['parameter_verdict']=='identifiable' else None,
        "reason":"smallest declared 1mV model-to-model band among complete candidate scans",
        "scope":"restricted ideal-model candidates only; not optimum on real material"})
    process=benchmark(session/"process",seeds=seeds,batches=batches,budget=budget,initial_n=initial_n,grid_n=grid_n,thresholds=thresholds,noise_std=noise_std) if process_benchmark else {"rows":[],"not_run":True}
    save(session/"process_benchmark.json",process)
    summary={"version":VERSION,"input_workbook":str(workbook),"session":str(session),
             "task_results":results,"constraint_benchmark":{"n":constraints["n"],"passed":constraints["passed"]},
             "credibility_ablation":gate,"process_benchmark":process,
             "model_decisions":decisions,
             "scientific_scope":"public and synthetic validation; no real recycled-graphite material verification"}
    save(session/"summary.json",summary)
    print(f"SESSION {session}",flush=True)
    return summary


def main(argv=None):
    ap=argparse.ArgumentParser(description="fangzhen v0.2 public/synthetic simulation loop")
    ap.add_argument("--workbook",required=True);ap.add_argument("--out",required=True)
    ap.add_argument("--skip-process",action="store_true")
    ap.add_argument("--seeds",type=int);ap.add_argument("--budget",type=int)
    args=ap.parse_args(argv)
    result=run_workbook(args.workbook,args.out,process_benchmark=not args.skip_process,
                        seeds=range(args.seeds) if args.seeds is not None else None,budget=args.budget)
    return int(any(r["status"]!="COMPLETED" for r in result["task_results"]))


if __name__=="__main__":
    raise SystemExit(main())

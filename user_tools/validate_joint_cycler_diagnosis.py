"""Reproducible pilot. Run python -m user_tools.validate_joint_cycler_diagnosis."""
import csv
import hashlib
import json
import math
import random
import statistics
from pathlib import Path
from user_tools.workbench.joint_cycler_diagnosis import diagnose
from user_tools.workbench.preprocess import normalize_csv

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/analysis/joint_cycler_diagnosis_20261016'
SCENARIOS=('clean','milliseconds','minutes','sign_flip','milliseconds_sign_flip',
           'step_reset','combined_reset','missing_evidence','clock_charge_conflict','time_rollback')

def synthetic(seed,scenario):
    """Analytic piecewise constant charge; no estimator imports in the generator."""
    rng=random.Random(seed);rows=[];t=0.;qc=qd=0.;current=1.
    factor=.001 if scenario in ('milliseconds','milliseconds_sign_flip','combined_reset') else 60. if scenario=='minutes' else 1.
    sign=-1 if scenario in ('sign_flip','milliseconds_sign_flip','combined_reset') else 1
    reset=scenario in ('step_reset','combined_reset')
    for k in range(240):
        dt=rng.uniform(.6,2.4) if k else 0.
        t+=dt;step=k//40;direction=1 if step%2==0 else -1
        if k%40==0:
            current=direction*rng.uniform(.2,2.)
            if reset:qc=qd=0.
        else:
            # Exact integral away from a protocol boundary, independent of solver.
            qc+=max(current,0)*dt/3600.;qd+=max(-current,0)*dt/3600.
        rows.append(dict(t=t/factor,i=sign*current*(1+rng.gauss(0,.002)),
            qc=round(qc,8),qd=round(qd,8),stamp=t+rng.uniform(-.001,.001),
            step=step,direction=direction))
    if scenario=='missing_evidence':
        for r in rows:r.update(qc=None,qd=None,stamp=None,direction=None)
    if scenario=='clock_charge_conflict':
        for r in rows:r['stamp']*=2
    if scenario=='time_rollback':
        shift=rows[119]['t']+100
        for r in rows[120:]:r['t']-=shift
    return rows,dict(time_factor=factor,current_sign=sign,
        identifiable=scenario not in ('missing_evidence','clock_charge_conflict','time_rollback'),
        reset=reset,seed=seed,scenario=scenario)

def public_records(path):
    text=path.read_text(encoding='utf-8-sig');lines=text.splitlines()
    if 'Program Duration#s' in lines[0]:
        schema=dict(t='Program Duration#s',i='Current#A',qc='AhCha#AH',qd='AhDch#Ah',stamp='Timestamp',step='Step',cycle='Cycle',status='Status')
    elif 'Total Time(s)' in lines[0]:
        schema=dict(t='Total Time(s)',i='Current(A)',qc='Chg. Cap.(Ah)',qd='DChg. Cap.(Ah)',stamp='Date',step='Step Index',cycle='Cycle Index',status='Step Type')
    else:
        schema=dict(t='test_time_s',i='current_A',qc='charge_capacity_Ah',qd='discharge_capacity_Ah',stamp='date_time_iso_string',step='step_index',cycle='cycle_index',status='step_name')
    h=next(k for k,line in enumerate(lines[:100]) if schema['t'] in next(csv.reader([line])))
    rows=[]
    for row in csv.DictReader(lines[h:]):
        if not row.get(schema['t']):continue
        r={k:float(row[schema[k]]) for k in ('t','i','qc','qd')}
        status=row[schema['status']].lower()
        direction=-1 if any(s in status for s in ('discharge','dchg','dch')) else 1 if any(s in status for s in ('charge','chg','cha')) else None
        r.update(stamp=row[schema['stamp']],step=(row[schema['cycle']],row[schema['step']]),direction=direction)
        rows.append(r)
    return rows,schema

def wilson(success,total):
    if not total:return None
    z=1.959963984540054;p=success/total;den=1+z*z/total
    center=(p+z*z/(2*total))/den;half=z*math.sqrt(p*(1-p)/total+z*z/(4*total*total))/den
    return [center-half,center+half]

def independent_charge_check(rows,result):
    """Independent right-rectangle check on constant-current segments (not estimator helper)."""
    errors=[]
    for a,b in zip(rows,rows[1:]):
        if a['step']!=b['step'] or b['t']<=a['t'] or b['qc'] is None:continue
        measured=(b['qc']-a['qc'])-(b['qd']-a['qd'])
        if abs(measured)<1e-8:continue
        predicted=b['i']*result['proposed_current_sign']*(b['t']-a['t'])*result['proposed_time_factor']/3600.
        errors.append(abs(predicted-measured)/abs(measured))
    return statistics.median(errors) if errors else None

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    if (OUT/'results.json').exists():raise SystemExit('Existing results retained; choose a new run directory before rerun.')
    source_paths=['user_tools/workbench/joint_cycler_diagnosis.py','user_tools/validate_joint_cycler_diagnosis.py','docs/joint_cycler_diagnosis_20261016.md']
    manifest={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in source_paths}
    (OUT/'frozen_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    results=[];public=[]
    rawfile=(OUT/'synthetic_observations.jsonl').open('w',encoding='utf-8')
    truthfile=(OUT/'synthetic_truth.jsonl').open('w',encoding='utf-8')
    with rawfile,truthfile,(OUT/'candidate_logs.jsonl').open('w',encoding='utf-8') as logs:
        for scenario in SCENARIOS:
            for seed in range(1000,1100):
                rows,truth=synthetic(seed,scenario);case=f'{scenario}_{seed}'
                rawfile.write(json.dumps(dict(case=case,records=rows))+'\n')
                truthfile.write(json.dumps(dict(case=case,**truth))+'\n')
                for evidence in ('joint','clock','charge'):
                    out=diagnose(rows,evidence)
                    logs.write(json.dumps(dict(case=case,method=evidence,**out))+'\n')
                    correct=out['proposed_time_factor']==truth['time_factor'] and out['proposed_current_sign']==truth['current_sign']
                    results.append(dict(case=case,scenario=scenario,method=evidence,
                        accepted=out['auto_applicable'],correct_accepted=out['auto_applicable'] and correct and truth['identifiable'],
                        wrong_accepted=out['auto_applicable'] and (not correct or not truth['identifiable']),
                        scale_correct=out['proposed_time_factor']==truth['time_factor'],
                        identifiable=truth['identifiable'],reset_detected=bool(out['counter_reset_events']),
                        independent_charge_error=independent_charge_check(rows,out) if out['auto_applicable'] and truth['identifiable'] else None))
        root=ROOT/'data/external/cycler_pipeline_qc_18214281/raw'
        for path in sorted(root.glob('*.csv')):
            rows,schema=public_records(path)
            normalized,qc=normalize_csv(path.read_bytes())
            modes={mode:diagnose(rows,mode) for mode in ('joint','clock','charge')}
            logs.write(json.dumps(dict(public_file=path.name,results=modes))+'\n')
            public.append(dict(file=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),rows=len(rows),schema=schema,
                previous_normalizer=dict(qc_pass=qc['qc_pass'],segments=qc['segments'],warnings=qc['warnings']),
                methods={m:{k:v for k,v in r.items() if k not in ('candidates','interval_evidence')} for m,r in modes.items()}))
    summary=[]
    for scenario in SCENARIOS:
        for method in ('joint','clock','charge'):
            group=[r for r in results if r['scenario']==scenario and r['method']==method]
            n=len(group);correct=sum(r['correct_accepted'] for r in group);wrong=sum(r['wrong_accepted'] for r in group)
            summary.append(dict(scenario=scenario,method=method,n=n,accepted=sum(r['accepted'] for r in group),correct_accepted=correct,wrong_accepted=wrong,
                correct_accepted_95ci=wilson(correct,n),wrong_accepted_95ci=wilson(wrong,n),
                scale_correct=sum(r['scale_correct'] for r in group),reset_detected=sum(r['reset_detected'] for r in group)))
    payload=dict(summary=summary,public_development_checks=public,
        statistical_unit='independent_synthetic_trajectory_not_rows; same seeds paired across methods',
        limits='synthetic finite hypotheses, known counter units/semantics, no novelty or real experiment benefit proved')
    (OUT/'results.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    with (OUT/'episodes.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(results[0]));w.writeheader();w.writerows(results)
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in manifest.items())
    print(json.dumps(payload,ensure_ascii=False,indent=2))

if __name__=='__main__':main()

"""Frozen-seed v2 pilot; raw observations and truth stored separately."""
import argparse
import copy
import csv
import hashlib
import json
import random
import shutil
from pathlib import Path
from .validate_joint_cycler_diagnosis import ROOT, SCENARIOS, synthetic, public_records, wilson
from .workbench.joint_cycler_diagnosis import diagnose
from .workbench.joint_cycler_diagnosis_v2 import diagnose_v2, PrecisionBudget

EXTRA=('coarse_low_current','coarse_combined_reset','coarse_wrong_capacity_scale',
       'coarse_missing_reference','same_time_changed_voltage','exact_duplicate','precision_limited')
ALL_SCENARIOS=SCENARIOS+EXTRA

def fixture(seed,scenario):
    coarse=scenario.startswith('coarse') or scenario=='precision_limited'
    if not coarse:
        rows,truth=synthetic(seed,scenario if scenario in SCENARIOS else 'clean')
        for r in rows:r['voltage']=3.7  # independent field, never used for sign inference
        budget=PrecisionBudget(0.,1e-8,1e-8,0.001,.01,'synthetic declared bounds')
        if scenario=='exact_duplicate':rows.insert(80,copy.deepcopy(rows[79]))
        if scenario=='same_time_changed_voltage':
            new=copy.deepcopy(rows[79]);new['voltage']=3.71;rows.insert(80,new);truth['identifiable']=False
        truth.update(scenario=scenario,expected_charge_status=None)
        return rows,budget,truth
    rng=random.Random(seed);rows=[];t=0.;qc=qd=0.;physical_i=0.
    short=scenario in ('coarse_missing_reference','precision_limited')
    combined=scenario=='coarse_combined_reset'
    factor=.001 if combined else 1.;sign=-1 if combined else 1
    n=240 if short else 1440;size=n//6
    for k in range(n):
        dt=rng.uniform(1,2) if short else rng.uniform(120,300)
        if k:t+=dt
        step=k//size;direction=1 if step%2==0 else -1
        if k%size==0:
            physical_i=direction*rng.uniform(.00021,.00089)
            if combined:qc=qd=0.
        else:
            qc+=max(physical_i,0)*dt/3600;qd+=max(-physical_i,0)*dt/3600
        scale=100 if scenario=='coarse_wrong_capacity_scale' else 1
        rows.append(dict(t=t/factor,i=round(sign*physical_i,4),
            qc=round(scale*qc,4),qd=round(scale*qd,4),stamp=t,step=step,
            direction=direction,voltage=3.7))
    if scenario=='coarse_missing_reference':
        for r in rows:r.update(stamp=None,direction=None)
    truth=dict(seed=seed,scenario=scenario,time_factor=factor,current_sign=sign,
        identifiable=scenario not in ('coarse_missing_reference','coarse_wrong_capacity_scale'),
        reset=combined,expected_charge_status='precision_limited_or_unresolved' if scenario=='precision_limited' else None)
    return rows,PrecisionBudget(.0001,.0001,.0001,.001,.01,'synthetic exported grid; one grid step bound'),truth

def public_input(path):
    rows,schema=public_records(path)
    lines=path.read_text(encoding='utf-8-sig').splitlines()
    h=next(k for k,s in enumerate(lines[:100]) if schema['t'] in next(csv.reader([s])))
    originals=list(csv.DictReader(lines[h:]));assert len(originals)==len(rows)
    # DictReader represents extra trailing columns under a None key. Preserve all
    # fields as ordered pairs; sorting heterogeneous keys would fail on Landt.
    for row,original in zip(rows,originals):row['source_signature']=json.dumps(list(original.items()),ensure_ascii=False)
    fixed_four=all('.' in r[schema['i']] and len(r[schema['i']].split('.')[-1])==4 for r in originals if float(r[schema['i']])!=0)
    # This is an explicit EXPORT quantization assumption, not an instrument accuracy certificate.
    quantum=.0001 if fixed_four else 0.
    budget=PrecisionBudget(quantum,quantum,quantum,.001,.01,
        'assumed full display-step bound on fixed-four-decimal export + unverified 1% relative current bound; otherwise only 1% relative current allowance')
    return rows,budget,schema

SOURCES=('user_tools/workbench/joint_cycler_diagnosis_v2.py',
 'user_tools/validate_joint_cycler_diagnosis_v2.py','docs/joint_cycler_diagnosis_v2_20261016.md',
 'user_tools/workbench/joint_cycler_diagnosis.py','user_tools/validate_joint_cycler_diagnosis.py')

def main(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    if (out/'frozen_manifest.json').exists():raise SystemExit('Refusing existing run; select a fresh output directory.')
    frozen={s:hashlib.sha256((ROOT/s).read_bytes()).hexdigest() for s in SOURCES}
    for rel in SOURCES:
        target=out/'source'/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/rel,target)
    (out/'frozen_manifest.json').write_text(json.dumps(frozen,indent=2),encoding='utf-8')
    episodes=[]
    with (out/'observations.jsonl').open('w') as obs,(out/'truth.jsonl').open('w') as truthfile,(out/'candidate_logs.jsonl').open('w') as log:
        for scenario in ALL_SCENARIOS:
            for seed in range(2000,2100):
                rows,budget,truth=fixture(seed,scenario);case=f'{scenario}_{seed}'
                obs.write(json.dumps(dict(case=case,records=rows,precision_budget=budget.__dict__))+'\n')
                truthfile.write(json.dumps(dict(case=case,**truth))+'\n')
                for method in ('v1','v2'):
                    result=diagnose(rows) if method=='v1' else diagnose_v2(rows,budget)
                    log.write(json.dumps(dict(case=case,method=method,result=result))+'\n')
                    accepted=result['auto_applicable'];numeric_correct=(result['proposed_time_factor']==truth['time_factor'] and result['proposed_current_sign']==truth['current_sign'])
                    episodes.append(dict(case=case,scenario=scenario,method=method,accepted=accepted,
                        correct_accepted=accepted and numeric_correct and truth['identifiable'],
                        numerical_wrong_accept=accepted and not numeric_correct,
                        policy_violating_accept=accepted and not truth['identifiable'],
                        expected_accept=truth['identifiable'],
                        charge_status=result.get('charge_status'),duplicate_rows=len(result.get('removed_exact_duplicate_rows',[]))))
    summary=[]
    for scenario in ALL_SCENARIOS:
        for method in ('v1','v2'):
            group=[x for x in episodes if x['scenario']==scenario and x['method']==method];n=len(group)
            r=dict(scenario=scenario,method=method,n=n)
            for k in ('accepted','correct_accepted','numerical_wrong_accept','policy_violating_accept'):
                r[k]=sum(x[k] for x in group);r[k+'_95ci']=wilson(r[k],n)
            summary.append(r)
    paired=[]
    for scenario in ALL_SCENARIOS:
        a=[x for x in episodes if x['scenario']==scenario and x['method']=='v1']
        b=[x for x in episodes if x['scenario']==scenario and x['method']=='v2']
        diffs=[int(y['correct_accepted'])-int(x['correct_accepted']) for x,y in zip(a,b)]
        paired.append(dict(scenario=scenario,correct_accept_rate_difference=sum(diffs)/len(diffs),
            improved_pairs=sum(d>0 for d in diffs),worsened_pairs=sum(d<0 for d in diffs),n=len(diffs)))
    public=[]
    for path in sorted((ROOT/'data/external/cycler_pipeline_qc_18214281/raw').glob('*.csv')):
        rows,budget,schema=public_input(path)
        r=diagnose_v2(rows,budget)
        public.append(dict(file=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),schema=schema,result=r))
    payload=dict(summary=summary,paired=paired,public_development_checks=public,
        seed_range=[2000,2099],scope='conditional synthetic evidence; public files reused development; not patent novelty')
    (out/'results.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    with (out/'episodes.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(episodes[0]));w.writeheader();w.writerows(episodes)
    assert all(hashlib.sha256((ROOT/s).read_bytes()).hexdigest()==h for s,h in frozen.items())
    for r in summary:print(r['scenario'],r['method'],'correct',r['correct_accepted'],'unsafe',r['policy_violating_accept'],'numeric_wrong',r['numerical_wrong_accept'])
    for x in public:
        r=x['result'];print(x['file'],r['status'],r['proposed_time_factor'],r['proposed_current_sign'],r['charge_status'],'windows',len(r['windows']))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',default=str(ROOT/'outputs/analysis/joint_cycler_diagnosis_v2_20261016'))
    main(parser.parse_args().out)

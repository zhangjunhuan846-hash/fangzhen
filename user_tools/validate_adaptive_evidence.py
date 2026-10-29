"""Independent metric recomputation and full-record RK4 check without adapter imports."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import numpy as np


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);parser.add_argument('--data',type=Path,required=True);args=parser.parse_args()
    proof=json.loads((args.out/'desktop_acceptance.json').read_text(encoding='utf-8'));checks=[]
    def folder(action):return args.data/'jobs'/next(t['job_id'] for t in proof['tasks'] if t['action']==action)/'physics'
    p=folder('commercial_adaptive');frozen=json.loads((p/'adaptive_frozen_model.json').read_text(encoding='utf-8'))
    result=json.loads((p/'adaptive_validation.json').read_text(encoding='utf-8'))
    assert hashlib.sha256((p/'adaptive_frozen_model.json').read_bytes()).hexdigest()==result['freeze_sha256']
    rows=list(csv.DictReader((p/'engineering.csv').open(encoding='utf-8-sig')));groups={}
    for row in rows:groups.setdefault(row['test'],[]).append(row)
    counts={};observed_count=0
    for score in result['tests']:
        group=groups[score['test']];observed=[r for r in group if r['measurement_used']=='True'];observed_count+=len(observed)
        assert len(observed)==score['points'] and len(group)==score['simulation_points']
        for label,key in [('updated_voltage_V','voltage_rmse_mV'),('baseline_voltage_V','baseline_voltage_rmse_mV')]:
            metric=math.sqrt(math.fsum((float(r[label])-float(r['measured_voltage_V']))**2 for r in observed)/len(observed))*1000
            assert abs(metric-score[key])<1e-8,(label,metric,score[key])
        for r in group:
            if r['measurement_used']!='True':assert r['measured_voltage_V']=='' and r['innovation_V']==''
        counts[score['role']]=counts.get(score['role'],0)+1
    assert counts==dict(fresh_condition_holdout=7,development_exposed_regression=2,historical_aging_regression=10)
    checks.append(dict(check='all19_observation_masked_metric_recalculations_and_role_counts',passed=True,simulation_points=len(rows),observations=observed_count))
    # A complete0C US06 record, recomputed from first-principles equations with a separately written RK4.
    name=next(k for k in groups if '0degC_US06' in k);group=groups[name];model=frozen['model'];grid=np.array(model['soc_grid']);temps=np.array(model['temperature_nodes_C']);tables=np.array(model['tables'])
    scale=model['aging_scales'];ambient=0.;state=np.array([1.,0.,float(group[0]['measured_temperature_C'])])
    def lookup(s,t,j):return float(np.interp(t,temps,[np.interp(s,grid,table) for table in tables[j]]))
    def rhs(x,i):
        rc_temp=x[2] if model['dynamic_case_temperature'] else ambient
        r0=lookup(x[0],rc_temp,1)*scale[0];r1=lookup(x[0],rc_temp,2)*scale[1];c1=lookup(x[0],rc_temp,3)*scale[2]/scale[1]
        return np.array([-i/(3600*model['capacity_Ah']),(i*r1-x[1])/(r1*c1),
            (i*(i*r0+x[1])-model['heat_transfer_W_K']*(x[2]-ambient))/model['thermal_capacity_J_K']])
    maximum=0.
    for j,row in enumerate(group):
        current=float(row['current_A']);dt=float(row['time_s'])-float(group[j-1]['time_s']) if j else 0.;n=max(1,math.ceil(dt/.1));h=dt/n
        for _ in range(n):
            k1=rhs(state,current);k2=rhs(state+h*k1/2,current);k3=rhs(state+h*k2/2,current);k4=rhs(state+h*k3,current)
            state=state+h*(k1+2*k2+2*k3+k4)/6
        rc_temp=state[2] if model['dynamic_case_temperature'] else ambient
        v=lookup(state[0],ambient,0)-state[1]-current*lookup(state[0],rc_temp,1)*scale[0]
        maximum=max(maximum,abs(v-float(row['updated_voltage_V'])))
    assert maximum<1e-4,maximum
    checks.append(dict(check='full0C_US06_independent_RK4_vs_Thevenin',passed=True,max_voltage_difference_V=maximum))
    numerical=json.loads((p/'adaptive_numerical_audit.json').read_text(encoding='utf-8'))
    assert max(r['max_voltage_difference_V'] for r in numerical)<1e-4
    assert max(r['max_temperature_difference_C'] for r in numerical)<.005
    checks.append(dict(check='all19_Thevenin_vs_midpoint_solvers',passed=True))
    eis=json.loads((folder('eis_audit')/'eis_audit.json').read_text(encoding='utf-8'))
    assert len(eis['spectra'])==14 and all(s['excluded_points']==0 and s['unit']['unit_consistency_pass'] for s in eis['spectra'])
    assert max(s['augmented']['independent_SVD_max_difference_ohm'] for s in eis['spectra'])<1e-7
    checks.append(dict(check='EIS14_full_spectra_unit_redundancies_and_independent_SVD',passed=True,points=sum(s['points'] for s in eis['spectra'])))
    trace=json.loads((folder('safety_bench')/'safety_trace.json').read_text(encoding='utf-8'));cases=json.loads((folder('safety_bench')/'safety_cases.json').read_text(encoding='utf-8'))
    assert len(cases)==12 and all(c['expected_stop']==c['actual_stop'] and c['physical_command_sent'] is False for c in cases)
    assert all(r['command_charge_A']==0. for r in trace[4:]) and max(r['soc'] for r in trace[4:])-min(r['soc'] for r in trace[4:])<1e-10
    checks.append(dict(check='SIL12_cases_latched_current_zero_and_frozen_SOC',passed=True))
    root=Path(__file__).resolve().parents[1]
    for task in proof['tasks']:
        f=args.data/'jobs'/task['job_id']/'physics';obj=json.loads((f/'result.json').read_text(encoding='utf-8'))
        for name,sha in obj['code_sha256'].items():
            assert hashlib.sha256((f/'code_snapshot'/name).read_bytes()).hexdigest()==sha
            assert hashlib.sha256((root/'user_tools/workbench'/name).read_bytes()).hexdigest()==sha
        assert hashlib.sha256((f/'dependency_manifest.json').read_bytes()).hexdigest()==obj['dependency_manifest_sha256']
    checks.append(dict(check='all5_job_code_snapshots_runtime_manifests_and_current_source_hashes',passed=True))
    (args.out/'independent_audit.json').write_text(json.dumps(dict(passed=True,checks=checks,scope='numerical and artifact verification, not hardware certification'),ensure_ascii=False,indent=2),encoding='utf-8')
    print(checks)


if __name__=='__main__':main()

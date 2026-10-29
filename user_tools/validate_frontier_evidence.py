"""Independent artifact, metric and first-principles ODE checks; no adapter math imported."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import numpy as np


def main():
    parser=argparse.ArgumentParser();parser.add_argument('acceptance',type=Path);parser.add_argument('--data',type=Path,required=True);args=parser.parse_args()
    proof=json.loads(args.acceptance.read_text(encoding='utf-8')); checks=[]
    root=Path(__file__).resolve().parents[1]
    commercial=next(t for t in proof['tasks'] if t['action']=='commercial_validation')
    out=args.data/'jobs'/commercial['job_id']/'physics'
    evidence=json.loads((out/'commercial_validation.json').read_text(encoding='utf-8'))
    frozen=json.loads((out/'frozen_model.json').read_text(encoding='utf-8'))
    assert hashlib.sha256((out/'frozen_model.json').read_bytes()).hexdigest()==evidence['frozen_model_sha256']
    assert evidence['parameter_tuned_on_holdout'] is False
    rows=list(csv.DictReader((out/'engineering.csv').open(encoding='utf-8-sig')))
    for test in evidence['tests']:
        group=[r for r in rows if r['test']==test['test']]
        assert len(group)==test['points']
        squared=[(float(r['predicted_voltage_V'])-float(r['measured_voltage_V']))**2 for r in group]
        rmse=math.sqrt(math.fsum(squared)/len(group))*1000
        assert abs(rmse-test['voltage_rmse_mV'])<1e-8
        soc=math.sqrt(math.fsum((float(r['soc_ekf'])-float(r['soc_coulomb_reference']))**2 for r in group)/len(group))
        assert abs(soc-test['ekf_rmse_soc'])<1e-10
    checks.append({'check':'recomputed_all_15_voltage_and_SOC_metrics_from_exported_rows','passed':True,'points':len(rows)})
    # Independent RK4 ODE for the complete US06 trajectory, including SOC-dependent RC.
    # This code does not import the Thevenin model, plant_parameters, predict or resample.
    m=frozen['model']; table=m['table']; nodes=np.array([r['soc'] for r in table]); n=m['branches']
    group=[r for r in rows if 'US06' in r['test']]
    ambient_data=__import__('scipy.io',fromlist=['loadmat']).loadmat(next((root/'data/public/panasonic_pf_v1').rglob('*US06_*.mat')),simplify_cells=True)['meas']
    ambient=float(np.median(ambient_data['Chamber_Temp_degC']))
    state=np.r_[1.,np.zeros(n),float(group[0]['measured_temperature_C'])]
    expected_v=[];expected_t=[]
    def values(s):
        return [float(np.interp(s,nodes,[r[k] for r in table])) for k in ['R0_ohm']+[v for j in range(1,n+1) for v in [f'R{j}_ohm',f'C{j}_F']]]
    def rhs(s,current):
        rc=values(s[0]);derivative=[-current/(3600*m['capacity_Ah'])]
        derivative += [(current*rc[1+2*j]-s[j+1])/(rc[1+2*j]*rc[2+2*j]) for j in range(n)]
        derivative += [(current*(current*rc[0]+sum(s[1:1+n]))-m['heat_transfer_W_K']*(s[-1]-ambient))/m['thermal_capacity_J_K']]
        return np.asarray(derivative)
    for i,row in enumerate(group):
        current=float(row['current_A'])
        dt=float(row['time_s'])-float(group[i-1]['time_s']) if i else 0.
        substeps=max(1,math.ceil(dt/.1));h=dt/substeps
        for _ in range(substeps):
            k1=rhs(state,current);k2=rhs(state+h*k1/2,current);k3=rhs(state+h*k2/2,current);k4=rhs(state+h*k3,current)
            state=state+h*(k1+2*k2+2*k3+k4)/6
        v=float(np.interp(state[0],m['ocv_soc'],m['ocv_V']))-current*values(state[0])[0]-sum(state[1:1+n])
        expected_v.append(v);expected_t.append(state[-1])
    maximum_v=float(np.max(np.abs(np.asarray(expected_v)-[float(r['predicted_voltage_V']) for r in group])))
    maximum_t=float(np.max(np.abs(np.asarray(expected_t)-[float(r['predicted_temperature_C']) for r in group])))
    assert maximum_v<.001 and maximum_t<.02,(maximum_v,maximum_t)
    checks.append({'check':'complete_US06_Thevenin_vs_independent_RK4_ODE','passed':True,'max_voltage_difference_V':maximum_v,'max_temperature_difference_C':maximum_t})
    # Recompute and enforce whole-cell split and training-only normalization.
    for task in [t for t in proof['tasks'] if t['action']=='batterylife']:
        folder=args.data/'jobs'/task['job_id']/'physics'
        split=json.loads((folder/'batterylife_split.json').read_text(encoding='utf-8'))
        train=set(split['normalizers_fit_on']);val=set(split['validation_ids']);test=set(split['test_ids'])
        assert not(train&val or train&test or val&test)
        assert (len(train),len(val),len(test))==(45,15,16)
        pred=list(csv.DictReader((folder/'engineering.csv').open(encoding='utf-8-sig')))
        actual=[r for r in pred if r['model'].startswith('BatteryLife_')]
        mae=math.fsum(abs(float(r['predicted_rul_cycles'])-float(r['reference_rul_cycles'])) for r in actual)/len(actual)
        assert abs(mae-task['metrics']['test_mae_cycles'])<1e-6
        assert set(r['cell_id'] for r in actual)==test
        checks.append({'check':'BatteryLife_independent_cell_split_and_MAE_'+actual[0]['model'],'passed':True,'test_cells':len(test)})
    for task in [t for t in proof['tasks'] if t['mode']=='engineering']:
        folder=args.data/'jobs'/task['job_id']/'physics'
        result=json.loads((folder/'result.json').read_text(encoding='utf-8'))
        assert result['material_validation'] is False and result['hardware_connected'] is False
        for name,sha in result['code_sha256'].items():assert hashlib.sha256((root/'user_tools/workbench'/name).read_bytes()).hexdigest()==sha,name
        assert hashlib.sha256((folder/'dependency_manifest.json').read_bytes()).hexdigest()==result['dependency_manifest_sha256']
    checks.append({'check':'every_final_engineering_source_hash_and_dependency_snapshot','passed':True})
    target=args.acceptance.parent/'independent_evidence_audit.json'
    target.write_text(json.dumps(dict(checks=checks,passed=all(c['passed'] for c in checks),scope='independent numerical/artifact checks; no hardware or material certification'),ensure_ascii=False,indent=2),encoding='utf-8')
    print(target);print(checks)


if __name__=='__main__':main()

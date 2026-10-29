"""Bounded, reproducible ask/evaluate/tell demonstration on a frozen commercial-cell model.

This is simulation evidence. It never reads independent measured-test outcomes.
"""
import csv
import io
import json
from pathlib import Path
import time
import numpy as np

from user_tools.workbench.engineering_common import finish, save, write_csv
from user_tools.workbench.engineering_contracts import defaults
from user_tools.workbench.engineering_commercial import parameters
from user_tools.workbench.engineering_frontier import run_frontier


def simulate(model, x, fidelity):
    import thevenin
    dt = {0.3: 60., 0.6: 20., 1.: 5.}[float(fidelity)]
    p = parameters(model, .3, 25., 25.)
    plant = thevenin.Prediction(p); plant.set_options(rtol=1e-8, atol=1e-10)
    state = thevenin.TransientState(.3, 298.15, 0., np.zeros(model['branches']))
    elapsed, maximum_t, maximum_v, guards = 0., 25., 0., 0
    for _ in range(1800):
        ampere = 2.9*(.5+.5*x[0]) if state.soc < .6 else 2.9*(.3+.7*x[1])
        # Voltage guard uses only the model's current state; no look-ahead target labels.
        max_i = (4.19-p['ocv'](state.soc)+float(np.sum(state.eta_j)))/p['R0'](state.soc,state.T_cell)
        if ampere > max_i: guards += 1
        ampere = max(.01, min(ampere, max_i))
        step = min(dt, max(.001,(.8-state.soc)*3600*model['capacity_Ah']/ampere))
        state = plant.take_step(state, -ampere, step); elapsed += step
        maximum_t = max(maximum_t, float(state.T_cell-273.15)); maximum_v = max(maximum_v, float(state.voltage))
        if state.soc >= .8-1e-8: break
        if maximum_t > 45 or maximum_v > 4.21: raise RuntimeError('Simulated charging constraint exceeded')
    if state.soc < .8-1e-8: raise RuntimeError('Charging target not reached')
    return dict(charge_time_s=elapsed,max_temperature_C=maximum_t,max_voltage_V=maximum_v,guards=guards,
                objective1=-elapsed/3600,objective2=-(maximum_t-25),fidelity=float(fidelity))


def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--model',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    model=json.loads(args.model.read_text(encoding='utf-8'))['model']
    rng=np.random.default_rng(42); initial=rng.uniform(0,1,(12,2)); evaluations=[]
    # No neural/optimization worker has access to the simulation evaluator or its future labels.
    for algorithm in ['mobo_osd','rmfbo','camo']:
        folder=args.out/algorithm;folder.mkdir(exist_ok=True)
        levels=[1.] if algorithm=='mobo_osd' else [.3,.6,1.]
        rows=[]
        for j,x in enumerate(initial):
            for f in levels:
                result=simulate(model,x,f)
                rows.append(dict(candidate_id=f'initial-{j}-{f}',x1=x[0],x2=x[1],status='completed',
                    objective1=result['objective1'] if algorithm=='mobo_osd' else result['objective1']+.1*result['objective2'],
                    objective2=result['objective2'],fidelity=f,cost={0.3:1.,0.6:3.,1.:12.}[f]))
                evaluations.append(dict(algorithm=algorithm,round=0,x1=x[0],x2=x[1],**result))
        if algorithm!='mobo_osd':
            for j,x in enumerate(rng.uniform(0,1,(40,2))):
                for f in levels:
                    rows.append(dict(candidate_id=f'pool-{j}-{f}',x1=x[0],x2=x[1],status='candidate',objective1='',objective2='',fidelity=f,cost={0.3:1.,0.6:3.,1.:12.}[f]))
        start=time.perf_counter()
        for round_no in range(1,4):
            text=io.StringIO();w=csv.DictWriter(text,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
            request=defaults('frontier');request.update(algorithm=algorithm,data_origin='public',source='Panasonic PF HPPC-calibrated Thevenin simulation; frozen_model='+str(args.model))
            stepout=folder/f'round{round_no}';stepout.mkdir(exist_ok=True)
            write_csv(stepout/'submitted_observations.csv',rows)
            asked=run_frontier(request,stepout,text.getvalue().encode())
            for proposal in asked['recommendations']:
                x=[proposal['x1'],proposal['x2']];f=proposal['fidelity'];result=simulate(model,x,f)
                record=dict(candidate_id=f'queried-{round_no}-{len(rows)}',x1=x[0],x2=x[1],status='completed',
                    objective1=result['objective1'] if algorithm=='mobo_osd' else result['objective1']+.1*result['objective2'],
                    objective2=result['objective2'],fidelity=f,cost={0.3:1.,0.6:3.,1.:12.}[f])
                if algorithm=='mobo_osd':rows.append(record)
                else:
                    target=next(r for r in rows if r['candidate_id']==proposal['candidate_id']);record['candidate_id']=target['candidate_id'];target.update(record)
                evaluations.append(dict(algorithm=algorithm,round=round_no,x1=x[0],x2=x[1],**result))
            print(algorithm,'round',round_no,'evaluated',len(asked['recommendations']),flush=True)
        save(folder/'loop_summary.json',dict(algorithm=algorithm,rounds=3,elapsed_s=time.perf_counter()-start,
             simulation_only=True,independent_measured_test_access=False,declared_cost_ratios=[1,3,12],
             objective='MOBO: maximize -charge hours and -temperature rise; MFBO/CAMO: maximize -charge hours-0.1*temperature rise',
             evaluations=[e for e in evaluations if e['algorithm']==algorithm]))
    write_csv(args.out/'evaluations.csv',evaluations)
    save(args.out/'summary.json',dict(simulation_only=True,independent_measured_test_access=False,
         algorithms=['mobo_osd','rmfbo','camo'],rounds_each=3,evaluations=len(evaluations),
         scope='Same frozen commercial-cell ECM; fidelity is solver/control interval60/20/5s with cost proxy1/3/12; not learned material chemistry or measured lifetime gains.'))


if __name__=='__main__':main()

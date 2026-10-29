"""Scoped action-selection study: unchanged worlds, exact KG, factorial models.

No platform integration; all measurements are dimensionless mathematical toys.
The original pilot is a declared development set. Selectors never receive World.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import time
import numpy as np
from user_tools.workbench.action_validation import (SCENARIOS, PRIOR_SD, Posterior,
    public_design, available_actions, SyntheticWorld, keyed_rng, digest, kg_scores, write_csv)
from user_tools.workbench.action_study_numerics import action_scores

MODELS = ('full','fixed_radius','no_discrepancy')
POLICIES = tuple(f'{m}__{c}' for m in MODELS for c in ('kg','contrast_variance'))+('full__ei',)


def prior_for(model):
    sd = PRIOR_SD.copy()
    if model=='fixed_radius': sd[3]=1e-6
    if model=='no_discrepancy': sd[5]=1e-6
    if model not in MODELS: raise ValueError('Unknown observation model')
    return Posterior(np.zeros(6),np.diag(sd**2))


def choose(p,design,pool,policy):
    model,criterion = policy.split('__')
    f = np.array([r['target_h'] for r in design]); offsets = np.array([r['offset'] for r in design])
    if criterion=='gh31':
        scores = kg_scores(p,design,pool,31)/np.array([a['cost'] for a in pool])
    else:
        scores = action_scores(p.mean,p.covariance,f,offsets,pool,criterion)
    ix = int(np.argmax(scores))
    return (pool[ix] if scores[ix]>1e-12 else None),float(scores[ix])


def campaign(scenario,instance,policy,budget,adaptive_stream,final_stream):
    model,_ = policy.split('__')
    world = SyntheticWorld(scenario,instance)
    design = public_design(scenario)
    p = prior_for(model); counts = Counter(); observed=[]; spent=0.; fee=1.6
    for kind,cid in [('tau_protocol','global'),('reference','x00'),('reference','x06'),('reference','x12')]:
        a = next(a for a in available_actions(design,counts,budget-fee-spent)
                 if a['kind']==kind and a['candidate_id']==cid)
        y = world.observe(a,design)
        observed.append({**a,'value':y,'phase':'initial'})
        counts[(kind,cid)]+=1; spent+=a['cost']
        p = p.update(a['h'],y,a['noise_sd'],a['offset'])
    initial_hash=digest(observed)
    step=0; stop='no_affordable_action'
    while True:
        pool=available_actions(design,counts,budget-fee-spent)
        if not pool: break
        a,score=choose(p,design,pool,policy)
        if a is None:
            stop='no_positive_acquisition'; break
        record={'scenario':scenario,'instance':instance,'policy':policy,'step':step,
                'spent_before':spent,'remaining_search_budget':budget-fee-spent,
                'observations_sha256':digest(observed),'available_actions_sha256':digest(pool),
                'action':a,'score':score,'posterior_mean':p.mean.tolist(),
                'posterior_covariance':p.covariance.tolist()}
        adaptive_stream.write(json.dumps(record,allow_nan=False)+'\n'); adaptive_stream.flush()
        y=world.observe(a,design)
        observed.append({**a,'value':y,'phase':'adaptive'})
        p=p.update(a['h'],y,a['noise_sd'],a['offset'])
        counts[(a['kind'],a['candidate_id'])]+=1; spent+=a['cost']; step+=1
        if spent+fee>budget+1e-9: raise AssertionError('Budget exceeded')
    f=np.array([r['target_h'] for r in design]); offsets=np.array([r['offset'] for r in design])
    mu=offsets+f@p.mean; cov=f@p.covariance@f.T; ix=int(np.argmax(mu))
    confirmation_sd=float(np.sqrt(max(cov[ix,ix],0)+.2**2/3))
    final={'scenario':scenario,'instance':instance,'policy':policy,'selected_id':design[ix]['id'],
           'observations_sha256':digest(observed),'prediction_mean':float(mu[ix]),
           'prediction_interval_95':[float(mu[ix]-1.96*confirmation_sd),float(mu[ix]+1.96*confirmation_sd)],
           'spent_before_confirmation':spent,'reserved_confirmation_cost':fee,'budget':budget,
           'target_mean':mu.tolist(),'target_covariance':cov.tolist()}
    final_stream.write(json.dumps(final,allow_nan=False)+'\n'); final_stream.flush()
    # Oracle accesses below are evaluator-only, after the terminal commitment.
    truth=np.array([world.target_truth(r) for r in design])
    confirmation_reads=(world.target_truth(design[ix])+keyed_rng('final_confirmation',scenario,instance,
                         design[ix]['id']).normal(0,.2,3)).tolist()
    confirmation_mean=float(np.mean(confirmation_reads))
    r={'scenario':scenario,'instance':instance,'policy':policy,'model':model,
       'criterion':policy.split('__')[1],'budget':budget,'spent':spent+fee,
       'unused_budget':budget-spent-fee,'confirmation_cost':fee,'initial_hash':initial_hash,
       'selected_id':design[ix]['id'],'simple_regret':float(truth.max()-truth[ix]),
       'oracle_max':float(truth.max()),'selected_truth':float(truth[ix]),
       'exact_best':bool(truth.max()-truth[ix]<1e-9),'within_0p5':bool(truth.max()-truth[ix]<=.5),
       'confirmation_reads':confirmation_reads,'confirmation_mean':confirmation_mean,
       'confirmation_used_in_training':False,'adaptive_actions':step,'stop_reason':stop,
       'oracle_target_values':truth.tolist(),'truth_theta':world.theta.tolist(),'sin_amplitude':world.sin_amplitude,
       'observations':observed,'posterior_radius_sd':float(np.sqrt(p.covariance[3,3])),
       'interval_fraction':float(np.mean(np.abs(mu-truth)<=1.96*np.sqrt(np.maximum(np.diag(cov),0)))),
       'confirmation_interval_hit':bool(abs(confirmation_mean-mu[ix])<=1.96*confirmation_sd)}
    for kind in ['reference','target','radius_characterization','tau_protocol','alternative_protocol']:
        r[kind+'_adaptive_cost']=sum(a['cost'] for a in observed if a['phase']=='adaptive' and a['kind']==kind)
    return r


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--split',choices=['development','validation'],required=True)
    parser.add_argument('--protocol',type=Path)
    args=parser.parse_args()
    if args.output.exists(): raise FileExistsError('Evidence must not be overwritten')
    if args.split=='development':
        config={'split':'development','first_instance':1000,'instances_per_scenario':40,
                'budget':10.,'policies':list(POLICIES)+['full__gh31'],'scenarios':list(SCENARIOS)}
    else:
        if args.protocol is None: raise ValueError('Frozen protocol required')
        config=json.loads(args.protocol.read_text(encoding='utf-8'))
        if config['first_instance']<20000: raise ValueError('Validation overlaps development')
        if config['policies']!=list(POLICIES): raise ValueError('Unfrozen policies')
        for filename,wanted in config['source_hashes'].items():
            if hashlib.sha256(Path(filename).read_bytes()).hexdigest()!=wanted:
                raise ValueError('Source changed after protocol freeze: '+filename)
    args.output.mkdir(parents=True)
    (args.output/'protocol.json').write_text(json.dumps(config,indent=2),encoding='utf-8')
    snapshots=args.output/'source'; snapshots.mkdir()
    for name in ['action_study.py','action_study_numerics.py','action_validation.py',
                 'action_study_analysis.py','action_study_verify.py']:
        (snapshots/name).write_bytes((Path(__file__).parent/name).read_bytes())
    start=time.monotonic(); records=[]
    with (args.output/'decisions.jsonl').open('w',encoding='utf-8') as actions, \
         (args.output/'final_decisions.jsonl').open('w',encoding='utf-8') as finals:
        for s in config['scenarios']:
            for instance in range(config['first_instance'],config['first_instance']+config['instances_per_scenario']):
                for policy in config['policies']:
                    records.append(campaign(s,instance,policy,config['budget'],actions,finals))
            print(json.dumps({'scenario':s,'campaigns_completed':len(records)}),flush=True)
    result={'protocol':config,'campaigns':records,'elapsed_s':time.monotonic()-start}
    (args.output/'result.json').write_text(json.dumps(result,allow_nan=False),encoding='utf-8')
    excluded={'observations','truth_theta','oracle_target_values','confirmation_reads'}
    write_csv(args.output/'campaigns.csv',[{k:v for k,v in r.items() if k not in excluded} for r in records])
    write_csv(args.output/'confirmation_reads.csv',[{'scenario':r['scenario'],'instance':r['instance'],
        'policy':r['policy'],'read':j+1,'value':v} for r in records for j,v in enumerate(r['confirmation_reads'])])
    print(json.dumps({'status':'completed','campaigns':len(records),'elapsed_s':result['elapsed_s']}),flush=True)


if __name__=='__main__': main()

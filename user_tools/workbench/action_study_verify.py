"""Independent verifier: no experiment implementation imports.

Batch whitened precision solves replace sequential updates. All pairwise line
crossings replace the experiment's upper-hull KG algorithm.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import numpy as np
from scipy.linalg import cho_factor,cho_solve
from scipy.special import ndtr

PRIOR=np.array([.5,1.,.8,.7,1.4,1.])


def sha(obj): return hashlib.sha256(json.dumps(obj,sort_keys=True,allow_nan=False).encode()).hexdigest()
def rng(*parts): return np.random.default_rng(int(hashlib.sha256(':'.join(map(str,parts)).encode()).hexdigest()[:16],16))


def design_for(s):
    result=[]
    for i,x in enumerate(np.linspace(-1,1,13)):
        tau=0. if s=='matched_no_coupling' else (.6 if s=='coupled_ranking_stable' else .3*x*x)
        r=0. if s in ('matched_no_coupling','coupled_ranking_stable') else 2*x
        result.append({'id':f'x{i:02d}','x':float(x),'offset':float(-2*x*x),
            'reference_h':[1.,float(x),float(x*x),float(-2*tau),float(tau),0.],
            'target_h':[1.,float(x),float(x*x),float(-2*tau+r),float(tau),float(2*x**3)]})
    return result


def pool_for(design,obs,remaining):
    counts=Counter((o['kind'],o['candidate_id']) for o in obs)
    actions=[]
    for row in design:
        for kind,sd,fee,maximum in [('reference',.18,.6+.1*abs(row['x']),2),('target',.2,1.8+.4*abs(row['x']),3)]:
            n=counts[kind,row['id']]
            if n<maximum:
                price=1.2 if kind=='target' and n else fee
                actions.append({'id':f'{kind}:{row["id"]}:{n}','kind':kind,'candidate_id':row['id'],
                    'repeat':n,'h':row[kind+'_h'],'offset':row['offset'],'noise_sd':sd,'cost':price})
    for kind,h,sd,fee,maximum in [('tau_protocol',[0,0,0,-2,1,0],.12,.4,3),
        ('radius_characterization',[0,0,0,1,0,0],.15,.7,2),('alternative_protocol',[0,0,0,-.5,1,0],.12,.9,2)]:
        n=counts[kind,'global']
        if n<maximum: actions.append({'id':f'{kind}:global:{n}','kind':kind,'candidate_id':'global',
            'repeat':n,'h':list(map(float,h)),'offset':0.,'noise_sd':sd,'cost':fee})
    return [a for a in actions if a['cost']<=remaining+1e-10]


def batch_posterior(observations,model):
    sd=PRIOR.copy()
    if model in ('fixed_radius','fixed_radius_cost_kg'): sd[3]=1e-6
    if model in ('no_discrepancy','no_discrepancy_cost_kg'): sd[5]=1e-6
    h=np.array([o['h'] for o in observations]); noise=np.array([o['noise_sd'] for o in observations])
    values=np.array([o['value']-o['offset'] for o in observations])
    g=h*sd/noise[:,None]
    factor=cho_factor(np.eye(6)+g.T@g,lower=True)
    cov_z=cho_solve(factor,np.eye(6))
    m_z=cho_solve(factor,g.T@(values/noise))
    return m_z*sd,cov_z*np.outer(sd,sd)


def crossing_integral(mu,slope):
    a=np.asarray(mu)-max(mu); b=np.asarray(slope)-slope[0]
    denominator=b[:,None]-b[None,:]
    numerator=a[None,:]-a[:,None]
    mask=np.triu(np.ones_like(denominator,dtype=bool),1)&(denominator!=0)
    crossings=numerator[mask]/denominator[mask]
    cuts=np.r_[-12.,np.unique(crossings[(crossings>-12)&(crossings<12)]),12.]
    mid=.5*(cuts[:-1]+cuts[1:])
    winners=np.argmax(a[None,:]+mid[:,None]*b[None,:],axis=1)
    l,u=cuts[:-1],cuts[1:]
    mass=np.where(l>=0,ndtr(-l)-ndtr(-u),ndtr(u)-ndtr(l))
    phi=lambda z:np.exp(-.5*z*z)/np.sqrt(2*np.pi)
    return max(0.,float(a[winners]@mass+b[winners]@(phi(l)-phi(u))))


def main():
    p=argparse.ArgumentParser(); p.add_argument('directory',type=Path); p.add_argument('--output',type=Path,required=True)
    p.add_argument('--check-scores',action='store_true'); args=p.parse_args()
    payload=json.loads((args.directory/'result.json').read_text(encoding='utf-8'))
    records=payload['campaigns']; old='confirmation_reads' not in records[0]
    finals={tuple(r[k] for k in ['scenario','instance','policy']):r for r in map(json.loads,(args.directory/'final_decisions.jsonl').read_text().splitlines())}
    decisions={}
    for r in map(json.loads,(args.directory/'decisions.jsonl').read_text().splitlines()):
        decisions.setdefault((r['scenario'],r['instance'],r['policy']),[]).append(r)
    max_mean=max_cov=max_kg=0.; checked_scores=0; near_ties=0; initial={}
    for r in records:
        key=(r['scenario'],r['instance'],r['policy']); obs=r['observations']; design=design_for(r['scenario'])
        f=np.array([d['target_h'] for d in design]); offset=np.array([d['offset'] for d in design])
        model=r.get('model',r['policy']); m,c=batch_posterior(obs,model)
        mu=offset+f@m; cov=f@c@f.T; selected=int(np.argmax(mu)); final=finals[key]
        np.testing.assert_allclose(final.get('target_mean',final.get('target_posterior_mean')),mu,atol=2e-9)
        np.testing.assert_allclose(final.get('target_covariance',final.get('target_posterior_covariance')),cov,atol=2e-9)
        assert final.get('selected_id')==design[selected]['id']
        assert final['observations_sha256']==sha(obs)
        initial_key=key[:2]; init_hash=sha(obs[:4])
        assert initial.setdefault(initial_key,init_hash)==init_hash
        theta=rng('truth',r['scenario'],r['instance']).normal(size=6)*PRIOR
        if r['scenario']!='cubic_discrepancy': theta[5]=0.
        amp=float(rng('outside',r['instance']).normal(0,1.5)) if r['scenario']=='outside_model_sinusoid' else 0.
        truth=offset+f@theta+amp*np.sin(2*np.pi*np.array([d['x'] for d in design]))
        np.testing.assert_allclose(theta,r['truth_theta'],atol=1e-12)
        assert abs(r['simple_regret']-(truth.max()-truth[selected]))<1e-9
        for o in obs:
            expected=o['offset']+np.asarray(o['h'])@theta
            if o['kind']=='target': expected=truth[int(o['candidate_id'][1:])]
            expected+=rng('observation',r['scenario'],r['instance'],o['id']).normal(0,o['noise_sd'])
            assert abs(o['value']-expected)<1e-9
        reads=truth[selected]+rng('final_confirmation',r['scenario'],r['instance'],design[selected]['id']).normal(0,.2,3)
        assert abs(r['confirmation_mean']-reads.mean())<1e-9
        if not old: np.testing.assert_allclose(reads,r['confirmation_reads'],atol=1e-12)
        spent=sum(o['cost'] for o in obs)+1.6
        assert abs(spent-r['spent'])<1e-9 and spent<=r['budget']+1e-9
        rows=decisions.get(key,[]); assert len(rows)==len(obs)-4
        for step,d in enumerate(rows):
            history=obs[:4+step]; mm,cc=batch_posterior(history,model)
            max_mean=max(max_mean,float(np.max(np.abs(mm-d['posterior_mean']))))
            max_cov=max(max_cov,float(np.max(np.abs(cc-d['posterior_covariance']))))
            np.testing.assert_allclose(mm,d['posterior_mean'],atol=2e-9)
            np.testing.assert_allclose(cc,d['posterior_covariance'],atol=2e-9)
            assert d['observations_sha256']==sha(history)
            fee_before=sum(o['cost'] for o in history)
            pool=pool_for(design,history,r['budget']-1.6-fee_before)
            assert d['available_actions_sha256']==sha(pool)
            chosen=d.get('action',d.get('selected_action'))
            assert chosen['id']==obs[4+step]['id']
            if args.check_scores and not old and r['criterion']!='gh31':
                h=np.array([a['h'] for a in pool]); cross=cc@h.T
                vy=np.einsum('ij,ji->i',h,cross)+np.array([a['noise_sd']**2 for a in pool])
                slopes=(f@cross)/np.sqrt(vy)
                mu0=offset+f@mm
                if r['criterion']=='kg':
                    values=np.array([crossing_integral(mu0,slopes[:,j]) for j in range(len(pool))])
                elif r['criterion']=='contrast_variance':
                    values=np.sum((slopes-slopes.mean(axis=0))**2,axis=0)
                else:
                    from scipy.stats import norm
                    sig=np.sqrt(np.maximum(np.diag(f@cc@f.T),1e-12)); difference=mu0-mu0.max(); z=difference/sig
                    ei=difference*norm.cdf(z)+sig*norm.pdf(z)
                    values=np.array([ei[int(a['candidate_id'][1:])] if a['kind']=='target' else 0. for a in pool])
                values/=np.array([a['cost'] for a in pool])
                ix=next(i for i,a in enumerate(pool) if a['id']==chosen['id'])
                difference=abs(values[ix]-d['score']); max_kg=max(max_kg,float(difference))
                assert difference<2e-8
                assert values[ix]>=values.max()-2e-8
                near_ties+=int(ix!=int(np.argmax(values)))
                checked_scores+=1
    receipt={'status':'PASS','experiment_implementation_imported':False,'campaigns':len(records),
             'independent_scenario_instances':len(initial),'adaptive_records':sum(map(len,decisions.values())),
             'terminal_records':len(finals),'batch_posterior_max_mean_error':max_mean,
             'batch_posterior_max_covariance_error':max_cov,'independently_scored_actions':checked_scores,
             'independent_score_max_error':max_kg,'score_equivalent_argmax_ties':near_ties,
             'kg_reference':'All pairwise crossings; exact segment normal integrals on [-12,12], omitted tails negligible for these scales',
             'old_confirmation_reads':'regenerated, not originally persisted' if old else 'all three raw reads verified',
             'scope':'Numerical/accounting verification only, not novelty or real chemistry'}
    args.output.write_text(json.dumps(receipt,indent=2),encoding='utf-8'); print(json.dumps(receipt))

if __name__=='__main__': main()

"""Original frozen-state quadrature sensitivity, independent batch reconstruction."""
import json
from pathlib import Path
import numpy as np
from numpy.polynomial.hermite import hermgauss
from scipy.integrate import quad
from scipy.stats import norm
from user_tools.workbench.action_study_verify import design_for,pool_for,crossing_integral
from user_tools.workbench.action_study_numerics import normal_envelope_gain
from user_tools.workbench.action_validation import write_csv


def main():
    source=Path('outputs/analysis/action_validation_20261014_v3')
    out=Path('outputs/analysis/action_study_20261015/numerical'); out.mkdir(exist_ok=False)
    data=json.loads((source/'result.json').read_text()); campaigns={(r['scenario'],r['instance'],r['policy']):r for r in data['campaigns']}
    nodes={n:hermgauss(n) for n in [31,63,127]}; rows=[]; quad_checks=[]
    for k,d in enumerate(map(json.loads,(source/'decisions.jsonl').read_text().splitlines())):
        if not d['policy'].endswith('cost_kg'): continue
        case=campaigns[d['scenario'],d['instance'],d['policy']]
        history=case['observations'][:4+d['step']]; design=design_for(d['scenario'])
        pool=pool_for(design,history,10-1.6-d['spent_before'])
        f=np.array([r['target_h'] for r in design]); offset=np.array([r['offset'] for r in design])
        m=np.array(d['posterior_mean']); c=np.array(d['posterior_covariance'])
        h=np.array([a['h'] for a in pool]); cross=c@h.T
        vy=np.einsum('ij,ji->i',h,cross)+np.array([a['noise_sd']**2 for a in pool])
        slopes=f@cross/np.sqrt(vy); mu=offset+f@m; costs=np.array([a['cost'] for a in pool])
        exact=np.array([normal_envelope_gain(mu,slopes[:,i]) for i in range(len(pool))])/costs
        reference=np.array([crossing_integral(mu,slopes[:,i]) for i in range(len(pool))])/costs
        np.testing.assert_allclose(exact,reference,atol=2e-10)
        exact_ix=int(np.argmax(exact)); record={'scenario':d['scenario'],'instance':d['instance'],
            'policy':d['policy'],'step':d['step'],'actions':len(pool),'exact_id':pool[exact_ix]['id'],
            'independent_crossing_max_error':float(abs(exact-reference).max())}
        for n,(z,w) in nodes.items():
            future=mu[None,None,:]+np.sqrt(2)*z[:,None,None]*slopes.T[None,:,:]
            score=np.maximum(w@future.max(axis=2)/np.sqrt(np.pi)-mu.max(),0)/costs
            ix=int(np.argmax(score)); chosen=ix if score[ix]>1e-12 else None
            exact_chosen=exact_ix if exact[exact_ix]>1e-12 else None
            record[f'gh{n}_max_error']=float(abs(score-exact).max())
            record[f'gh{n}_different_action']=chosen!=exact_chosen
            record[f'gh{n}_exact_loss']=float(max(exact)-exact[ix]) if chosen is not None else float(max(exact))
        if len(quad_checks)<35 and k%61==0:
            a=mu-mu.max(); b=slopes[:,exact_ix]-slopes[0,exact_ix]
            points=sorted({float((a[j]-a[i])/(b[i]-b[j])) for i in range(13) for j in range(i)
                           if b[i]!=b[j] and -12<(a[j]-a[i])/(b[i]-b[j])<12})
            integral,err=quad(lambda z:np.max(a+b*z)*norm.pdf(z),-12,12,points=points,
                              epsabs=1e-11,epsrel=1e-11,limit=250)
            value=normal_envelope_gain(mu,slopes[:,exact_ix])
            assert abs(value-integral)<2e-9
            quad_checks.append({'record':k,'absolute_error':float(abs(value-integral)),
                                'quadrature_error_estimate':float(err)})
        rows.append(record)
    write_csv(out/'frozen_state_comparison.csv',rows)
    summary={'states':len(rows),'all_available_action_scores_crosschecked':sum(r['actions'] for r in rows),
        'independent_crossing_max_error':max(r['independent_crossing_max_error'] for r in rows),
        'scipy_quad_checks':quad_checks,'tail_truncation':'[-12,12]; Gaussian tails negligible at observed scales',
        'counts':{str(n):{'different_actions':sum(r[f'gh{n}_different_action'] for r in rows),
            'max_score_error':max(r[f'gh{n}_max_error'] for r in rows),
            'max_exact_acquisition_loss':max(r[f'gh{n}_exact_loss'] for r in rows)} for n in nodes},
        'scope':'Frozen-state numerical diagnostics; full-campaign path comparison is separate on development instances'}
    (out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8'); print(json.dumps(summary))
if __name__=='__main__': main()

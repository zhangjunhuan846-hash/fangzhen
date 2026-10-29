"""Resolve QUADPACK warnings from nearly coincident inactive line crossings."""
import json
from pathlib import Path
import warnings
import numpy as np
from scipy.integrate import quad,IntegrationWarning
from scipy.stats import norm
from user_tools.workbench.action_study_verify import design_for,pool_for
from user_tools.workbench.action_study_numerics import normal_envelope_gain

def main():
    root=Path('outputs/analysis/action_study_20261015')
    original=Path('outputs/analysis/action_validation_20261014_v3')
    summary=json.loads((root/'numerical/summary.json').read_text())
    decisions=list(map(json.loads,(original/'decisions.jsonl').read_text().splitlines()))
    campaigns={(r['scenario'],r['instance'],r['policy']):r for r in json.loads((original/'result.json').read_text())['campaigns']}
    checks=[]
    for entry in summary['scipy_quad_checks']:
        d=decisions[entry['record']]; r=campaigns[d['scenario'],d['instance'],d['policy']]
        design=design_for(d['scenario']); pool=pool_for(design,r['observations'][:4+d['step']],10-1.6-d['spent_before'])
        f=np.array([v['target_h'] for v in design]); mu=np.array([v['offset'] for v in design])+f@np.array(d['posterior_mean'])
        c=np.array(d['posterior_covariance']); h=np.array([v['h'] for v in pool]); cross=c@h.T
        vy=np.einsum('ij,ji->i',h,cross)+np.array([v['noise_sd']**2 for v in pool]); slopes=f@cross/np.sqrt(vy)
        values=np.array([normal_envelope_gain(mu,slopes[:,i]) for i in range(len(pool))])/np.array([v['cost'] for v in pool])
        ix=int(np.argmax(values)); a=mu-mu.max(); b=slopes[:,ix]-slopes[0,ix]
        points=sorted({float((a[j]-a[i])/(b[i]-b[j])) for i in range(13) for j in range(i)
                       if b[i]!=b[j] and -12<(a[j]-a[i])/(b[i]-b[j])<12})
        cuts=[-12.]
        for point in points:
            if point-cuts[-1]>1e-8 and 12-point>1e-8: cuts.append(point)
        cuts.append(12.)
        total=error=0.
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always',IntegrationWarning)
            for left,right in zip(cuts[:-1],cuts[1:]):
                val,err=quad(lambda z:np.max(a+b*z)*norm.pdf(z),left,right,epsabs=1e-12,epsrel=1e-12)
                total+=val; error+=err
        exact=normal_envelope_gain(mu,slopes[:,ix])
        assert abs(total-exact)<2e-10 and error<2e-10
        checks.append({'record':entry['record'],'absolute_error':abs(total-exact),'summed_error_estimate':error,
                       'warnings':[str(w.message) for w in caught]})
    result={'status':'PASS','checks':checks,'max_absolute_error':max(r['absolute_error'] for r in checks),
        'warning_count':sum(len(r['warnings']) for r in checks),
        'method':'Independent adaptive integration split at separated all-pair crossings; near-coincident cuts merged at 1e-8. Original warning retained in numerical/summary.json.'}
    (root/'numerical/quad_refinement.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
if __name__=='__main__': main()

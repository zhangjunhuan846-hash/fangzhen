"""Predeclared contrasts, stratified paired bootstrap and report inputs."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from scipy.stats import t
from user_tools.workbench.action_validation import SCENARIOS,write_csv

COMPARISONS={
 'primary_kg_vs_variance':{'full__kg':1.,'full__contrast_variance':-1.},
 'secondary_kg_vs_ei':{'full__kg':1.,'full__ei':-1.},
 'radius_effect_kg':{'full__kg':1.,'fixed_radius__kg':-1.},
 'radius_effect_variance':{'full__contrast_variance':1.,'fixed_radius__contrast_variance':-1.},
 'discrepancy_effect_kg':{'full__kg':1.,'no_discrepancy__kg':-1.},
 'discrepancy_effect_variance':{'full__contrast_variance':1.,'no_discrepancy__contrast_variance':-1.},
 'radius_interaction':{'full__kg':1.,'fixed_radius__kg':-1.,'full__contrast_variance':-1.,'fixed_radius__contrast_variance':1.},
 'discrepancy_interaction':{'full__kg':1.,'no_discrepancy__kg':-1.,'full__contrast_variance':-1.,'no_discrepancy__contrast_variance':1.}}


def cells(records):
    return {(s,p):sorted([r for r in records if r['scenario']==s and r['policy']==p],key=lambda r:r['instance'])
            for s in SCENARIOS for p in sorted({r['policy'] for r in records})}


def differences(grouped,coefficients):
    return [sum(weight*np.array([r['simple_regret'] for r in grouped[s,p]])
                for p,weight in coefficients.items()) for s in SCENARIOS]


def statistics(delta,bootstrap_seed=20261015):
    rng=np.random.default_rng(bootstrap_seed)
    samples=sum(rng.choice(d,size=(10000,len(d)),replace=True).mean(axis=1)/len(delta) for d in delta)
    value=float(np.mean([d.mean() for d in delta]))
    variances=np.array([np.var(d,ddof=1)/len(d)/len(delta)**2 for d in delta])
    se=float(np.sqrt(variances.sum()))
    df=float(variances.sum()**2/sum(v*v/(len(d)-1) for v,d in zip(variances,delta))) if se else 1e9
    pvalue=float(2*t.sf(abs(value)/se,df)) if se else (1. if value==0 else 0.)
    flat=np.concatenate(delta)
    return {'mean_difference':value,'bootstrap_95_lower':float(np.quantile(samples,.025)),
        'bootstrap_95_upper':float(np.quantile(samples,.975)),'stratified_standard_error':se,
        'satterthwaite_df':df,'two_sided_approximate_p':pvalue,'median_difference':float(np.median(flat)),
        'wins':int((flat < -1e-9).sum()),'ties':int((abs(flat)<=1e-9).sum()),'losses':int((flat>1e-9).sum()),
        'maximum_absolute_instance_difference':float(abs(flat).max()),
        'leave_one_out_max_mean_change':float(max(abs(d-d.mean()).max()/((len(d)-1)*len(delta)) for d in delta))}


def analyse(root):
    payload=json.loads((root/'result.json').read_text()); grouped=cells(payload['campaigns'])
    rows=[]
    for (s,p),rs in grouped.items():
        rows.append({'scenario':s,'policy':p,'instances':len(rs),
            **{k+'_mean':float(np.mean([r[k] for r in rs])) for k in ['simple_regret','spent','unused_budget','exact_best',
                'within_0p5','interval_fraction','confirmation_interval_hit','radius_characterization_adaptive_cost']},
            'regret_median':float(np.median([r['simple_regret'] for r in rs])),
            'regret_90pct':float(np.quantile([r['simple_regret'] for r in rs],.9))})
    comparisons=[]
    for name,coefs in COMPARISONS.items():
        delta=differences(grouped,coefs)
        summary={'comparison':name,'scope':'equal_weight_five_fixed_scenarios',**statistics(delta)}
        comparisons.append(summary)
    # One primary comparison; seven secondary tests form one Holm family.
    secondary=comparisons[1:]; ordered=sorted(secondary,key=lambda r:r['two_sided_approximate_p'])
    adjusted=0.
    for i,r in enumerate(ordered):
        adjusted=max(adjusted,min(1.,(len(ordered)-i)*r['two_sided_approximate_p']))
        r['holm_adjusted_p']=adjusted
        r['secondary_supported']=bool(adjusted<.05 and (r['bootstrap_95_upper']<0 or r['bootstrap_95_lower']>0))
    primary=comparisons[0]; primary['minimum_effect']=.01
    primary['primary_success']=bool(primary['bootstrap_95_upper']<-.01)
    primary['statistical_improvement']=bool(primary['bootstrap_95_upper']<0)
    scenario_rows=[]
    for name,coefficients in COMPARISONS.items():
        for s,delta in zip(SCENARIOS,differences(grouped,coefficients)):
            scenario_rows.append({'comparison':name,'scenario':s,**statistics([delta])})
    write_csv(root/'summary.csv',rows); write_csv(root/'contrasts.csv',comparisons)
    write_csv(root/'scenario_contrasts_exploratory.csv',scenario_rows)
    result={'summary':rows,'contrasts':comparisons,'scenario_contrasts_exploratory':scenario_rows,
            'primary_hypothesis':'KG minus contrast-variance mean simple regret across five equal-weight fixed scenarios < -0.01',
            'scope':'dimensionless synthetic utility; no real cost or material claim; intervals are bootstrap approximations'}
    (root/'analysis.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result


def freeze(development,output):
    data=json.loads((development/'result.json').read_text()); g=cells(data['campaigns'])
    delta=differences(g,COMPARISONS['primary_kg_vs_variance'])
    # N selected from development variance for a .03 pooled CI half-width,
    # capped at 160 per scenario; no optional stopping or validation peeking.
    n_required=int(np.ceil(1.96**2*sum(np.var(d,ddof=1) for d in delta)/(25*.03**2)))
    n=next((n for n in [40,80,160] if n>=n_required),160)
    files=['user_tools/workbench/action_study.py','user_tools/workbench/action_study_numerics.py',
           'user_tools/workbench/action_validation.py','user_tools/workbench/action_study_analysis.py',
           'user_tools/workbench/action_study_verify.py','tests/test_action_study.py',
           'docs/action_study_20261015_method.md',
           'refine-logs/action_study_20261015/EXPERIMENT_PLAN.md']
    from user_tools.workbench.action_study import POLICIES
    from datetime import datetime,timezone
    protocol={'split':'validation','date':'2026-10-15','frozen_at_utc':datetime.now(timezone.utc).isoformat(),
        'first_instance':20000,'instances_per_scenario':n,
        'scenarios':list(SCENARIOS),'policies':list(POLICIES),'budget':10.,'confirmation_fee':1.6,
        'minimum_primary_effect':.01,'effect_rationale':'1% of the declared unit prior slope SD; numerical study threshold, not material relevance',
        'primary_comparison':'primary_kg_vs_variance','scenario_weights':[.2]*5,
        'independent_unit':'scenario, instance; seven methods are paired measurements, not independent replicates',
        'development_instances':'1000-1039 in all five existing worlds; old smoke 0-1 also development',
        'n_precision_target_halfwidth':.03,'n_required_by_development_variance':n_required,
        'n_allowed':[40,80,160],'n_cap':160,'n_rule':'smallest allowed N >= requirement, else cap and disclose imprecision',
        'bootstrap_replicates':10000,'bootstrap_seed':20261015,
        'primary_success':'two-sided stratified paired percentile-bootstrap 95% upper bound < -0.01',
        'secondary_multiplicity':'seven predeclared secondary contrasts, approximate stratified t p-values, Holm FWER .05; require bootstrap CI also excludes zero',
        'adaptive_stopping':'all criteria stop at <=1e-12 or no affordable allowed action; confirmation always reserved',
        'cost_scope':'relative mock units; no actual cost-reduction claim',
        'failure_policy':'stop on numerical exception, preserve output, never omit a failed episode to improve a result',
        'comparisons':COMPARISONS,'source_hashes':{f:hashlib.sha256(Path(f).read_bytes()).hexdigest() for f in files},
        'development_result_sha256':hashlib.sha256((development/'result.json').read_bytes()).hexdigest(),
        'evidence_type':'simulation_only','original_algorithm_claim':False,'external_human_validation':False,
        'library_crosscheck':'No torch/gpytorch/botorch installed; no large dependency installation. Independent batch conditioning and crossing integration used; author source examined, not executed.'}
    if output.exists(): raise FileExistsError('Freeze cannot be overwritten')
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(protocol,indent=2),encoding='utf-8')
    print(json.dumps({'frozen_protocol':str(output),'N_required':n_required,'N_selected':n}))


def main():
    p=argparse.ArgumentParser(); p.add_argument('directory',type=Path); p.add_argument('--freeze',type=Path)
    args=p.parse_args()
    if args.freeze: freeze(args.directory,args.freeze)
    else:
        result=analyse(args.directory); print(json.dumps(result['contrasts'][0]))

if __name__=='__main__': main()

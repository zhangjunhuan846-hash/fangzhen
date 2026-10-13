"""Read-only graphite workbook audit and finite historical replay.

No Alchemite scripts are executed. Raw files and cached source values remain intact.
The pilot uses ASC only: explicit ToC links and sheet-labelled calendering states.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
import numpy as np
import openpyxl
from scipy.stats import norm
from .optimization import GaussianProcess


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def write_csv(path, rows):
    if not rows:
        return
    keys=list(dict.fromkeys(k for r in rows for k in r))
    with Path(path).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)


def inventory(root):
    result=[]
    for p in sorted(root.rglob('*.xlsx')):
        if 'Cell_Data' not in p.name and 'results-live' not in p.name.lower():
            continue
        item={'file':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
        try:
            w=openpyxl.load_workbook(p,read_only=True,data_only=True)
            item['status']='readable'
            item['sheets']=[{'name':s.title,'declared_rows':s.max_row,'declared_columns':s.max_column} for s in w]
            w.close()
        except Exception as exc:
            item.update(status='unreadable',error=f'{type(exc).__name__}: {exc}')
        result.append(item)
    return result


def read_asc(root):
    summary=next(root.rglob('ASC-Cell_Data-Azar-Stavros.xlsx'))
    detail=next(root.rglob('ASC results-live.xlsx'))
    w=openpyxl.load_workbook(detail,read_only=True,data_only=True)
    links={};states={};warnings=[]
    for row in w['ToC'].iter_rows(values_only=True):
        sample=re.sub(r'\s+','',str(row[0]))
        for cid in row[2:]:
            if isinstance(cid,str) and re.fullmatch(r'ASC-\d+',cid):
                if cid in links:raise ValueError('duplicate ToC ID')
                links[cid]=sample
    for sheet in w:
        if sheet.title=='ToC':continue
        sample=re.sub(r'\s+','',sheet.title);state=None
        for row in sheet.iter_rows(values_only=True):
            label=str(row[0]).strip().lower()
            if label=='calendaring':state=1
            elif label=='non calendared':state=0
            if len(row)>2 and isinstance(row[1],str) and re.fullmatch(r'ASC-\d+',row[1]) and row[2]=='Anode':
                cid=row[1]
                if state is None or links.get(cid)!=sample:raise ValueError('ambiguous cell state/link')
                if cid in states:raise ValueError('duplicate state ID')
                states[cid]=state
    w.close()
    w=openpyxl.load_workbook(summary,read_only=True,data_only=True)
    headers=list(w.active.iter_rows(max_row=2,max_col=44,values_only=True))
    norm=lambda value:re.sub(r'\s+','',str(value)).lower()
    if norm(headers[0][1])!='cellid' or norm(headers[1][8])!='activemass(mg)' or norm(headers[1][35])!='d5(ma.h)':
        raise ValueError('ASC关键表头或质量/容量单位发生变化，不能使用固定列映射。')
    cells=[];sample_inputs={};case=None
    for rownum,row in enumerate(w.active.iter_rows(max_col=44,values_only=True),1):
        cid=row[1]
        if not isinstance(cid,str) or not re.fullmatch(r'ASC-\d+',cid):continue
        if row[0] is not None:case=str(row[0])
        if cid not in links or cid not in states:raise ValueError('missing explicit ToC/state')
        sample=links[cid]
        # Process entries printed once per Sample block, not inferred across samples.
        if row[11] is not None:
            declared=re.sub(r'\s+','',str(row[11]))
            if declared!=sample:raise ValueError('INK and ToC disagree')
            sample_inputs[sample]={'drying_temperature_label':str(row[12]),'coating_speed_m_min':row[13],
                                   'coating_gap_um':row[14]}
        inputs=sample_inputs.get(sample,{})
        composition=list(row[16:20]);mass=row[8];d5=row[35]
        reasons=[]
        if not number(mass) or mass<=0:reasons.append('invalid_active_mass')
        if not number(d5) or d5<=0:reasons.append('D5_missing_or_nonpositive')
        if not all(number(x) for x in composition):reasons.append('composition_missing')
        elif abs(sum(composition)-100)>.1:reasons.append('composition_sum_not_100')
        if not inputs or not all(number(inputs.get(k)) for k in ['coating_speed_m_min','coating_gap_um']):reasons.append('process_missing')
        q=1000*d5/mass if number(mass) and mass>0 and number(d5) else None
        if q is not None and q>450:warnings.append({'cell_id':cid,'issue':'D5_specific_above_450_review_only','value':q})
        cells.append({'cell_id':cid,'sample_id':sample,'case_id':case,'calendered':states[cid],
                      'source_row':rownum,'source_file':summary.name,**inputs,
                      'graphite_dry_pct':composition[0],'carbon_dry_pct':composition[1],
                      'cmc_dry_pct':composition[2],'sbr_dry_pct':composition[3],
                      'active_mass_mg':mass,'D5_mAh':d5,'D5_specific_mAh_g':q,
                      'eligible':not reasons,'exclusion_reason':';'.join(reasons)})
    w.close()
    if len({r['cell_id'] for r in cells})!=len(cells):raise ValueError('duplicate cell summary IDs')
    groups=defaultdict(list)
    for r in cells:groups[(r['sample_id'],r['calendered'])].append(r)
    conditions=[]
    for (sample,state),rows in sorted(groups.items()):
        good=[r for r in rows if r['eligible']]
        base=rows[0]
        # All replicate inputs must match, including dry composition.
        keys=['drying_temperature_label','coating_speed_m_min','coating_gap_um',
              'graphite_dry_pct','carbon_dry_pct','cmc_dry_pct','sbr_dry_pct']
        for k in keys:
            vals=[r.get(k) for r in rows]
            if number(vals[0]):
                if not all(number(v) and abs(v-vals[0])<1e-7 for v in vals):raise ValueError('replicate input mismatch '+k)
            elif len(set(vals))!=1:raise ValueError('replicate input mismatch '+k)
        ys=[r['D5_specific_mAh_g'] for r in good]
        conditions.append({'candidate_id':f'{sample}_cal{state}','sample_id':sample,'calendered':state,
                           **{k:base.get(k) for k in keys},'cell_count':len(rows),'usable_cell_count':len(good),
                           'cell_ids':';'.join(r['cell_id'] for r in rows),
                           'D5_mean_mAh_g':float(np.mean(ys)) if ys else None,
                           'D5_sd_mAh_g':float(np.std(ys,ddof=1)) if len(ys)>1 else None,
                           'eligible':len(good)>=2})
    return cells,conditions,warnings


def features(rows,fit_indices=None):
    # Only declared fabrication settings and actual dry composition. No adhesion,
    # porosity, active mass, capacity or cycling-derived values in GP predictors.
    numeric=['coating_speed_m_min','coating_gap_um','graphite_dry_pct','carbon_dry_pct',
             'cmc_dry_pct','sbr_dry_pct','calendered']
    fitting=rows if fit_indices is None else [rows[i] for i in fit_indices]
    labels=sorted({r['drying_temperature_label'] for r in fitting})
    x=np.array([[float(r[k]) for k in numeric]+[float(r['drying_temperature_label']==s) for s in labels] for r in rows])
    fitting_x=x if fit_indices is None else x[fit_indices]
    lo=fitting_x.min(axis=0);span=fitting_x.max(axis=0)-lo
    active=span>1e-10
    return ((x[:,active]-lo[active])/span[active]),[k for k,a in zip(numeric+['temperature='+s for s in labels],active) if a]


def select_next(observed_x,observed_y,candidate_x,*,strategy,seed,noise):
    """Selection has no access to unobserved outcome labels."""
    if strategy=='random':return int(np.random.default_rng(seed).integers(len(candidate_x)))
    if strategy=='spacefill':
        return int(np.argmax(np.sqrt(((candidate_x[:,None]-observed_x[None])**2).sum(axis=2)).min(axis=1)))
    model=GaussianProcess().fit(observed_x,observed_y,noise)
    mu,sd=model.predict(candidate_x);incumbent=float(model.predict(observed_x)[0].max())
    improvement=mu-incumbent;z=improvement/sd
    return int(np.argmax(improvement*norm.cdf(z)+sd*norm.pdf(z)))


def replay(rows,out,seeds=10,budget=15,noise=10.):
    usable=[r for r in rows if r['eligible']]
    x,names=features(usable);y=np.array([r['D5_mean_mAh_g'] for r in usable])
    if not 5<budget<=len(usable):raise ValueError('budget outside measured candidate space')
    campaigns=[];history=[]
    for seed in range(seeds):
        initial=list(map(int,np.random.default_rng(seed).choice(len(usable),5,replace=False)))
        for strategy in ['random','spacefill','bo']:
            used=initial.copy()
            for step in range(budget-5):
                available=[i for i in range(len(usable)) if i not in used]
                pick=available[select_next(x[used],y[used],x[available],strategy=strategy,seed=seed*1000+step,noise=noise)]
                record={'seed':seed,'strategy':strategy,'round':step+1,
                        'candidate_id':usable[pick]['candidate_id'],
                        'training_ids':[usable[i]['candidate_id'] for i in used],
                        'observed_best_before':float(y[used].max())}
                # Persist recommendation before revealing historical measurement.
                folder=out/f'noise_{noise:g}'/f'{strategy}_{seed}';folder.mkdir(parents=True,exist_ok=True)
                (folder/f'suggestion_{step+1:02d}.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
                record['revealed_D5_mean_mAh_g']=float(y[pick]);history.append(record);used.append(pick)
            campaigns.append({'seed':seed,'strategy':strategy,'noise_assumption_mAh_g':noise,
                              'initial_ids':';'.join(usable[i]['candidate_id'] for i in initial),
                              'budget':budget,'best_observed_mAh_g':float(y[used].max()),
                              'historical_regret_mAh_g':float(y.max()-y[used].max()),
                              'optimum_found':bool(y[used].max()==y.max())})
    # Leave entire Sample (both calendering states) out: no cell-level split leakage.
    validation=[]
    for sample in sorted({r['sample_id'] for r in usable}):
        test=[i for i,r in enumerate(usable) if r['sample_id']==sample]
        train=[i for i,r in enumerate(usable) if r['sample_id']!=sample]
        fold_x,_=features(usable,train)
        gp=GaussianProcess().fit(fold_x[train],y[train],noise);mu,sd=gp.predict(fold_x[test])
        for i,m,s in zip(test,mu,sd):
            predictive_sd=math.sqrt(s*s+noise*noise)
            validation.append({'candidate_id':usable[i]['candidate_id'],'sample_id':sample,
                               'actual':float(y[i]),'prediction':float(m),'conditional_prediction_sd':predictive_sd,
                               'error':float(m-y[i]),'covered_95':bool(abs(m-y[i])<=1.96*predictive_sd)})
    assert all(r['candidate_id'] not in r['training_ids'] for r in history)
    write_csv(out/f'campaigns_noise_{noise:g}.csv',campaigns)
    write_csv(out/f'grouped_validation_noise_{noise:g}.csv',validation)
    (out/f'history_noise_{noise:g}.json').write_text(json.dumps(history,indent=2),encoding='utf-8')
    return {'candidate_count':len(usable),'features':names,'noise_assumption_mAh_g':noise,
            'optimum_historical_mean':float(y.max()),'optimum_id':usable[int(np.argmax(y))]['candidate_id'],
            'strategies':{s:{'mean_best':float(np.mean([r['best_observed_mAh_g'] for r in campaigns if r['strategy']==s])),
                             'mean_regret':float(np.mean([r['historical_regret_mAh_g'] for r in campaigns if r['strategy']==s])),
                             'optimum_hits':sum(r['optimum_found'] for r in campaigns if r['strategy']==s)} for s in ['random','spacefill','bo']},
            'grouped_validation_rmse':float(np.sqrt(np.mean([r['error']**2 for r in validation]))),
            'grouped_validation_95_coverage':float(np.mean([r['covered_95'] for r in validation])),
            'campaigns':len(campaigns),'suggestions':len(history)}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=False)
    inv=inventory(args.root);cells,conditions,warnings=read_asc(args.root)
    write_csv(args.out/'cells.csv',cells);write_csv(args.out/'conditions.csv',conditions)
    write_csv(args.out/'review_flags.csv',warnings)
    results=[replay(conditions,args.out,noise=n) for n in [5.,10.,20.]]
    report={'scope':'ASC pilot; AS not merged; D5 column is cycle-labelled, NOT a verified 1C target',
            'source_inventory':inv,'cell_count':len(cells),'sample_count':len({r['sample_id'] for r in cells}),
            'condition_count':len(conditions),'excluded_cells':sum(not r['eligible'] for r in cells),
            'exclusion_counts':dict(Counter(r['exclusion_reason'] for r in cells if not r['eligible'])),
            'readable_source_caches':'Source formula caches used, D5 specific recomputed from mass; not raw curve validation',
            'replay_results':results,'limitations':['finite historical replay, not prospective regeneration',
             'eligible candidate population conditioned on available labels; failed/missing tests are not predicted',
             'spacefill is maximin, not a reconstructed original DOE',
             'actual dry composition is observed fabrication input, not guaranteed pre-experiment setpoint',
             'GP observation noise is an explicit sensitivity assumption, not calibrated',
             'replicate SD and unavailable cycling protocols require follow-up before scientific claims']}
    (args.out/'audit_and_replay.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ['source_inventory']},ensure_ascii=False,indent=2))


if __name__=='__main__':main()

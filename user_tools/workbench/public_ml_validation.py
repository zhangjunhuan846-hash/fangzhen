"""Real graphite data replay with evaluator-owned, unrevealed labels."""
import hashlib
import json
from pathlib import Path
import numpy as np
from user_tools.rg_loop.public_graphite import read_asc,features,inventory
from user_tools.workbench.ml_worker import train,fit_bundle,predict_bundle,write_csv

def run_public(config,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    root=Path(__file__).resolve().parents[2]/'data/external/graphite_manufacturing_4dh2h3tsf4_v1/extracted'
    cells,conditions,flags=read_asc(root);usable=[r for r in conditions if r['eligible']]
    write_csv(out/'cell_quality_audit.csv',cells);write_csv(out/'condition_quality_audit.csv',conditions)
    numeric=['coating_speed_m_min','coating_gap_um','graphite_dry_pct','carbon_dry_pct','cmc_dry_pct','sbr_dry_pct','calendered']
    names=numeric+['drying_temperature_label']
    fields=[{'key':k,'label':k,'kind':'numeric' if k in numeric else 'categorical','stage':'process'} for k in names]
    rows=[{'record_id':r['candidate_id'],'group_id':r['sample_id'],'batch_id':'public_ASC','target':float(r['D5_mean_mAh_g']),
           **{k:r[k] for k in names}} for r in usable]
    dataset={'rows':rows,'fields':fields,'target':'D5_specific_mAh_g','source':'public_graphite_ASC',
             'exclusions':[{'cell_id':r['cell_id'],'reason':r['exclusion_reason']} for r in cells if not r['eligible']]+flags,
             'group_basis':'同一INK的辊压/未辊压条件同组留出'}
    comparison=train(dataset,{'features':names,'purpose':'process','selector':'manual','auto_calibrate':True,'alpha':.1},out/'models')
    x,_=features(usable);seeds=int(config.get('seeds',20));budget=min(int(config.get('budget',12)),len(rows));initial=5
    if not 5<=seeds<=50 or budget<=initial:raise ValueError('公开回放需5–50种子且预算>5。')
    strategies=['random','spacefill','gp_fixed','gp_dynamic'];traces=[];finals={s:[] for s in strategies};fallbacks=[]
    for seed in range(seeds):
        initial_ids=np.random.default_rng(seed).choice(len(rows),initial,replace=False).tolist()
        for strategy in strategies:
            seen=list(initial_ids)
            for step in range(initial,budget+1):
                best=max(rows[i]['target'] for i in seen)
                traces.append({'seed':seed,'strategy':strategy,'observations':len(seen),'best_D5_mAh_g':best})
                if step==budget:break
                hidden=[i for i in range(len(rows)) if i not in seen]
                observed=[dict(rows[i]) for i in seen]
                # Selector sees only these inputs; no outcome labels in candidate rows.
                candidates=[{k:v for k,v in rows[i].items() if k!='target'} for i in hidden]
                rng=np.random.default_rng(seed*101+step)
                if strategy=='random':choice=int(rng.integers(len(hidden)))
                elif strategy=='spacefill':choice=int(np.argmax(np.linalg.norm(x[hidden,None]-x[None,seen],axis=2).min(axis=1)))
                else:
                    try:
                        cfg={'features':names,'selector':'spearman' if strategy=='gp_dynamic' else 'manual','top_k':3}
                        gp=fit_bundle(observed,fields,cfg,'gp');mu,sd=predict_bundle(gp,candidates,std=True)
                        # UCB explores using only current observations, not true candidate labels.
                        choice=int(np.argmax(mu+2*sd))
                    except Exception as e:
                        choice=int(rng.integers(len(hidden)));fallbacks.append({'seed':seed,'step':step,'strategy':strategy,'reason':str(e),'fallback':'random'})
                decision={'seed':seed,'strategy':strategy,'observations_before':len(seen),
                          'observed_ids':[rows[i]['record_id'] for i in seen],
                          'observed_labels':{rows[i]['record_id']:rows[i]['target'] for i in seen},
                          'candidate_payload_sha256':hashlib.sha256(json.dumps(candidates,sort_keys=True).encode()).hexdigest(),
                          'candidate_payload_has_target':any('target' in r for r in candidates),
                          'selected_id':rows[hidden[choice]]['record_id']}
                folder=out/'decisions';folder.mkdir(exist_ok=True)
                (folder/f'{strategy}_{seed}_{step}.json').write_text(json.dumps(decision,allow_nan=False),encoding='utf-8')
                # Only after persisting the decision does the evaluator release GT.
                seen.append(hidden[choice])
            finals[strategy].append(max(rows[i]['target'] for i in seen))
    random=np.array(finals['random']);summary=[]
    for strategy in strategies:
        vals=np.array(finals[strategy]);diff=vals-random
        summary.append({'strategy':strategy,'mean_best_D5_mAh_g':float(vals.mean()),'std_across_seeds':float(vals.std(ddof=1)),
                        'paired_mean_vs_random':float(diff.mean()),'paired_standard_error':float(diff.std(ddof=1)/np.sqrt(seeds)),
                        'seeds_beating_random':int(np.sum(diff>0)),'seeds':seeds})
    result={'evidence_type':'public_descriptor_validation','candidate_count':len(rows),'independent_ink_groups':len({r['group_id'] for r in rows}),
            'model_comparison':comparison,'replay_summary':summary,'traces':traces,'fallbacks':fallbacks,
            'seeds':seeds,'budget':budget,'initial_observations':initial,'source_inventory':inventory(root),
            'cell_count':len(cells),'excluded_cells':sum(not r['eligible'] for r in cells),
            'excluded_conditions':sum(not r['eligible'] for r in conditions),
            'quality_audit_files':['cell_quality_audit.csv','condition_quality_audit.csv'],
            'header_checks':{'cell_id':'Cell Id','active_mass':'Active Mass (mg)','target':'D5 (mA.h)','specific_capacity_conversion':'1000*D5_mAh/active_mass_mg'},
            'scope':'真实公开ASC石墨电极制造数据，D5容量标签尚未核实为1C；不是回收石墨再生收益。模型留出按INK分组；回放限制历史已测条件，评测器持有隐藏标签。固定/动态GP、随机、空间填充同初始条件同预算；重复种子差异仅反映此候选池选点变化，不是新的材料重复实验。未改写旧BO回放结果。'}
    write_csv(out/'replay.csv',traces);write_csv(out/'replay_summary.csv',summary)
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    (out/'ui_result.json').write_text(json.dumps({'result':result,'curves':[]},ensure_ascii=False,allow_nan=False),encoding='utf-8')
    return result

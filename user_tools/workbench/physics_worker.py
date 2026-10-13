"""WSL worker: named actions only, delegates existing science kernels."""
import argparse
import csv
import json
from pathlib import Path


def run(config,out):
    if config['mode']=='battery_agent':
        from user_tools.workbench.battery_agent_worker import run_agent
        return run_agent(config,out)
    if config['mode'] in ['research_multi','research_chain','public_ml_validation','ml_train','ml_predict','ml_recommend']:
        import hashlib
        import user_tools.workbench.ml_worker as ml_module
        # Store exact source hashes with every final artifact, including paper claims.
        modules=['ml_data.py','ml_worker.py','ml_calibration.py','research_data.py','research_worker.py','chain_worker.py','public_ml_validation.py','physics_worker.py']
        provenance={name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest() for name in modules}
        from user_tools.rg_loop import public_graphite
        provenance['rg_loop/public_graphite.py']=hashlib.sha256(Path(public_graphite.__file__).read_bytes()).hexdigest()
        if config['mode']=='research_multi':
            from user_tools.workbench.research_worker import multi_run
            result=multi_run(config['dataset'],config['research_config'],out)
        elif config['mode']=='research_chain':
            from user_tools.workbench.chain_worker import run_chain
            result=run_chain(config['dataset'],config['chain_config'],config['prediction_rows'],out)
        elif config['mode']=='public_ml_validation':
            from user_tools.workbench.public_ml_validation import run_public
            result=run_public(config,out)
        elif config['mode']=='ml_train':result=ml_module.train(config['dataset'],config['ml_config'],out)
        else:result=ml_module.infer(config,out)
        result['code_sha256']=provenance
        result['runtime_versions']={'numpy':ml_module.np.__version__,'pandas':ml_module.pd.__version__,'sklearn':ml_module.sklearn.__version__}
        path=Path(out);(path/'result.json').write_text(json.dumps(result,ensure_ascii=False,allow_nan=False),encoding='utf-8')
        (path/'ui_result.json').write_text(json.dumps({'result':result,'curves':[]},ensure_ascii=False,allow_nan=False),encoding='utf-8')
        return result
    from user_tools.rg_loop.physics import forward_protocol,baseline_task,fit_measured,heldout_prediction,save
    out=Path(out);mode=config['mode'];model=config.get('model','SPM')
    if model not in ['SPM','SPMe','DFN']:raise ValueError('unsupported model')
    if mode=='eis_forward':
        from user_tools.workbench.eis_worker import public_eis
        result=public_eis(config,out);save(out/'result.json',result)
    elif mode=='parquet_preprocess':
        from user_tools.workbench.eis_worker import parquet_recording
        result,curves=parquet_recording(config,out);save(out/'result.json',result)
        save(out/'ui_result.json',{'result':result,'curves':curves});return result
    elif mode=='candidate_multi':
        from user_tools.workbench.candidate_multi import recommend_multi
        result=recommend_multi(config);save(out/'result.json',result)
    elif mode=='sample_forward':
        from user_tools.workbench.sample_forward import run_sample_forward
        result=run_sample_forward(config,out)
    elif mode=='public_replay':
        from user_tools.rg_loop.public_graphite import read_asc,replay,write_csv
        root=Path(__file__).resolve().parents[2]
        cells,conditions,flags=read_asc(root/'data/external/graphite_manufacturing_4dh2h3tsf4_v1/extracted')
        out.mkdir(parents=True,exist_ok=True);write_csv(out/'conditions.csv',conditions)
        result=replay(conditions,out,seeds=10,budget=15,noise=10)
        result.update(evidence_type='public_historical_replay',excluded_cells=sum(not r['eligible'] for r in cells),
                      scope='ASC历史已测候选回放；D5未核实为1C；不是新的再生实验或真实工艺推荐')
        save(out/'result.json',result)
    elif mode=='forward':
        result=forward_protocol(out,parameter_set='Chen2020',model=model,c_rate=float(config.get('c_rate',1)),
                                initial_soc=float(config.get('initial_soc',.9)),temperature_C=float(config.get('temperature_C',25)))
    elif mode=='chen_baseline':result=baseline_task('chen2020','02','C10',model,'Chen2020',out)
    elif mode=='graphite_baseline':result=baseline_task('sintef_graphite','4ccc47','pOCV-deli',model,'Ecker2015_graphite_halfcell',out)
    elif mode=='identify':
        result=fit_measured('chen2020','02','C10',model,out,parameter_set='Chen2020',bounds=(-15.3,-13),sigma_mV=1,maxiter=90,profile_n=21)
    elif mode=='predict':
        fit=json.loads(Path(config['fit_path']).read_text(encoding='utf-8'))
        result=heldout_prediction(fit,'chen2020','02','C2',out)
    else:raise ValueError('unknown mode')
    # Display at most 500 points, preserve all original CSV data on disk.
    curves=[]
    for p in sorted(out.rglob('*.csv')):
        if 'time_aligned' not in p.name and p.name!='forward_curve.csv':continue
        with p.open(encoding='utf-8-sig') as f:
            rows=list(csv.DictReader(f))
        if not rows:continue
        keys=list(rows[0]);tk=next((k for k in keys if k.lower() in ['time_s','t_s','time [s]']),None)
        vk=next((k for k in keys if 'sim' in k.lower() and ('voltage' in k.lower() or k.lower().startswith('v_'))),None)
        ek=next((k for k in keys if ('exp' in k.lower() or 'meas' in k.lower()) and ('voltage' in k.lower() or k.lower().startswith('v_'))),None)
        if not tk or not vk:continue
        points=[]
        for r in rows[::max(1,len(rows)//500)]:
            try:points.append([float(r[tk]),float(r[vk]),float(r[ek]) if ek else None])
            except (ValueError,TypeError):continue
        curves.append({'name':p.name,'points':points})
    save(out/'ui_result.json',{'result':result,'curves':curves[:3]})
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    run(json.loads(Path(a.config).read_text(encoding='utf-8')),a.out)

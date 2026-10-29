"""Score only preselected W8/W5 cycles using frozen models; no refitting."""
from pathlib import Path
import argparse,hashlib,json
import numpy as np
import pandas as pd
from user_tools.workbench.engineering_stanford_frozen import replay_frozen,time_metrics

BASE=Path('outputs/eis_bms_validation')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--cell',choices=('W8','W5'),required=True);args=parser.parse_args()
    folder=BASE/('stanford_w8_new_cycles_20261029' if args.cell=='W8' else 'stanford_w5_diag2_20261029')
    selection=json.loads((folder/'selection.json').read_text(encoding='utf8'))
    modelpath=BASE/'stanford_w8_frozen_20261029/frozen_hppc_model.json' if args.cell=='W8' else folder/'frozen_hppc_model.json'
    code=Path('user_tools/workbench/engineering_stanford_frozen.py')
    if sha(modelpath)!=selection['frozen_model_sha256'] or sha(code)!=selection['replay_code_sha256']:raise ValueError('model or code changed after selection')
    part_records=selection['part_files'] if args.cell=='W8' else selection['parts']
    for rec in part_records:
        if sha(Path(rec['file']))!=rec['sha256']:raise ValueError('selected data changed')
    d=pd.concat([pd.read_csv(r['file']) for r in part_records],ignore_index=True).drop_duplicates('time_s',keep='last')
    if (d.time_s.diff().dropna()<=0).any():raise ValueError('time order invalid')
    model=json.loads(modelpath.read_text(encoding='utf8'));records=selection['baseline_and_selected'] if args.cell=='W8' else [selection['cycle']]
    results=[];sensitivity=[]
    for index,record in enumerate(records,1):
        lo=record['rest']['end_s'];end=record['dynamic']['end_s']
        frame=d[(d.time_s>=lo-1e-7)&(d.time_s<=end+1e-7)].copy()
        if abs(frame.time_s.iloc[0]-lo)>1e-6 or abs(frame.time_s.iloc[-1]-end)>1e-6:raise ValueError('selected endpoints missing')
        trace=replay_frozen(model,frame);dynamic=trace[trace.step==14]
        if len(dynamic)<2:raise ValueError('missing dynamic segment')
        maxgap=float(np.max(np.diff(dynamic.time_s)))
        if maxgap>1.0:raise ValueError(f'dynamic missing samples or gap: {maxgap}s')
        score=time_metrics(dynamic);score.update(cell=args.cell,record=index,selection_role=('partly_observed_development' if args.cell=='W8' and index==1 else 'later_record'),
           start_datetime=record['dynamic']['start_datetime'],end_datetime=record['dynamic']['end_datetime'],
           rest_duration_s=record['rest']['end_s']-record['rest']['start_s'],initial_soc=1.,initial_polarization_V=0.,
           max_sample_gap_s=maxgap,coverage_fraction=1.,number_points=len(dynamic),
           eis_used=False,parameters_source=('same-cell W8 previously frozen' if args.cell=='W8' else 'same-cell W5 HPPC calibration'))
        results.append(score);trace.to_csv(folder/f'{args.cell}_record_{index}_trace.csv.gz',index=False,compression='gzip')
        # Illustrative perturbations, not fitted on voltage and not a quantified uncertainty range.
        for soc,eta in ((1.,0.),(.99,0.),(1.,.005),(1.,-.005)):
            alt=replay_frozen(model,frame,initial_soc=soc,initial_eta_V=eta);s=time_metrics(alt[alt.step==14])
            sensitivity.append({'cell':args.cell,'record':index,'initial_soc':soc,'initial_polarization_V':eta,
               'rmse_mV':s['rmse_mV'],'bias_mV':s['bias_mV'],
               'scope':'illustrative perturbation, not a calibrated uncertainty interval; not used for selecting model'})
        print(json.dumps(score),flush=True)
    pd.DataFrame(results).to_csv(folder/'cycle_metrics.csv',index=False);pd.DataFrame(sensitivity).to_csv(folder/'initialization_sensitivity.csv',index=False)
    (folder/'validation.json').write_text(json.dumps({'records':results,'sensitivity':sensitivity,
       'model_sha256':sha(modelpath),'selection_sha256':sha(folder/'selection.json'),
       'limits':['same-cell cycles are not independent cells or independent experiments',
          'W5 is individually calibrated, not zero-shot transfer','initial SOC and polarization approximate',
          'uncertainty perturbations are illustrative only','EIS not used']},indent=2),encoding='utf8')
if __name__=='__main__':main()

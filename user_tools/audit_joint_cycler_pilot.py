"""Post-run diagnostics, not a retuned validation; all original results retained."""
import hashlib
import json
import shutil
import statistics
from pathlib import Path
from user_tools.validate_joint_cycler_diagnosis import ROOT, OUT, public_records

def main():
    root=ROOT/'data/external/cycler_pipeline_qc_18214281/raw'
    findings={}
    for path in root.glob('*.csv'):
        rows,_=public_records(path);diffs=[];positive=[];zeros=0;total=0
        for a,b in zip(rows,rows[1:]):
            if b['t']<=a['t']:diffs.append(dict(row=len(diffs),a=a,b=b,identical_record=a==b))
            if a['step']!=b['step']:continue
            dq=abs((b['qc']-a['qc'])-(b['qd']-a['qd']))
            if abs(b['i'])>1e-8 and a['i']*b['i']>0:
                total+=1
                if dq==0:zeros+=1
                else:positive.append(dq)
        # Aggregate *within* a stable step; diagnostic only, never used for validation choices.
        groups={}
        for r in rows:groups.setdefault(r['step'],[]).append(r)
        aggregated=[]
        for step,g in groups.items():
            if len(g)<10:continue
            amp=[abs(x['i']) for x in g]
            if min(amp)<=1e-9 or max(amp)-min(amp)>.05*max(amp):continue
            if any(b['t']<=a['t'] for a,b in zip(g,g[1:])):continue
            integral=sum((a['i']+b['i'])*.5*(b['t']-a['t'])/3600 for a,b in zip(g,g[1:]))
            observed=(g[-1]['qc']-g[0]['qc'])-(g[-1]['qd']-g[0]['qd'])
            if abs(observed)>1e-8:aggregated.append(dict(step=step,integral_raw_Ah=integral,counter_delta_Ah=observed,ratio=integral/observed))
        findings[path.name]=dict(nonincreasing_pairs=diffs,active_intervals=total,zero_capacity_increment_active_intervals=zeros,
            median_nonzero_capacity_increment_Ah=statistics.median(positive) if positive else None,
            minimum_nonzero_capacity_increment_Ah=min(positive) if positive else None,
            exploratory_whole_step_charge_comparison=aggregated)
    manifest=json.loads((OUT/'frozen_manifest.json').read_text())
    for rel,h in manifest.items():
        src=ROOT/rel
        assert hashlib.sha256(src.read_bytes()).hexdigest()==h
        target=OUT/'source'/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,target)
    result=dict(public_diagnostics=findings,all_frozen_sources_unchanged=True,
        caveat='post-hoc exploratory diagnostic; not a new validated estimator or retuned result')
    (OUT/'independent_diagnostics.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    for name,r in findings.items():
        print(name,'nonincreasing',len(r['nonincreasing_pairs']),
              'identical',sum(x['identical_record'] for x in r['nonincreasing_pairs']),
              'zeroQ',r['zero_capacity_increment_active_intervals'],'/',r['active_intervals'],
              'minQ',r['minimum_nonzero_capacity_increment_Ah'],
              'step ratios',[x['ratio'] for x in r['exploratory_whole_step_charge_comparison'][:8]])
if __name__=='__main__':main()

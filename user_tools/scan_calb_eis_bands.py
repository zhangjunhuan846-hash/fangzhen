"""Development-only frequency-band diagnostics on CALB cell 60129."""
import json
from pathlib import Path
from user_tools.validate_calb_eis_bms import spectrum_csv
from user_tools.workbench.engineering_eis_grid import run_grid
from user_tools.workbench.engineering_contracts import defaults

raw,_=spectrum_csv();out=Path('outputs/eis_bms_validation/calb_eis_band_development_20261029');records=[]
for low,high in [(0.01,1000.),(.05,2000.),(.1,3000.),(.5,1000.),(.01,3000.)]:
    cfg=defaults('eis_grid');cfg.update(data_origin='public',source='https://doi.org/10.17632/ycx459r5c3.2',
        rc_branches=2,frequency_min_Hz=low,frequency_max_Hz=high,interpolation='log_invT')
    r=run_grid(cfg,out/f'{low}_{high}',raw)
    records.append({'low_Hz':low,'high_Hz':high,'kk_passed':r['metrics']['kk_passed'],
        'grid_usable_for_replay':r['grid_usable_for_replay'],
        'max_test_relative_rms':max(x['relative_rms'] for x in r['spectra_summary'] if x['role']=='test')})
    print(records[-1],flush=True)
out.mkdir(parents=True,exist_ok=True)
(out/'bands.json').write_text(json.dumps(records,indent=2),encoding='utf8')

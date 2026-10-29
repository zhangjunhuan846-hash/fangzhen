"""Retrospective same-cell EIS grid versus independent earlier C/3 pulses."""
import csv
import argparse
import io
import json
from pathlib import Path
import numpy as np
from scipy.io import loadmat
from user_tools.workbench.engineering_contracts import defaults
from user_tools.workbench.engineering_eis_grid import run_grid
from user_tools.workbench.engineering_service import bridge_eis_grid
from user_tools.workbench.engineering_bms import estimate_stream
from user_tools.workbench.engineering_bms import run_bms
from user_tools.workbench import engineering_calb_validation as base
from user_tools.workbench.engineering_common import save,write_csv
from user_tools.workbench.engineering_crosscell import verify_all

CELL='60129'
OUT=Path('outputs/eis_bms_validation/calb_eis_pulse_20261029')/CELL
WARM_ONLY=False


def spectrum_csv():
    text=io.StringIO(newline='');writer=csv.writer(text)
    writer.writerow(['cell_id','spectrum_id','role','soc','temperature_C','frequency_Hz','Z_real_ohm','Z_imag_ohm'])
    soc_audit=[]
    for temp in ((25,40) if WARM_ONLY else base.TEMPS):
        root=(base.EXTRA3_DATA if CELL in base.EXTRA3_CELLS else base.EXTRA2_DATA if CELL in base.EXTRA2_CELLS
              else base.EXTRA_DATA if CELL in base.EXTRA_CELLS else base.DATA)
        p=root/f'Temperature_{temp}C'/'eis_test'/(CELL+'.mat')
        spectra=loadmat(p,simplify_cells=True)['Data']
        if not isinstance(spectra,list) or len(spectra)!=4:raise ValueError('需要每温度四条完整EIS')
        voltages=[float(s['OCV_value']) for s in spectra]
        if not all(a>b for a,b in zip(voltages,voltages[1:])):raise ValueError('EIS谱顺序与单调放电不一致')
        ref=base.slow_reference(CELL,temp)
        for spectrum,soc in zip(spectra,(.8,.6,.4,.2)):
            role='train' if soc in (.2,.8) and (WARM_ONLY or temp in (10,40)) else 'test'
            m=spectrum['meas'];sid=f'{CELL}_{temp}_{soc}'
            for f,re,im in zip(m['Frequency'],m['Zreal'],m['Zimg']):writer.writerow([CELL,sid,role,soc,temp,f,re,im])
            soc_audit.append({'cell_id':CELL,'temperature_C':temp,'nominal_soc':soc,
                'c20_voltage_inferred_soc':float(np.interp(float(spectrum['OCV_value']),ref['reference_voltage'],ref['reference_soc'])),
                'eis_ocv_V':float(spectrum['OCV_value'])})
    return text.getvalue().encode(),soc_audit


def main():
    global CELL,OUT,WARM_ONLY
    parser=argparse.ArgumentParser();parser.add_argument('--cell',choices=('60129','59627','60031'),default='60129');parser.add_argument('--warm-only',action='store_true');args=parser.parse_args()
    CELL=args.cell;WARM_ONLY=args.warm_only;OUT=Path('outputs/eis_bms_validation/calb_eis_pulse_20261029')/(CELL+('-25_40C' if WARM_ONLY else ''))
    manifest_hash=verify_all()
    raw,audit=spectrum_csv();OUT.mkdir(parents=True,exist_ok=True);(OUT/'eis_input.csv').write_bytes(raw)
    write_csv(OUT/'soc_label_audit.csv',audit);summaries=[];pulse_rows=[]
    for branches in (1,2):
        cfg=defaults('eis_grid');cfg.update(data_origin='public',source='https://doi.org/10.17632/ycx459r5c3.2',
             rc_branches=branches,frequency_min_Hz=.5,frequency_max_Hz=1000.,interpolation='log_invT')
        folder=OUT/f'{branches}rc';result=run_grid(cfg,folder,raw)
        hold=[x for x in result['spectra_summary'] if x['role']=='test' and x['relative_rms'] is not None]
        info={'branches':branches,'usable_for_replay':result['grid_usable_for_replay'],
              'kk_passed':result['metrics']['kk_passed'],'total_spectra':result['metrics']['total_spectra'],
              'heldout_mean_relative_rms':float(np.mean([r['relative_rms'] for r in hold])) if hold else None}
        summaries.append(info)
        if not result['grid_usable_for_replay']:continue
        cell,refs,_=base.fit_cell(CELL);cell.update(cell_id=CELL,initial_soc=.5,estimated_initial_soc=.46,temperature_C=25.)
        replay=defaults('ecm_bms');replay.update(cell=cell,data_origin='public',source=cfg['source'],
                   same_cell_eis_confirmed=True,filter_rc_mode='estimated_grid',voltage_noise_V=.005,current_noise_A=0.)
        replay=bridge_eis_grid(replay,result,'calb_eis_retrospective',(folder/'rc_grid.json').read_bytes())
        for temp in ((25,40) if WARM_ONLY else base.TEMPS):
            for window in base.pulse_windows(CELL,temp,refs[temp]):
                replay['cell']['estimated_initial_soc']=float(window['soc_proxy'][0]-.04)
                rows=[{'time_s':float(k),'sensor_current_A':float(i),'sensor_voltage_V':float(v),
                       'measured_temperature_C':float(temp),'soc_reference':float(s)}
                      for k,(i,v,s) in enumerate(zip(window['current'],window['voltage'],window['soc_proxy']))]
                try:
                    _,m=estimate_stream(replay,rows);pulse_rows.append({'branches':branches,'temperature_C':temp,
                       'target_soc':window['target_soc'],'status':'ok','ekf_prior_voltage_rmse_mV':m['ekf_prior_voltage_rmse_V']*1000,
                       'soc_proxy_rmse':m['ekf_rmse_soc']})
                except ValueError as exc:
                    if '不支持外推' not in str(exc):raise
                    pulse_rows.append({'branches':branches,'temperature_C':temp,'target_soc':window['target_soc'],
                                       'status':'outside_grid','ekf_prior_voltage_rmse_mV':None,'soc_proxy_rmse':None})
        if WARM_ONLY and branches==2:
            # Provide the exact same data in the workbench upload schema.
            demo=base.pulse_windows(CELL,25,refs[25])[1]
            stream=io.StringIO(newline='');w=csv.writer(stream)
            w.writerow(['time_s','current_A','voltage_V','temperature_C','soc_reference'])
            for k,(current,voltage,soc) in enumerate(zip(demo['current'],demo['voltage'],demo['soc_proxy'])):
                w.writerow([k,current,voltage,25.,soc])
            replay_raw=stream.getvalue().encode();(OUT/'bms_pulse_input.csv').write_bytes(replay_raw)
            demo_cell,_,_=base.fit_cell(CELL)
            demo_cell.update(cell_id=CELL,initial_soc=float(demo['soc_proxy'][0]),
                estimated_initial_soc=float(demo['soc_proxy'][0]-.04),temperature_C=25.,isothermal=True,
                current_max_A=60.,voltage_min_V=2.5,voltage_max_V=4.3,temperature_max_C=60.)
            demo_cell.pop('rc_table',None);demo_cell.pop('rc_interpolation',None)
            user_cfg=defaults('ecm_bms');user_cfg.update(cell=demo_cell,data_origin='public',source=cfg['source'],
                same_cell_eis_confirmed=True,filter_rc_mode='estimated_grid',voltage_noise_V=.005,current_noise_A=0.)
            save(OUT/'bms_config.json',user_cfg);save(OUT/'eis_config.json',cfg)
            demo_config=bridge_eis_grid(user_cfg,result,'calb_eis_retrospective',(folder/'rc_grid.json').read_bytes())
            run_bms(demo_config,OUT/'bms_end_to_end',replay_raw)
    if any(x['usable_for_replay'] for x in summaries):
        cell,refs,_=base.fit_cell(CELL)
        for temp in ((25,40) if WARM_ONLY else base.TEMPS):
            for window in base.pulse_windows(CELL,temp,refs[temp]):
                metrics,_=base.score_window(cell,temp,window,'estimated_grid',.005)
                pulse_rows.append({'branches':0,'temperature_C':temp,'target_soc':window['target_soc'],'status':'ok',
                    'ekf_prior_voltage_rmse_mV':metrics['ekf_prior_voltage_rmse_V']*1000,'soc_proxy_rmse':metrics['ekf_rmse_soc']})
    if pulse_rows:write_csv(OUT/'eis_pulse_metrics.csv',pulse_rows)
    save(OUT/'summary.json',{'cell':CELL,'grid':summaries,'pulse_results':pulse_rows,
          'extra_manifest_sha256':manifest_hash,
          'scope':'EIS collected after pulses and driving: retrospective temporal order; EIS SOC labels nominal protocol values, not measured SOC; independent test pulse is earlier than EIS; not prospective or same-SOH proven',
          'temperature_scope_C':[25,40] if WARM_ONLY else list(base.TEMPS),
          'nominal_soc_label':'4 complete spectra sorted by measured time/descending voltage, mapped to protocol 80/60/40/20%',
          'soc_audit':audit})
    print(json.dumps(summaries,indent=2))


if __name__=='__main__':main()

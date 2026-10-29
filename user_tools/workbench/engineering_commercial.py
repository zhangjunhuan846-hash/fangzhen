"""Commercial Panasonic PF identification, frozen-model replay and independent checks."""
import hashlib
import json
from pathlib import Path
import time
import numpy as np

from user_tools.workbench.engineering_common import ROOT, finish, save, write_csv


DATA = ROOT/'data/public/panasonic_pf_v1'


def load_measurement(path):
    from scipy.io import loadmat
    x = loadmat(path, simplify_cells=True)['meas']
    return {k: np.asarray(v, dtype=float) for k, v in x.items() if k != 'TimeStamp'}


def resample(x, lo=0, hi=None):
    """Preserve charge integrated from the measured current, never a resetting Ah counter."""
    from scipy.integrate import cumulative_trapezoid
    hi = len(x['Time']) if hi is None else hi
    t = x['Time'][lo:hi]; keep = np.r_[np.diff(t) > 1e-9, True]
    t = t[keep]; t = t-t[0]
    grid = np.r_[np.arange(0, t[-1], 1.), t[-1]]
    cols = {k: np.interp(grid, t, v[lo:hi][keep]) for k, v in x.items() if k != 'Time'}
    charge = np.interp(grid, t, cumulative_trapezoid(-x['Current'][lo:hi][keep], t, initial=0))
    current = np.r_[-cols['Current'][0], np.diff(charge)/np.diff(grid)]
    return dict(t=grid, current=current, v=cols['Voltage'], temp=cols['Battery_Temp_degC'],
                ambient=cols['Chamber_Temp_degC'], ah=cols['Ah'], cumulative_charge_As=charge)


def rc_voltage(p, stream, ocv, branches):
    from scipy.signal import lfilter
    # All calibration segments are sampled at exactly 1s except their last endpoint.
    r0 = np.exp(p[0]); v = ocv-r0*stream['current']+p[-1]
    for j in range(branches):
        r, tau = np.exp(p[1+2*j:3+2*j]); a = np.exp(-1/tau)
        v = v-lfilter([r*(1-a)], [1., -a], stream['current'])
    return v


def identify(out):
    from scipy.optimize import least_squares
    from scipy.signal import lfilter
    hppc_path = next(DATA.rglob('*5Pulse_HPPC*.mat'))
    h = load_measurement(hppc_path)
    boundaries = np.r_[0, np.flatnonzero(np.diff(h['Time']) > 2)+1, len(h['Time'])]
    # Rest-to-rest table is identified from the calibration file, never test voltages.
    capacity = 2.9  # Published commercial nominal capacity; do not infer from a holdout endpoint.
    soc = [1+float(h['Ah'][lo])/capacity for lo in boundaries[:-1]]
    rest = [float(np.median(h['Voltage'][lo:lo+10])) for lo in boundaries[:-1]]
    soc, rest = np.asarray(soc)[::-1], np.asarray(rest)[::-1]
    ocv_soc = np.r_[0., soc]; ocv_v = np.maximum.accumulate(np.r_[2.5, rest])
    c20_path = next(DATA.rglob('*C20*.mat')); c20 = load_measurement(c20_path)
    mask = (c20['Current'] < -.1) & (c20['Chamber_Temp_degC'] >= 24)
    capacity_c20 = float(np.ptp(c20['Ah'][mask]))
    streams, models, fits = [], {}, []
    for lo, hi in zip(boundaries[:-1], boundaries[1:]):
        s = resample(h, int(lo), int(hi)); s['soc'] = 1+s['ah']/capacity; streams.append(s)
    for branches in [1, 2]:
        table = []
        for i, s in enumerate(streams):
            initial = [np.log(.02)]
            lower, upper = [np.log(.001)], [np.log(.3)]
            for j in range(branches):
                initial += [np.log(.01), np.log(10. if j==0 else 150.)]
                lower += [np.log(.0001), np.log(1. if j==0 else 30.)]
                upper += [np.log(.3), np.log(100. if j==0 and branches==2 else 3000.)]
            initial += [0.]; lower += [-.15]; upper += [.15]
            ocv = np.interp(s['soc'], ocv_soc, ocv_v)
            fit = least_squares(lambda p: rc_voltage(p, s, ocv, branches)-s['v'], initial,
                                bounds=(lower, upper), max_nfev=120, loss='soft_l1', f_scale=.02)
            p = fit.x
            row = dict(soc=float(np.mean(s['soc'])), R0_ohm=float(np.exp(p[0])), temperature_C=25.)
            for j in range(branches):
                r, tau = np.exp(p[1+2*j:3+2*j]); row.update({f'R{j+1}_ohm': r, f'C{j+1}_F': tau/r})
            table.append(row)
            fits.append(dict(branches=branches, segment=i, soc=row['soc'], rmse_mV=float(np.sqrt(np.mean(fit.fun**2))*1000),
                             local_voltage_offset_V=p[-1], success=bool(fit.success)))
        table.sort(key=lambda r:r['soc'])
        models[branches] = dict(branches=branches, capacity_Ah=capacity, ocv_soc=ocv_soc.tolist(), ocv_V=ocv_v.tolist(), table=table)
    # Thermal calibration uses calibration-only currents and measured initial temperatures.
    table = models[2]['table']
    def thermal_residual(logp):
        cth, heat_transfer = np.exp(logp); a = np.exp(-heat_transfer/cth); residual = []
        for s in streams:
            rtot = np.interp(s['soc'], [r['soc'] for r in table], [r['R0_ohm']+r['R1_ohm']+r['R2_ohm'] for r in table])
            heat = s['current']**2*rtot
            target = 25.+heat/heat_transfer
            pred = lfilter([1-a], [1., -a], target, zi=[a*s['temp'][0]])[0]
            residual.extend((pred-s['temp'])[::10])
        return residual
    fit = least_squares(thermal_residual, np.log([60., .15]), bounds=(np.log([10., .01]), np.log([250., 2.])), max_nfev=100)
    cth, ht = np.exp(fit.x)
    for model in models.values(): model.update(thermal_capacity_J_K=float(cth), heat_transfer_W_K=float(ht))
    save(out/'identification.json', dict(models=models, fits=fits, published_capacity_Ah=capacity,
           measured_C20_capacity_Ah=capacity_c20, calibration_paths=[str(hppc_path.relative_to(ROOT)), str(c20_path.relative_to(ROOT))],
           thermal_loss_rmse_C=float(np.sqrt(np.mean(np.asarray(fit.fun)**2))),
           ocv_policy='HPPC initial rest voltages versus recorded Ah/nominal2.9Ah; 0SOC endpoint2.5V; piecewise monotone table',
           c20_role='capacity diagnostic only; May C20 is not used to fit March drive predictions',
           polarization_policy='each disconnected HPPC group resets RC to zero; never integrates across unrecorded inter-group discharges'))
    return models


def parameters(model, initial_soc, initial_temp, ambient):
    n = model['branches']; table = model['table']; sx = [r['soc'] for r in table]
    params = dict(num_RC_pairs=n, soc0=initial_soc, capacity=model['capacity_Ah'], gamma=0., ce=1., mass=.048,
          isothermal=False, Cp=model['thermal_capacity_J_K']/.048, T_inf=ambient+273.15,
          h_therm=model['heat_transfer_W_K'], A_therm=1.,
          ocv=lambda s: float(np.interp(s, model['ocv_soc'], model['ocv_V'])), M_hyst=lambda s:0.)
    for key in ['R0_ohm']+[k for j in range(1,n+1) for k in [f'R{j}_ohm', f'C{j}_F']]:
        output_key = key.split('_')[0]; values = [r[key] for r in table]
        params[output_key] = lambda soc,temp,values=values: float(np.interp(soc,sx,values))
    return params


def predict(model, stream):
    import thevenin
    p = parameters(model, 1., stream['temp'][0], float(np.median(stream['ambient'])))
    plant = thevenin.Prediction(p); plant.set_options(rtol=1e-8, atol=1e-10)
    state = thevenin.TransientState(1., stream['temp'][0]+273.15, 0., np.zeros(model['branches']))
    v, temp, soc = [], [], []
    for i, t in enumerate(stream['t']):
        if i: state = plant.take_step(state, float(stream['current'][i]), float(t-stream['t'][i-1]))
        voltage = state.voltage if i else p['ocv'](1.)-stream['current'][0]*p['R0'](1.,state.T_cell)
        v.append(voltage); temp.append(state.T_cell-273.15); soc.append(state.soc)
    return np.asarray(v), np.asarray(temp), np.asarray(soc)


def voltage_metrics(pred, stream):
    v, temp, soc = pred; error = v-stream['v']
    return dict(voltage_rmse_mV=float(np.sqrt(np.mean(error**2))*1000), voltage_mae_mV=float(np.mean(abs(error))*1000),
                voltage_p95_abs_mV=float(np.quantile(abs(error), .95)*1000),
                temperature_rmse_C=float(np.sqrt(np.mean((temp-stream['temp'])**2))), coverage=1.,
                observed_voltage_out_of_2_5_4_2_V=int(np.sum((stream['v']<2.5)|(stream['v']>4.2))),
                predicted_voltage_out_of_2_5_4_2_V=int(np.sum((v<2.5)|(v>4.2))), points=len(v))


def cell_for_control(model):
    from user_tools.workbench.engineering_contracts import default_cell
    cell = default_cell(); table = model['table']; middle = min(table,key=lambda r:abs(r['soc']-.5))
    cell.update(cell_id='Panasonic-NCR18650PF-published-cell', capacity_Ah=2.9, initial_soc=.3, estimated_initial_soc=.3,
                mass_kg=.048, heat_capacity_J_kgK=model['thermal_capacity_J_K']/.048,
                heat_transfer_W_K=model['heat_transfer_W_K'], current_max_A=2.9, voltage_min_V=2.5,
                ocv_soc=model['ocv_soc'], ocv_V=model['ocv_V'], R0_ohm=middle['R0_ohm'],
                R_ohm=[middle[f'R{j}_ohm'] for j in range(1,model['branches']+1)],
                C_F=[middle[f'C{j}_F'] for j in range(1,model['branches']+1)])
    return cell


def run_commercial(config, out):
    out = Path(out); start = time.perf_counter()
    manifest = json.loads((DATA/'download_manifest.json').read_text(encoding='utf-8'))
    for item in manifest['files']:
        path = Path(item['path']); path = ROOT/path if item['path'].startswith('data/') else DATA/path
        if hashlib.sha256(path.read_bytes()).hexdigest() != item['expected_sha256']:
            raise ValueError('公开原始文件哈希不符：'+str(path))
    protocol = json.loads((ROOT/'configs/commercial_pf_validation_20261029.json').read_text(encoding='utf-8'))
    save(out/'validation_protocol.json', protocol)
    models = identify(out)
    calibration_path = next(DATA.rglob('*Cycle_1_*.mat'))
    calibration = resample(load_measurement(calibration_path))
    selection = {n: voltage_metrics(predict(m, calibration), calibration) for n, m in models.items()}
    chosen = min(selection, key=lambda n: selection[n]['voltage_rmse_mV'])
    model = models[chosen]
    # Freeze all selection before opening any independent-drive or July signal contents.
    residual_noise = max(.005, min(.1, selection[chosen]['voltage_rmse_mV']/1000))
    frozen = dict(model=model, selection=selection, selected_branches=chosen, voltage_noise_V=residual_noise,
                  selection_source=str(calibration_path.relative_to(ROOT)), independent_holdout_opened=False)
    save(out/'frozen_model.json', frozen)
    frozen_hash = hashlib.sha256((out/'frozen_model.json').read_bytes()).hexdigest()
    save(out/'pre_holdout_freeze.json', dict(frozen_model_sha256=frozen_hash, source_manifest_sha256=hashlib.sha256((DATA/'download_manifest.json').read_bytes()).hexdigest()))
    paths = [next(DATA.rglob(p)) for p in ['*US06_*.mat','*UDDS_*.mat','*LA92_*.mat']]
    paths += sorted((DATA/'25degC/C20 OCV Test_end_of_tests').glob('*Dis1C*.mat'))
    if len(paths)<5: raise ValueError('缺少独立工况/时间留出测试。')
    all_rows, scores, curves = [], [], []
    from user_tools.workbench.engineering_bms import estimate_stream
    segments = []
    for path in paths:
        raw = load_measurement(path)
        # Repeated 1C file omits intervening charges. Do not synthesize their missing signals.
        splits = np.r_[0, np.flatnonzero(np.diff(raw['Time'])>60)+1, len(raw['Time'])]
        for segment, (lo,hi) in enumerate(zip(splits[:-1],splits[1:])):
            segments.append((path, raw, int(lo), int(hi), segment+1, len(splits)-1))
    for path, raw, lo, hi, segment, total_segments in segments:
        test_name = path.stem+(f'__segment{segment}' if total_segments>1 else '')
        s = resample(raw,lo,hi); pred = predict(model, s)
        metrics = voltage_metrics(pred, s)
        n = model['branches']; cell = cell_for_control(model)
        cell.update(initial_soc=.999, estimated_initial_soc=.85)
        observations = [dict(time_s=float(t), sensor_current_A=float(i), sensor_voltage_V=float(v),
                      soc_reference=float(1-q/(3600*model['capacity_Ah']))) for t,i,v,q in zip(s['t'],s['current'],s['v'],s['cumulative_charge_As'])]
        estimated, fm = estimate_stream(dict(cell=cell,voltage_noise_V=residual_noise,current_noise_A=0.), observations)
        metrics.update(fm); metrics['test'] = test_name
        metrics['role'] = 'time_holdout_aged_cell' if 'end_of_tests' in str(path) else 'condition_holdout'
        metrics['screening_voltage_pass'] = metrics['voltage_rmse_mV'] <= 50
        metrics['screening_thermal_pass'] = metrics['temperature_rmse_C'] <= 3
        metrics['screening_soc_pass'] = metrics['ekf_rmse_soc'] <= .03
        scores.append(metrics)
        for k, t in enumerate(s['t']):
            all_rows.append(dict(test=test_name,time_s=t,current_A=s['current'][k],measured_voltage_V=s['v'][k],
                 predicted_voltage_V=pred[0][k],measured_temperature_C=s['temp'][k],predicted_temperature_C=pred[1][k],
                 soc_coulomb_reference=observations[k]['soc_reference'],soc_ekf=estimated[k]['soc_ekf'],soc_ukf=estimated[k]['soc_ukf']))
        stride = max(1,len(s['t'])//500)
        curves.append(dict(name=test_name+' 电压',y_label='电压 (V)',primary='冻结模型',secondary='留出实测',
             points=[[s['t'][i],pred[0][i],s['v'][i]] for i in range(0,len(s['t']),stride)]))
    if hashlib.sha256((out/'frozen_model.json').read_bytes()).hexdigest()!=frozen_hash: raise RuntimeError('冻结模型被修改。')
    write_csv(out/'commercial_metrics.csv', scores)
    save(out/'commercial_validation.json', dict(dataset=manifest, frozen_model_sha256=frozen_hash, model_selection=selection,
          tests=scores, cell_count=1, external_cell_validation=False, parameter_tuned_on_holdout=False,
          soc_reference='integrated measured current/nominal2.9Ah, not an independent SOC instrument',
          missing_interval_policy='split original time gaps >60s; every recorded discharge segment retained; unrecorded charges never interpolated',
          temperature_input='initial measured case temperature and median chamber ambient, no measured future case temperature feedback',
          limitation='single physical cell, 25C calibration; July aging deliberately not refitted; finite-pool optimizers are separate recommendation tools'))
    save(out/'commercial_control_config.json', dict(action='mpc',data_origin='public',source=config['source'],cell=cell_for_control(model),
          steps=180,dt_s=12.,horizon=8,target_soc=.8,voltage_noise_V=.005,current_noise_A=0.,current_bias_A=0.,seed=42))
    return finish(config,out,dict(kind='engineering', title='Panasonic PF · 冻结模型独立验证', engine='Thevenin + scipy identification + SOX',
         metrics=dict(independent_tests=len(scores), condition_tests=3, chronological_tests=len(scores)-3,
          selected_RC_branches=chosen, voltage_tests_passed=sum(r['screening_voltage_pass'] for r in scores),
          thermal_tests_passed=sum(r['screening_thermal_pass'] for r in scores),soc_tests_passed=sum(r['screening_soc_pass'] for r in scores),
          worst_voltage_rmse_mV=max(r['voltage_rmse_mV'] for r in scores), elapsed_s=time.perf_counter()-start),
         tests=scores,details={'scope':'同一公开商用电芯：HPPC辨识→Cycle1选型→冻结→US06/UDDS/LA92及7月老化电芯测试。完整工况计算无裁剪；SOC仅对库仑参考，未验证跨电芯泛化。'}),
         all_rows,curves,['thevenin','scipy','numpy','sox'])

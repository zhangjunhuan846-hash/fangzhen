"""Thevenin electrothermal plant + actual SOX CC/EKF/UKF implementations."""
from __future__ import annotations
import time
import numpy as np

from user_tools.workbench.engineering_common import finish
from user_tools.workbench.engineering_contracts import csv_rows, finite


def ocv_function(cell):
    x, y = np.asarray(cell['ocv_soc']), np.asarray(cell['ocv_V'])

    def value(soc):
        k = int(np.clip(np.searchsorted(x, float(soc), side='right') - 1, 0, len(x) - 2))
        return float(y[k] + (float(soc) - x[k]) * (y[k+1] - y[k]) / (x[k+1] - x[k]))

    return value


def plant_parameters(cell):
    from user_tools.workbench.engineering_rc_grid import make_rc_interpolator
    ocv = ocv_function(cell)
    params = {'num_RC_pairs': len(cell['R_ohm']), 'soc0': cell['initial_soc'],
              'capacity': cell['capacity_Ah'], 'gamma': 0., 'ce': 1.,
              'mass': cell['mass_kg'], 'isothermal': bool(cell.get('isothermal', False)),
              'Cp': cell['heat_capacity_J_kgK'], 'T_inf': cell['temperature_C'] + 273.15,
              'h_therm': cell['heat_transfer_W_K'], 'A_therm': 1.,
              'ocv': ocv, 'M_hyst': lambda soc: 0.}
    scalar = {'R0': cell['R0_ohm']}
    for i, (r, c) in enumerate(zip(cell['R_ohm'], cell['C_F']), 1):
        scalar.update({f'R{i}': r, f'C{i}': c})
    table = cell.get('rc_table')
    if not table:
        params.update({key: (lambda soc, temp, v=value: v) for key, value in scalar.items()})
        return params
    interp = make_rc_interpolator(table, len(cell['R_ohm']), cell.get('rc_interpolation','linear'))
    temps = sorted({float(r['temperature_C']) for r in table})
    if len(temps)==1 and cell.get('isothermal') is True and abs(cell['temperature_C']-temps[0])>1e-7:
        raise ValueError('等温回放初始温度必须与单温度RC表一致。')
    for key in scalar:
        unit_key = key + ('_F' if key.startswith('C') else '_ohm')
        def parameter(soc, temp, unit_key=unit_key):
            t=float(temp)-273.15
            # Isothermal solvers can perturb temperature internally for Jacobians.
            if len(temps)==1 and cell.get('isothermal') is True:t=temps[0]
            return interp(soc,t)[unit_key]

        params[key] = parameter
    return params


def profile(config, raw=None):
    if raw is not None:
        rows = csv_rows(raw)
        if not {'time_s', 'current_A'} <= set(rows[0]):
            raise ValueError('动态CSV需要time_s,current_A；用户SOC估计还需voltage_V。')
        parsed = []
        for row in rows:
            item = {'time_s': finite(row['time_s'], 'time_s', 0),
                    'current_A': finite(row['current_A'], 'current_A', -1000, 1000)}
            for key in ['voltage_V', 'soc_reference', 'temperature_C']:
                if row.get(key) not in (None, ''):
                    item[key] = finite(row[key], key)
            if parsed and item['time_s'] <= parsed[-1]['time_s']:
                raise ValueError('时间必须严格递增。')
            if abs(item['current_A']) > config['cell']['current_max_A']:
                raise ValueError('输入电流超过声明的电芯限值。')
            parsed.append(item)
        if parsed[0]['time_s'] != 0 or len(parsed) > 1001:
            raise ValueError('动态CSV需从0秒开始，最多1001个点。')
        if config['data_origin'] != 'synthetic' and any('voltage_V' not in r for r in parsed):
            raise ValueError('实测SOC估计每个时间点都需要voltage_V。')
        return parsed
    maximum = min(3., config['cell']['current_max_A'])
    return [{'time_s': i * config['dt_s'],
             'current_A': maximum * (1 if (i // 15) % 3 == 0 else -.3 if (i // 15) % 3 == 1 else .05)}
            for i in range(config['steps'] + 1)]


def estimate_stream(config, rows):
    from sox.filter.coulomb_count import CoulombCount
    from sox.filter.extended_kalman_filter import ExtendedKalmanFilter
    from sox.filter.unscented_kalman_filter import UnscentedKalmanFilter, MerweSigmaPoints

    cell = config['cell']
    r, c = np.asarray(cell['R_ohm']), np.asarray(cell['C_F'])
    n = 1 + len(r)
    ocv = ocv_function(cell)
    ocv_mode=config.get('filter_ocv_mode','soc_only')
    if ocv_mode not in ('soc_only','soc_temperature'):
        raise ValueError('filter_ocv_mode仅支持soc_only或soc_temperature。')
    if ocv_mode=='soc_temperature':
        from user_tools.workbench.engineering_rc_grid import make_ocv_interpolator
        ocv_grid=make_ocv_interpolator(cell.get('ocv_temperature_table'))
    else:ocv_grid=None
    filter_mode = config.get('filter_rc_mode', 'fixed')
    if filter_mode not in ('fixed', 'estimated_grid', 'estimated_grid_jacobian'):
        raise ValueError('filter_rc_mode仅支持fixed、estimated_grid或estimated_grid_jacobian。')
    if filter_mode != 'fixed' and not cell.get('rc_table'):
        raise ValueError('estimated_grid需要经校验的EIS参数表。')
    grid_parameters = plant_parameters(cell) if filter_mode != 'fixed' else None
    x0 = np.array([cell['estimated_initial_soc'], *np.zeros(len(r))])[:, None]
    covariance = np.diag([.15**2, *([.02**2] * len(r))])
    soc_variance=finite(config.get('soc_process_variance_per_step',1e-8),'soc_process_variance_per_step',0.,1e-3)
    q = np.diag([soc_variance, *([1e-7] * len(r))])
    observation = np.array([[config['voltage_noise_V']**2 + (config['current_noise_A'] * cell['R0_ohm'])**2]])
    ekf = ExtendedKalmanFilter(np.eye(n), np.zeros((n, 1)), q, observation, x0.copy(), covariance.copy())
    use_ukf=config.get('enable_ukf',True)
    if not isinstance(use_ukf,bool):raise ValueError('enable_ukf必须为true或false。')
    constraint=config.get('soc_constraint','strict')
    if constraint not in ('strict','project') or (constraint=='project' and use_ukf):
        raise ValueError('SOC投影仅支持单独EKF；请设置enable_ukf=false。')
    min_soc,max_soc=0.,1.
    for tab in ([cell.get('ocv_temperature_table')] if ocv_grid is not None else [])+([cell.get('rc_table')] if grid_parameters is not None else []):
        min_soc=max(min_soc,min(float(row['soc']) for row in tab))
        max_soc=min(max_soc,max(float(row['soc']) for row in tab))
    if min_soc>=max_soc:raise ValueError('OCV和RC表SOC范围没有重叠。')
    ukf = (UnscentedKalmanFilter(q.copy(), observation.copy(), x0.copy(), covariance.copy(),
                               MerweSigmaPoints(n, .3, 2., 0.)) if use_ukf else None)
    cc = CoulombCount(float(x0[0, 0]), cell['capacity_Ah'], 0.)
    output = []
    elapsed = []
    projection_steps=0
    for index, row in enumerate(rows):
        tick = time.perf_counter()
        projected_before=False
        if constraint=='project':
            previous_soc=float(ekf.x[0,0]);ekf.x[0,0]=np.clip(previous_soc,min_soc,max_soc)
            projected_before=float(ekf.x[0,0])!=previous_soc
        current = row['sensor_current_A']
        dt = row['time_s'] - rows[index-1]['time_s'] if index else 0.
        temperature = row.get('measured_temperature_C')
        if (grid_parameters is not None or ocv_grid is not None) and temperature is None:
            if cell.get('isothermal') is True:
                temperature = cell['temperature_C']
            else:
                raise ValueError('estimated_grid需要每个时间点的测量温度，或明确声明等温。')
        def filter_ocv(soc):
            return ocv(soc) if ocv_grid is None else ocv_grid(float(soc),float(temperature))
        if grid_parameters is not None and cell.get('isothermal') is True:
            temp_nodes = {float(item['temperature_C']) for item in cell['rc_table']}
            if len(temp_nodes)==1 and abs(float(temperature)-next(iter(temp_nodes)))>1e-7:
                raise ValueError('单温度RC表与输入温度不一致，不支持外推。')

        def model_at(soc):
            if grid_parameters is None:
                return cell['R0_ohm'], r, c
            kelvin = float(temperature) + 273.15
            r0 = grid_parameters['R0'](soc, kelvin)
            rr = np.array([grid_parameters[f'R{j}'](soc, kelvin) for j in range(1, n)])
            cc_values = np.array([grid_parameters[f'C{j}'](soc, kelvin) for j in range(1, n)])
            return r0, rr, cc_values

        def matrices(rr, cc_values):
            decay = np.exp(-dt / (rr * cc_values))
            f = np.diag([1., *decay])
            b = np.array([-dt / (3600 * cell['capacity_Ah']), *(rr * (1 - decay))])[:, None]
            return f, b

        def jacobian(state):
            soc = float(state[0, 0])
            if ocv_grid is None:
                slope = (ocv(soc + 1e-5) - ocv(soc - 1e-5)) / 2e-5
            else:
                lo=max(min(float(v['soc']) for v in cell['ocv_temperature_table']),soc-1e-5)
                hi=min(max(float(v['soc']) for v in cell['ocv_temperature_table']),soc+1e-5)
                if hi<=lo:raise ValueError('SOC超出OCV温度表，无法计算雅可比。')
                slope=(filter_ocv(hi)-filter_ocv(lo))/(hi-lo)
            if filter_mode == 'estimated_grid_jacobian':
                lo=max(min(float(v['soc']) for v in cell['rc_table']),soc-1e-5)
                hi=min(max(float(v['soc']) for v in cell['rc_table']),soc+1e-5)
                if hi<=lo:raise ValueError('SOC超出RC网格，无法计算雅可比。')
                slope-=current*(model_at(hi)[0]-model_at(lo)[0])/(hi-lo)
            return np.array([[slope, *([-1.] * len(r))]])

        # Each filter uses its own previous estimate, never the plant's true SOC.
        # Parameters are held fixed over this step (quasi-static approximation).
        ekf_r0, ekf_r, ekf_c = model_at(float(ekf.x[0, 0]))
        ekf.F, ekf.B = matrices(ekf_r, ekf_c)
        nominal_prediction=ekf.F@ekf.x+ekf.B*current
        if filter_mode == 'estimated_grid_jacobian':
            estimated_soc=float(ekf.x[0,0])
            lo=max(min(float(v['soc']) for v in cell['rc_table']),estimated_soc-1e-5)
            hi=min(max(float(v['soc']) for v in cell['rc_table']),estimated_soc+1e-5)
            if hi<=lo:raise ValueError('SOC超出RC网格，无法计算雅可比。')
            _,rlo,clo=model_at(lo);_,rhi,chi=model_at(hi)
            flo,blo=matrices(rlo,clo);fhi,bhi=matrices(rhi,chi)
            derivative=((fhi-flo)@ekf.x+(bhi-blo)*current)/(hi-lo)
            ekf.F[1:,0]=derivative[1:,0]
        def ekf_measurement(state):
            r0 = model_at(float(state[0,0]))[0] if filter_mode == 'estimated_grid_jacobian' else ekf_r0
            return np.array([[filter_ocv(state[0, 0]) - np.sum(state[1:]) - current * r0]])
        ekf.predict(np.array([current]))
        if filter_mode == 'estimated_grid_jacobian':
            # SOX uses F for both state and covariance; the Jacobian is only
            # for covariance, so retain the nonlinear nominal state prediction.
            ekf.x=nominal_prediction
        projected=projected_before
        if constraint=='project':
            old_soc=float(ekf.x[0,0]);ekf.x[0,0]=np.clip(old_soc,min_soc,max_soc)
            projected=projected or float(ekf.x[0,0])!=old_soc
        ekf_prior_voltage = float(ekf_measurement(ekf.x)[0, 0])
        ekf.update(np.array([row['sensor_voltage_V']]), ekf_measurement, jacobian)
        if constraint=='project':
            old_soc=float(ekf.x[0,0]);ekf.x[0,0]=np.clip(old_soc,min_soc,max_soc)
            projected=projected or float(ekf.x[0,0])!=old_soc
            projection_steps+=int(projected)
        ukf_prior_voltage=None
        if use_ukf:
            ukf_r0, ukf_r, ukf_c = model_at(float(ukf.x[0, 0]))
            ukf_f, ukf_b = matrices(ukf_r, ukf_c)
            def transition(state):
                return ukf_f @ state + ukf_b * current
            def ukf_measurement(state):
                return np.array([[filter_ocv(state[0, 0]) - np.sum(state[1:]) - current * ukf_r0]])
            ukf.predict(transition)
            ukf_prior_voltage = float(ukf_measurement(ukf.x)[0, 0])
            ukf.update(np.array([row['sensor_voltage_V']]), ukf_measurement)
        cc.sampling_time = dt
        cc.predict(current)
        for model in ((ekf,ukf) if use_ukf else (ekf,)):
            model.P = (model.P + model.P.T) / 2
            if not np.isfinite(model.x).all() or np.linalg.eigvalsh(model.P).min() < -1e-10:
                raise RuntimeError('滤波器状态或协方差不合法；未隐藏发散。')
        elapsed.append(time.perf_counter() - tick)
        output.append({**row, 'soc_cc': cc.soc, 'soc_ekf': float(ekf.x[0, 0]),
                       'soc_ukf': float(ukf.x[0, 0]) if use_ukf else None, 'soc_ekf_std': float(np.sqrt(ekf.P[0, 0])),
                       'voltage_ekf_prior_V': ekf_prior_voltage, 'voltage_ukf_prior_V': ukf_prior_voltage,
                       'soc_ekf_projected':projected,
                       'soc_ukf_std': float(np.sqrt(ukf.P[0, 0])) if use_ukf else None,
                       **{f'eta_ekf_{j}_V': float(ekf.x[j, 0]) for j in range(1, n)}})
    metrics = {'mean_filter_step_ms': float(np.mean(elapsed) * 1000),
               'max_filter_step_ms': float(np.max(elapsed) * 1000),'soc_projection_steps':projection_steps}
    for method in (('ekf','ukf') if use_ukf else ('ekf',)):
        error=np.array([row[f'voltage_{method}_prior_V']-row['sensor_voltage_V'] for row in output])
        metrics[method+'_prior_voltage_rmse_V']=float(np.sqrt(np.mean(error**2)))
    if all(row.get('soc_reference') is not None for row in output):
        for method in (('cc','ekf','ukf') if use_ukf else ('cc','ekf')):
            delta = np.array([row['soc_' + method] - row['soc_reference'] for row in output])
            metrics[method + '_rmse_soc'] = float(np.sqrt(np.mean(delta**2)))
            metrics[method + '_max_abs_soc'] = float(np.max(np.abs(delta)))
    return output, metrics


def run_bms(config, out, raw=None):
    import thevenin
    cell = config['cell']
    params = plant_parameters(cell)
    plant = thevenin.Prediction(params)
    plant.set_options(rtol=1e-8, atol=1e-10)
    state = thevenin.TransientState(cell['initial_soc'], cell['temperature_C'] + 273.15, 0.,
                                   np.zeros(len(cell['R_ohm'])))
    rng = np.random.default_rng(config['seed'])
    observations, events = [], []
    for i, point in enumerate(profile(config, raw)):
        current = point['current_A']
        dt = point['time_s'] - observations[-1]['time_s'] if i else 0.
        if i:
            state = plant.take_step(state, current, dt)
        voltage = state.voltage if i else params['ocv'](state.soc) - current * params['R0'](state.soc, state.T_cell)
        synthetic = config['data_origin'] == 'synthetic'
        sensor_i = current + rng.normal(0, config['current_noise_A']) + config['current_bias_A'] if synthetic else current
        sensor_v = voltage + rng.normal(0, config['voltage_noise_V']) if synthetic else point['voltage_V']
        ref = state.soc if synthetic else point.get('soc_reference')
        row = {'time_s': point['time_s'], 'current_A': current, 'model_voltage_V': float(voltage),
               'model_soc': float(state.soc), 'model_temperature_C': float(state.T_cell - 273.15),
               'sensor_current_A': float(sensor_i), 'sensor_voltage_V': float(sensor_v), 'soc_reference': ref,
               'measured_temperature_C': (float(state.T_cell - 273.15) if synthetic else point.get('temperature_C'))}
        observations.append(row)
        if not 0 <= state.soc <= 1 or not cell['voltage_min_V'] <= voltage <= cell['voltage_max_V'] or state.T_cell - 273.15 > cell['temperature_max_C']:
            events.append({'time_s': point['time_s'], 'kind': 'declared_operating_limit', 'action': 'stop'})
            break
    rows, metrics = estimate_stream(config, observations)
    metrics['voltage_comparison_rmse_V'] = float(np.sqrt(np.mean([(r['model_voltage_V']-r['sensor_voltage_V'])**2 for r in rows])))
    result = {'kind': 'engineering', 'title': 'Thevenin + SOX SOC状态估计', 'cell_id': cell['cell_id'],
              'metrics': metrics, 'events': events, 'points': len(rows), 'current_convention': 'positive_discharge',
              'current_alignment': 'row current is held over the preceding interval; row zero is initial observation',
              'filter_model': ('estimated SOC + input temperature lookup; mode '+config.get('filter_rc_mode')+('; synthetic temperature sensor is noiseless' if config['data_origin']=='synthetic' else '') if config.get('filter_rc_mode', 'fixed') != 'fixed' else 'fixed operating-point RC; optional plant table variation is not fed as true SOC'),
              'filter_ocv_model': ('SOC-temperature table, bounded lookup; plant OCV stays on declared SOC-only curve' if config.get('filter_ocv_mode','soc_only')=='soc_temperature' else 'declared SOC-only curve'),
              'soc_constraint':config.get('soc_constraint','strict'),
              'plant_solver_tolerances': {'rtol': 1e-8, 'atol': 1e-10},
              'scope': '真实调用thevenin与SOX CC/EKF/UKF（可选择单独EKF）；合成传感器可用于恢复/失配测试。SOC误差仅对提供的soc_reference计算，参考的独立性由数据来源决定；电热参数、OCV与初态由声明输入决定。'}
    curves = [{'name': 'SOC估计与参考', 'y_label': 'SOC (0–1)', 'primary': 'EKF估计', 'secondary': '独立参考 / 合成真值',
               'points': [[r['time_s'], r['soc_ekf'], r['soc_reference']] for r in rows]},
              {'name': '端电压响应', 'y_label': '电压 (V)', 'primary': '电池模型', 'secondary': '传感器输入',
               'points': [[r['time_s'], r['model_voltage_V'], r['sensor_voltage_V']] for r in rows]},
              {'name': '电热响应', 'y_label': '温度 (°C)', 'primary': '仿真温度', 'secondary': '输入测温',
               'points': [[r['time_s'], r['model_temperature_C'], r['measured_temperature_C']] for r in rows]}]
    return finish(config, out, result, rows, curves, ['thevenin', 'sox', 'numpy', 'scipy'])

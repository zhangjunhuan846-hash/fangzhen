"""Actual do-mpc optimizer with Thevenin plant and SOX voltage feedback."""
import numpy as np
import time

from user_tools.workbench.engineering_bms import plant_parameters, estimate_stream
from user_tools.workbench.engineering_common import finish


def run_control(config, out, raw=None, *, plant_cell_override=None, stop_on_model_soc=False, ideal_soc_feedback=False):
    import casadi as ca
    import do_mpc
    import thevenin
    cell, dt = config['cell'], config['dt_s']
    source=config.get('adaptive_parameter_source',{})
    verified_table=source.get('table_replay_source_verified') is True and bool(source.get('job_id')) and len(source.get('frozen_model_sha256',''))==64
    if cell.get('rc_table') and not verified_table:
        raise ValueError('MPC当前使用明确的固定工况RC参数；参数表先用动态回放检查。')
    target = config['target_soc']
    if target <= cell['estimated_initial_soc']:
        raise ValueError('充电目标SOC必须高于估计初始SOC。')
    model = do_mpc.model.Model('discrete')
    soc = model.set_variable('_x', 'soc')
    eta = model.set_variable('_x', 'eta', (len(cell['R_ohm']), 1))
    temp = model.set_variable('_x', 'temperature_C')
    charge = model.set_variable('_u', 'charge_A')
    r, capacitance = np.array(cell['R_ohm']), np.array(cell['C_F'])
    decay = np.exp(-dt / (r * capacitance))
    ocv = ca.interpolant('cell_ocv', 'linear', [cell['ocv_soc']], cell['ocv_V'])
    voltage = ocv(soc) - ca.sum1(eta) + charge * cell['R0_ohm']
    heat = charge * (-ca.sum1(eta) + charge * cell['R0_ohm'])
    next_soc = soc + charge * dt / (3600 * cell['capacity_Ah'])
    next_eta = ca.DM(decay) * eta - ca.DM(r * (1 - decay)) * charge
    next_temp = temp + dt * (heat - cell['heat_transfer_W_K'] * (temp - cell['temperature_C'])) / (cell['mass_kg'] * cell['heat_capacity_J_kgK'])
    model.set_rhs('soc', next_soc)
    model.set_rhs('eta', next_eta)
    model.set_rhs('temperature_C', next_temp)
    model.set_expression('voltage_V', voltage)
    model.set_expression('voltage_endpoint_V', ocv(next_soc)-ca.sum1(next_eta)+charge*cell['R0_ohm'])
    model.set_expression('temperature_endpoint_C', next_temp)
    model.setup()
    # setup creates do-mpc's structured symbols; objectives and constraints
    # must reference that structure, not the pre-setup symbols.
    soc, temp = model.x['soc'], model.x['temperature_C']
    voltage = model.aux['voltage_V']
    mpc = do_mpc.controller.MPC(model)
    mpc.set_param(n_horizon=config['horizon'], t_step=dt, n_robust=0, store_full_solution=False,
                  nlpsol_opts={'ipopt.print_level': 0, 'print_time': 0, 'ipopt.max_iter': 100})
    loss = 100 * (soc - target)**2 + .001 * (temp - cell['temperature_C'])**2
    mpc.set_objective(mterm=loss, lterm=loss)
    mpc.set_rterm(charge_A=.01)
    mpc.bounds['lower', '_u', 'charge_A'] = 0.
    mpc.bounds['upper', '_u', 'charge_A'] = cell['current_max_A']
    mpc.bounds['lower', '_x', 'soc'] = 0.
    mpc.bounds['upper', '_x', 'soc'] = .999
    voltage_guard = config['voltage_guard_V']
    temperature_guard = config['temperature_guard_C']
    mpc.set_nl_cons('voltage_max', voltage, ub=cell['voltage_max_V']-voltage_guard)
    mpc.set_nl_cons('voltage_endpoint_max', model.aux['voltage_endpoint_V'], ub=cell['voltage_max_V']-voltage_guard)
    mpc.set_nl_cons('temperature_max', temp, ub=cell['temperature_max_C']-temperature_guard)
    mpc.set_nl_cons('temperature_endpoint_max', model.aux['temperature_endpoint_C'], ub=cell['temperature_max_C']-temperature_guard)
    mpc.setup()
    # Optional internal research harness can vary the simulated plant while
    # retaining the controller/filter model. The normal desktop path is unchanged.
    plant_cell=plant_cell_override if plant_cell_override is not None else cell
    params = plant_parameters(plant_cell)
    plant = thevenin.Prediction(params)
    plant.set_options(rtol=1e-8, atol=1e-10)
    state = thevenin.TransientState(cell['initial_soc'], cell['temperature_C'] + 273.15, 0., np.zeros(len(r)))
    sensor = np.random.default_rng(config['seed'])
    observations = [{'time_s': 0., 'sensor_current_A': 0.,
                     'sensor_voltage_V': params['ocv'](state.soc) + sensor.normal(0, config['voltage_noise_V']),
                     'soc_reference': state.soc if config['data_origin'] == 'synthetic' else None}]
    estimate, _ = estimate_stream(config, observations)
    initial = np.array([state.soc if ideal_soc_feedback else estimate[-1]['soc_ekf'], *[estimate[-1][f'eta_ekf_{j}_V'] for j in range(1, len(r)+1)], cell['temperature_C']])[:, None]
    mpc.x0 = initial
    mpc.set_initial_guess()
    rows, events = [], []
    for i in range(config['steps']):
        est = estimate[-1]
        x = np.array([state.soc if ideal_soc_feedback else est['soc_ekf'], *[est[f'eta_ekf_{j}_V'] for j in range(1, len(r)+1)], state.T_cell - 273.15])[:, None]
        plant_soc_before=float(state.soc)
        fallback = False
        solver_status = 'not_run'
        solver_started=time.perf_counter()
        try:
            charge_value = float(np.asarray(mpc.make_step(x)).ravel()[0])
            if not np.isfinite(charge_value) or not -1e-6 <= charge_value <= cell['current_max_A'] + 1e-6:
                raise RuntimeError('MPC返回非法控制量。')
            stats=getattr(mpc, 'solver_stats', {})
            solver_status=str(stats.get('return_status', 'status_unavailable'))
            if not stats.get('success', True):
                raise RuntimeError('MPC求解未成功。')
            charge_value = float(np.clip(charge_value, 0, cell['current_max_A']))
        except (RuntimeError, ValueError) as exc:
            charge_value, fallback = 0., True
            solver_status='fallback: '+str(exc)
            events.append({'time_s': i * dt, 'kind': 'solver_fallback', 'reason': str(exc), 'charge_A': 0.})
        solver_time_ms=(time.perf_counter()-solver_started)*1000
        # Nominal first-step predictions use the actual controller input state;
        # they do not claim to be the extrema across the full horizon.
        soc_before=float(x[0,0]);eta_before=x[1:-1,0];temp_before=float(x[-1,0])
        soc_next=soc_before+charge_value*dt/(3600*cell['capacity_Ah'])
        eta_next=decay*eta_before-r*(1-decay)*charge_value
        voltage_start=float(ocv(soc_before))-float(np.sum(eta_before))+charge_value*cell['R0_ohm']
        voltage_end=float(ocv(soc_next))-float(np.sum(eta_next))+charge_value*cell['R0_ohm']
        heat_now=charge_value*(-float(np.sum(eta_before))+charge_value*cell['R0_ohm'])
        temp_end=temp_before+dt*(heat_now-cell['heat_transfer_W_K']*(temp_before-cell['temperature_C']))/(cell['mass_kg']*cell['heat_capacity_J_kgK'])
        state = plant.take_step(state, -charge_value, dt)
        measured_current = -charge_value + sensor.normal(0, config['current_noise_A']) + config['current_bias_A']
        measured_voltage = state.voltage + sensor.normal(0, config['voltage_noise_V'])
        observations.append({'time_s': (i+1)*dt, 'sensor_current_A': measured_current,
                             'sensor_voltage_V': measured_voltage,
                             'soc_reference': state.soc if config['data_origin'] == 'synthetic' else None})
        estimate, _ = estimate_stream(config, observations)
        row = {'time_s': (i+1)*dt, 'charge_A': charge_value, 'voltage_V': float(state.voltage),
               'temperature_C': float(state.T_cell - 273.15), 'soc_model': float(state.soc),
               'soc_ekf': estimate[-1]['soc_ekf'], 'fallback': fallback,'solver_time_ms':solver_time_ms,
               'plant_soc_before':plant_soc_before,'controller_soc_before':soc_before,'command_A':charge_value,'applied_A':charge_value,
               'predicted_voltage_start_V':voltage_start,'predicted_voltage_end_V':voltage_end,'predicted_temperature_end_C':temp_end,
               'solver_status':solver_status,
               'voltage_margin_V': cell['voltage_max_V'] - state.voltage,
               'temperature_margin_C': cell['temperature_max_C'] - (state.T_cell - 273.15)}
        rows.append(row)
        if row['voltage_margin_V'] < -1e-4 or row['temperature_margin_C'] < -1e-4 or not 0 <= state.soc <= 1:
            events.append({'time_s': row['time_s'], 'kind': 'plant_limit_exceeded', 'action': 'stop'})
            break
        if (state.soc if stop_on_model_soc else estimate[-1]['soc_ekf']) >= target:
            events.append({'time_s': row['time_s'], 'kind': 'model_target_reached' if stop_on_model_soc else 'estimated_target_reached'})
            break
    result = {'kind': 'engineering', 'title': 'do-mpc充电 + SOX EKF反馈 + Thevenin电热响应',
              'metrics': {'final_model_soc': rows[-1]['soc_model'], 'final_estimated_soc': rows[-1]['soc_ekf'],
                          'max_temperature_C': max(r['temperature_C'] for r in rows),
                          'max_voltage_V': max(r['voltage_V'] for r in rows),
                          'fallback_count': sum(r['fallback'] for r in rows),
                          'plant_violation_count': sum(e['kind'] == 'plant_limit_exceeded' for e in events)},
              'events': events, 'scope': '仿真闭环，控制器读取EKF估计SOC/极化和仿真测温。声明参数与约束下的工程算例；未连接充电设备，不保证模型失配时实物约束成立。'}
    result['controller_model_scope']='fixed operating-point RC controller/filter; SOC-table plant from a hash-verified adaptive parent' if cell.get('rc_table') else 'fixed operating-point RC controller/filter and plant'
    if plant_cell_override is not None:result['controller_model_scope']='research harness: fixed nominal controller/filter; independently perturbed simulated plant'
    result['stop_rule']='simulated plant SOC (research harness only)' if stop_on_model_soc else 'EKF estimated SOC'
    result['soc_feedback']='ideal simulated plant SOC (diagnostic only)' if ideal_soc_feedback else 'EKF estimated SOC'
    result['constraint_guards']={'voltage_guard_V':voltage_guard,'temperature_guard_C':temperature_guard,
                                 'plant_solver_rtol':1e-8,'plant_solver_atol':1e-10}
    return finish(config, out, result, rows,
                  [{'name': '端电压响应', 'y_label': '电压 (V)', 'primary': '电池模型',
                    'points': [[r['time_s'], r['voltage_V'], None] for r in rows]},
                   {'name': '充电控制动作', 'y_label': '充电电流 (A)', 'primary': 'MPC电流指令',
                    'points': [[r['time_s'], r['charge_A'], None] for r in rows]},
                   {'name': '温度响应', 'y_label': '温度 (°C)', 'primary': '仿真温度',
                    'points': [[r['time_s'], r['temperature_C'], None] for r in rows]},
                   {'name': 'SOC反馈', 'y_label': 'SOC (0–1)', 'primary': 'EKF估计', 'secondary': '仿真模型SOC',
                    'points': [[r['time_s'], r['soc_ekf'], r['soc_model']] for r in rows]}],
                  ['thevenin', 'sox', 'do-mpc', 'casadi'])

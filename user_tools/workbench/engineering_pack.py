"""Actual liionpack SPM pack calculation, no surrogate pack output."""
import numpy as np

from user_tools.workbench.engineering_common import finish, save


def run_pack(config, out, raw=None):
    import liionpack as lp
    import pybamm
    if raw is not None:
        raise ValueError('电池包入口当前使用明确串并联参数与恒流协议；自定义动态协议尚未开放。')
    ns, np_ = config['Ns'], config['Np']
    period, duration = config['period_s'], config['duration_s']
    if duration < 2 * period:
        raise ValueError('电池包时长至少为两个采样周期。')
    netlist = lp.setup_circuit(Np=np_, Ns=ns, Rb=1e-4, Rc=.002, Ri=.05, V=3.7, I=config['pack_current_A'])
    netlist.to_csv(out / 'pack_netlist.csv', index=False)
    parameters = pybamm.ParameterValues('Chen2020')
    experiment = pybamm.Experiment([f'Discharge at {config["pack_current_A"]} A for {duration} seconds'], period=f'{period} seconds')
    output = lp.solve(netlist=netlist, parameter_values=parameters, experiment=experiment,
                       initial_soc=config['cell']['initial_soc'], manager='casadi', nproc=1,
                       output_variables=['Volume-averaged cell temperature [K]'])
    # Keep library arrays for inspection, and normalize only display/export keys.
    save(out / 'pack_raw.json', {key: np.asarray(value).tolist() for key, value in output.items()})
    times = np.asarray(output['Time [s]']).ravel()
    pack_voltage = np.asarray(output['Pack terminal voltage [V]']).ravel()
    currents = np.asarray(output['Cell current [A]'])
    voltages = np.asarray(output['Terminal voltage [V]'])
    if len(times) != len(pack_voltage) or not np.isfinite(pack_voltage).all():
        raise RuntimeError('电池包输出形状或有限性不合法。')
    rows = [{'time_s': float(t), 'pack_voltage_V': float(v),
             'pack_current_A': float(np.asarray(output['Pack current [A]']).ravel()[i]),
             'all_cells_current_sum_A': float(np.sum(currents[i])),
             'kcl_residual_A': float(np.sum(currents[i])/ns-np.asarray(output['Pack current [A]']).ravel()[i]),
             'min_cell_voltage_V': float(np.min(voltages[i])),
             'max_cell_voltage_V': float(np.max(voltages[i]))} for i, (t, v) in enumerate(zip(times, pack_voltage))]
    result = {'kind': 'engineering', 'title': 'liionpack + PyBaMM串并联电池包',
              'metrics': {'series': ns, 'parallel': np_, 'cells': ns*np_, 'points': len(times),
                          'final_pack_voltage_V': float(pack_voltage[-1])},
              'parameter_set': 'Chen2020', 'connection_resistance_assumption_ohm': .002,
              'scope': '真实liionpack数值求解，使用Chen2020参考全电芯与显式连接阻抗。未校准用户电池包，当前不含主动均衡控制或实际热管理硬件。'}
    return finish(config, out, result, rows,
                  [{'name': '电池包电压', 'points': [[float(t), float(v), None] for t, v in zip(times, pack_voltage)]}],
                  ['liionpack', 'pybamm', 'casadi'])

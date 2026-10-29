"""Multi-SOC 1RC grouped fit through the installed PyBOP optimizer API."""
import numpy as np

from user_tools.workbench.engineering_common import finish, write_csv
from user_tools.workbench.engineering_contracts import csv_rows, finite


def run_joint_eis(config, out, raw=None):
    import pybop
    if raw is None:
        rows = []
        for soc in [.2, .5, .8]:
            for frequency in np.logspace(-3, 4, 45):
                resistance = .025 * np.exp(.8 * (soc - .5))
                z = .012 + resistance / (1 + 2j * np.pi * frequency * resistance * 1500)
                rows.append({'soc': soc, 'frequency_Hz': frequency, 'Z_real_ohm': z.real,
                             'Z_imag_ohm': z.imag, 'role': 'test' if soc == .5 else 'train'})
    else:
        rows = csv_rows(raw)
    temperature = finite(config.get('measurement_temperature_C', config['cell']['temperature_C'] if config['data_origin']=='synthetic' else None),
                         'measurement_temperature_C', -30, 60)
    required = {'soc', 'frequency_Hz', 'Z_real_ohm', 'Z_imag_ohm', 'role'}
    if not required <= set(rows[0]):
        raise ValueError('联合EIS需soc,frequency_Hz,Z_real_ohm,Z_imag_ohm,role(train/test)。')
    dataset = []
    identities, soc_roles = set(), {}
    for row in rows:
        if row.get('temperature_C') not in (None, '') and abs(finite(row['temperature_C'],'temperature_C')-temperature)>1e-6:
            raise ValueError('本版联合RC辨识需同一声明温度，不能混合不同温度的谱。')
        point = {key: finite(row[key], key) for key in required - {'role'}}
        if not 0 <= point['soc'] <= 1 or point['frequency_Hz'] <= 0 or row['role'] not in ['train', 'test']:
            raise ValueError('SOC、正频率或train/test角色不合法。')
        identity = (point['soc'], point['frequency_Hz'])
        if identity in identities:
            raise ValueError('同SOC存在重复频率；请先拆分测量。')
        identities.add(identity)
        if point['soc'] in soc_roles and soc_roles[point['soc']] != row['role']:
            raise ValueError('同一SOC不得跨拟合与留出集合。')
        soc_roles[point['soc']] = row['role']
        dataset.append({**point, 'role': row['role']})
    train = [r for r in dataset if r['role'] == 'train']
    test = [r for r in dataset if r['role'] == 'test']
    if len({r['soc'] for r in train}) < 2 or len(train) < 24 or not test:
        raise ValueError('至少两个训练SOC、24个训练频点和一个独立留出SOC。')
    f = np.array([r['frequency_Hz'] for r in train])
    soc = np.array([r['soc'] for r in train])
    observed = np.array([complex(r['Z_real_ohm'], r['Z_imag_ohm']) for r in train])
    weights = np.abs(observed)
    if np.any(weights <= 0):
        raise ValueError('阻抗模值必须为正。')
    # Training spectra only: estimate high-frequency intercept, low-frequency
    # branch span, SOC trend, and the RC peak. A zero-slope Nelder-Mead simplex
    # otherwise starts with an extremely short slope edge and can stall.
    groups = []
    for value in sorted(set(soc)):
        indices = np.flatnonzero(soc == value)
        groups.append((value, f[indices], observed[indices]))
    r0_guess = max(1e-6, float(np.median([z[np.argmax(freq)].real for _, freq, z in groups])))
    resistances = np.array([max(1e-6, float(np.max(z.real))-r0_guess) for _, _, z in groups])
    slope, intercept = np.polyfit(np.array([g[0] for g in groups])-.5, np.log(resistances), 1)
    capacitances = [1/(2*np.pi*freq[np.argmax(np.abs(z.imag))]*resistance)
                    for (_, freq, z), resistance in zip(groups, resistances)]
    initial = [float(np.log(r0_guess)), float(intercept), float(np.log(np.median(capacitances))), float(np.clip(slope, -7, 7))]
    names = ['log_R0', 'log_R1', 'log_C1', 'soc_slope']
    bounds = [(-12, 2), (-12, 2), (-3, 18), (-8, 8)]
    params = pybop.Parameters({name: pybop.Parameter(initial_value=float(v), bounds=b)
                               for name, v, b in zip(names, initial, bounds)})

    def impedance(inputs, frequencies, socs):
        r0, r1, c1 = np.exp([inputs[name] for name in names[:3]])
        resistance = r1 * np.exp(inputs['soc_slope'] * (socs - .5))
        return r0 + resistance / (1 + 2j * np.pi * frequencies * resistance * c1)

    class GroupedRC(pybop.BaseSimulator):
        def __init__(self):
            super().__init__(params)

        def set_output_variables(self, target):
            self.target = target

        def solve_batch(self, inputs, calculate_sensitivities=False):
            solutions = []
            for values in inputs:
                z = impedance(values, f, soc) / weights
                solution = pybop.Solution(values)
                solution.set_solution_variable('Z_scaled', np.r_[z.real, z.imag])
                solutions.append(solution)
            return solutions

    cost = pybop.SumSquaredError(pybop.Dataset({'index': np.arange(2 * len(train)),
                           'Z_scaled': np.r_[observed.real / weights, observed.imag / weights]}, domain='index'), target='Z_scaled')
    problem = pybop.Problem(GroupedRC(), cost)
    optimizer = pybop.SciPyMinimize(problem, options=pybop.SciPyMinimizeOptions(method='Nelder-Mead', maxiter=1500, verbose=False))
    fit = optimizer.run()
    values = params.to_dict(np.asarray(fit.x).ravel())
    output = []
    for row in dataset:
        predicted = impedance(values, np.array([row['frequency_Hz']]), np.array([row['soc']]))[0]
        measured = complex(row['Z_real_ohm'], row['Z_imag_ohm'])
        output.append({**row, 'fit_real_ohm': float(predicted.real), 'fit_imag_ohm': float(predicted.imag),
                       'abs_error_ohm': float(abs(predicted - measured))})
    parameter_rows = [{'soc': value, 'temperature_C': temperature,
                       'R0_ohm': float(np.exp(values['log_R0'])),
                       'R1_ohm': float(np.exp(values['log_R1'] + values['soc_slope'] * (value - .5))),
                       'C1_F': float(np.exp(values['log_C1']))} for value in sorted(soc_roles)]
    write_csv(out / 'parameters.csv', parameter_rows)
    metrics = {role + '_rmse_complex_ohm': float(np.sqrt(np.mean([r['abs_error_ohm']**2 for r in output if r['role'] == role])))
               for role in ['train', 'test']}
    result = {'kind': 'engineering', 'title': 'PyBOP多SOC联合1RC辨识与留出', 'metrics': metrics,
              'parameters': parameter_rows, 'parameter_model': 'R0 constant; R1(soc)=R1_50*exp(beta*(soc-.5)); C1 constant',
              'fitted_inputs': values, 'optimizer': 'PyBOP 26.3 SciPyMinimize/Nelder-Mead',
              'initial_inputs_training_only': dict(zip(names, initial)),
              'parameter_identifiability': 'not_assessed',
              'scope': '多SOC共享电路参数的PyBOP适配；留出SOC不参与拟合。参数仍是等效电路量，未复现文献18参数SPMe物理辨识，未据此赋予材料机制。'}
    return finish(config, out, result, output, packages=['pybop', 'numpy', 'scipy'])

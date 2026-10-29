"""Optional impedance.py adapter. Circuit parameters remain local diagnostics."""
from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import warnings

from user_tools.workbench.paper_methods import read_eis


CIRCUITS = {'1rc': 'R0-p(R1,C1)', '2rc': 'R0-p(R1,C1)-p(R2,C2)'}


def prepare_eis_fit(raw, config):
    """Validate before queuing; no scientific dependencies on the UI host."""
    config = config or {}
    imported = read_eis(raw, config)
    spectra = imported['eis_spectra']
    selected = str(config.get('spectrum_id') or '').strip()
    if not selected and len(spectra) != 1:
        raise ValueError('多条谱必须明确填写 spectrum_id，每次拟合一条谱。')
    spectrum = next((s for s in spectra if s['name'] == selected), None) if selected else spectra[0]
    if spectrum is None:
        raise ValueError('找不到指定的 spectrum_id。')
    points = spectrum['points']
    if not 12 <= len(points) <= 2000:
        raise ValueError('拟合每条谱需要12–2000个频率点；请显式拆分，程序不抽点。')
    if len({p['frequency_Hz'] for p in points}) != len(points):
        raise ValueError('拟合谱存在重复频率，请分别标注 spectrum_id；程序不自动平均。')
    if any(p['magnitude_ohm'] <= 0 for p in points):
        raise ValueError('阻抗模值必须大于零，才能计算归一残差。')
    circuit = config.get('circuit', '1rc')
    weighting = config.get('weighting', 'modulus')
    if circuit not in CIRCUITS or weighting not in ('modulus', 'uniform'):
        raise ValueError('电路只支持1rc/2rc，权重只支持modulus/uniform。')
    kk_mode = config.get('kk_mode', 'fixed')
    if kk_mode not in ('fixed', 'automatic'):
        raise ValueError('Lin-KK阶数策略只支持fixed/automatic。')
    tolerance = float(config.get('kk_tolerance', .02))
    if not math.isfinite(tolerance) or not .0001 <= tolerance <= .2:
        raise ValueError('Lin-KK归一残差阈值需在0.0001–0.2之间。')
    guess = config.get('initial_guess')
    if guess is not None:
        if not isinstance(guess, list) or len(guess) != (3 if circuit == '1rc' else 5):
            raise ValueError('初值按R0,R1,C1[,R2,C2]填写3或5个数（Ω、F）。')
        guess = [float(v) for v in guess]
        if not all(math.isfinite(v) and v > 0 for v in guess):
            raise ValueError('拟合初值必须为有限正数。')
    return {'spectrum_id': spectrum['name'], 'points': points,
            'source_sha256': imported['source_sha256'], 'input_mapping': imported['mapping'],
            'declared_frequency_unit': imported['declared_frequency_unit'],
            'declared_impedance_unit': imported['declared_impedance_unit'],
            'imag_sign_converted': imported['imag_sign_converted'],
            'warnings': imported['warnings'], 'circuit': circuit,
            'weighting': weighting, 'kk_mode': kk_mode, 'kk_tolerance': tolerance, 'initial_guess': guess}


def _csv(path, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run_eis_fit(config, out):
    import numpy as np
    import scipy
    import impedance.validation as validation
    from impedance.models.circuits import CustomCircuit
    from impedance.models.circuits import fitting, elements

    raw = Path(config['source_path']).read_bytes()
    if hashlib.sha256(raw).hexdigest() != config['source_sha256']:
        raise ValueError('EIS原始文件校验失败，文件在提交后发生变化。')
    packet = prepare_eis_fit(raw, config['eis_config'])
    points = packet['points']
    f = np.array([p['frequency_Hz'] for p in points])
    z = np.array([complex(p['Z_real_ohm'], p['Z_imag_ohm']) for p in points])
    notes = list(packet['warnings'])
    guess = packet['initial_guess']
    if guess is None:
        r0 = max(float(np.min(z.real)), float(np.max(np.abs(z))) * 1e-6)
        resistance = max(float(np.ptp(z.real)), float(np.max(np.abs(z))) * .1)
        peak_f = float(f[np.argmax(-z.imag)])
        tau = 1 / (2 * np.pi * peak_f)
        guess = [r0, resistance, tau / resistance] if packet['circuit'] == '1rc' else [
            r0, resistance / 2, tau / 10 / (resistance / 2),
            resistance / 2, tau * 10 / (resistance / 2)]
    model = CustomCircuit(CIRCUITS[packet['circuit']], initial_guess=guess)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        model.fit(f, z, weight_by_modulus=packet['weighting'] == 'modulus',
                  bounds=([1e-15] * len(guess), [np.inf] * len(guess)),
                  method='trf', x_scale='jac', maxfev=5000, ftol=1e-10)
        fitted = model.predict(f)
        notes.extend(str(w.message) for w in caught)
    if not np.isfinite(model.parameters_).all() or not np.isfinite(fitted).all():
        raise RuntimeError('等效电路拟合产生非有限结果。')
    names, units = model.get_param_names()
    errors = model.conf_ if model.conf_ is not None else [None] * len(names)
    parameters = [{'name': name, 'value': float(value), 'unit': unit,
                   'local_std_error': float(error) if error is not None and np.isfinite(error) else None}
                  for name, unit, value, error in zip(names, units, model.parameters_, errors)]
    delta = fitted - z
    normalized = delta / np.abs(z)
    kk_z = None
    automatic = packet['kk_mode'] == 'automatic'
    kk = {'status': 'failed', 'tolerance': packet['kk_tolerance'], 'fit_type': 'complex',
          'order_selection': packet['kk_mode'], 'cutoff_c': .85 if automatic else None,
          'max_M': min(30, len(f) // 2) if automatic else min(20, len(f) // 3), 'add_cap': False,
          'scope': '有限频带Lin-KK残差诊断；固定阶数与自动mu截止都可能欠/过拟合，需联合查看残差、mu和频带。'
                   '阈值是用户选择，不证明线性、稳态或材料机制。'}
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            # impedance 1.7.1 serializes NumPy scalars into eval expressions.
            # NumPy 2 renders these as np.float64(...). Supply the missing
            # namespace only for this call; keep the installed package intact.
            missing_np = 'np' not in validation.circuit_elements
            if missing_np:
                validation.circuit_elements['np'] = np
            try:
                m, mu, kk_z, rr, ri = validation.linKK(f, z, c=kk['cutoff_c'], max_M=kk['max_M'], fit_type='complex')
            finally:
                if missing_np:
                    validation.circuit_elements.pop('np', None)
            notes.extend(str(w.message) for w in caught)
        if not all(np.isfinite(v).all() for v in [kk_z, rr, ri]) or not np.isfinite(mu):
            raise ValueError('Lin-KK产生非有限结果。')
        rms = float(np.sqrt(np.mean(np.asarray(rr)**2 + np.asarray(ri)**2)))
        kk.update(status='within_tolerance' if rms <= kk['tolerance'] else 'above_tolerance',
                  M=int(m), mu=float(mu), relative_rms=rms,
                  relative_max=float(np.max(np.hypot(rr, ri))),
                  cutoff_reached=bool(mu <= .85) if automatic else None)
        if automatic and mu > .85:
            notes.append('Lin-KK达到元件数上限，未达到mu截止条件；请检查频率覆盖与残差。')
    except (ValueError, np.linalg.LinAlgError, FloatingPointError) as exc:
        kk_z = None
        kk.update(error=str(exc))
        notes.append('Lin-KK未完成；电路拟合不替代谱质量诊断。')

    def curve(label, values):
        return {'name': label, 'points': [dict(frequency_Hz=float(fi), Z_real_ohm=float(zi.real),
                Z_imag_ohm=float(zi.imag), magnitude_ohm=float(abs(zi)),
                phase_deg=float(np.degrees(np.angle(zi)))) for fi, zi in zip(f, values)]}

    spectra = [curve(packet['spectrum_id'] + ' · 输入谱', z), curve('RC电路拟合', fitted)]
    if kk_z is not None:
        spectra.append(curve('Lin-KK重构', kk_z))
    rows = [dict(frequency_Hz=float(fi), Z_real_ohm=float(zi.real), Z_imag_ohm=float(zi.imag),
                 fit_real_ohm=float(pi.real), fit_imag_ohm=float(pi.imag),
                 residual_real_ohm=float(di.real), residual_imag_ohm=float(di.imag),
                 relative_residual_real=float(ni.real), relative_residual_imag=float(ni.imag),
                 kk_real_ohm=float(kk_z[i].real) if kk_z is not None else None,
                 kk_imag_ohm=float(kk_z[i].imag) if kk_z is not None else None)
            for i, (fi, zi, pi, di, ni) in enumerate(zip(f, z, fitted, delta, normalized))]
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    _csv(out / 'spectrum_fit.csv', rows)
    _csv(out / 'parameters.csv', parameters)
    source_files = [Path(__file__), Path(__file__).with_name('paper_methods.py'),
                    Path(validation.__file__), Path(fitting.__file__), Path(elements.__file__)]
    result = {'kind': 'eis_fit', 'evidence_type': 'user_eis_circuit_diagnostic',
              'engine': 'impedance.py', 'repository': 'https://github.com/ECSHackWeek/impedance.py',
              'compatibility': 'impedance-1.7.1 Lin-KK temporary NumPy 2 scalar-eval namespace',
              'runtime_versions': {**{p: importlib.metadata.version(p) for p in ('impedance', 'altair')},
                                   'numpy': np.__version__, 'scipy': scipy.__version__},
              'code_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files},
              'source_sha256': packet['source_sha256'], 'spectrum_id': packet['spectrum_id'],
              'input_mapping': packet['input_mapping'], 'declared_frequency_unit': packet['declared_frequency_unit'],
              'declared_impedance_unit': packet['declared_impedance_unit'],
              'imag_sign_converted': packet['imag_sign_converted'], 'point_count': len(f),
              'frequency_min_Hz': float(f.min()), 'frequency_max_Hz': float(f.max()),
              'circuit': model.circuit, 'initial_guess': guess, 'weighting': packet['weighting'],
              'parameters': parameters, 'rmse_complex_ohm': float(np.sqrt(np.mean(np.abs(delta)**2))),
              'relative_rms': float(np.sqrt(np.mean(np.abs(normalized)**2))), 'lin_kk': kk,
              'eis_spectra': spectra, 'warnings': list(dict.fromkeys(notes)),
              'linearity_assessed': False, 'stationarity_assessed': False,
              'parameter_identifiability': 'not_assessed', 'material_validation': False,
              'scope': '固定工况下1RC/2RC局部等效电路诊断。误差为同谱拟合误差；局部标准误不是独立验证。'
                       'RC支路不能自动命名为电荷转移过程，参数不写入PyBaMM材料参数；'
                       '用于BMS前需SOC/温度网格、OCV/容量、脉冲留出验证和估计算法。'}
    for name, value in [('result.json', result), ('ui_result.json', {'result': result, 'curves': []})]:
        (out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    return result

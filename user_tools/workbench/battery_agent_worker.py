"""Use the established measured-data replay kernel, with a fixed score window."""
import hashlib
from pathlib import Path
import numpy as np
from user_tools.workbench.battery_agent import CASES, PARAMETERS, normalize, explore, llm_proposer


def run_agent(config, out):
    import pybamm
    from battery_sim.registry import get_dataset
    from battery_sim.models.pybamm_factory import load_parameter_values, resolve_model_options
    from battery_sim.simulation.baseline import _run_one_replay, _filter_and_downsample
    from governance.dataset_roles import assert_calibration_allowed
    from user_tools.rg_loop.physics import save
    settings = normalize(config['agent_config']); out = Path(out); out.mkdir(parents=True, exist_ok=True)
    dataset, cell, rate, parameter_set = CASES[settings['case']]
    warnings = assert_calibration_allowed(dataset, rate, what='bounded agent exploration')
    adapter = get_dataset(dataset)
    frame = adapter.load_processed_discharge(cell, rate)
    t, _, observed = _filter_and_downsample(frame['time_s'].to_numpy(float),
        frame['current_A'].to_numpy(float), frame['voltage_V'].to_numpy(float))
    end = t[0] + .98 * (t[-1] - t[0]); mask = t <= end
    t, observed = t[mask], observed[mask]
    if len(t) < 5 or not np.isfinite(observed).all():
        raise ValueError('固定比较窗口缺少有效观测。')
    pv = load_parameter_values(parameter_set); options = resolve_model_options(adapter)
    originals = {alias: pv[PARAMETERS[alias]] for alias in settings['bounds']}
    frame.to_csv(out / 'observations.csv', index=False)
    def evaluate(values, folder):
        folder.mkdir(parents=True, exist_ok=True); overrides = {}
        for alias, z in values.items():
            ref = originals[alias]; multiplier = 10 ** z
            if callable(ref):
                def scaled(*args, _ref=ref, _m=multiplier):
                    return _m * _ref(*args)
                scaled.__name__ = f'agent_{alias}_{z:+.6f}'
                overrides[PARAMETERS[alias]] = scaled
            else:
                overrides[PARAMETERS[alias]] = float(ref) * multiplier
        sources = {PARAMETERS[k]: {'source': 'bounded agent candidate', 'log_multiplier': z} for k, z in values.items()}
        replay = _run_one_replay(frame, config.get('model', 'SPM'), parameter_set, options, overrides, sources)
        ts = np.asarray(replay['_t_common'], float); vs = np.asarray(replay['_V_sim_common'], float)
        if len(ts) < 2 or not np.isfinite(ts).all() or not np.isfinite(vs).all() or not (np.diff(ts) > 0).all():
            raise ValueError('无有效模拟曲线。')
        if t[0] < ts[0] - 1e-9 or t[-1] > ts[-1] + 1e-9:
            save(folder / 'rejected.json', {'reason': 'incomplete_fixed_window', 'coverage': replay.get('coverage_fraction')})
            raise ValueError('候选未覆盖固定比较窗口。')
        predicted = np.interp(t, ts, vs); residual = (predicted - observed) * 1000
        stages = []
        for i, idx in enumerate(np.array_split(np.arange(len(t)), 3)):
            stages.append({'stage': ('early', 'middle', 'late')[i],
                           'rmse_mV': float(np.sqrt(np.mean(residual[idx] ** 2))),
                           'bias_mV': float(np.mean(residual[idx])),
                           'time_start_s': float(t[idx[0]]), 'time_end_s': float(t[idx[-1]])})
        worst = max(stages, key=lambda r: r['rmse_mV'])
        result = {'rmse_mV': float(np.sqrt(np.mean(residual ** 2))),
                  'bias_mV': float(np.mean(residual)), 'max_abs_error_mV': float(np.max(np.abs(residual))),
                  'coverage': float(replay['coverage_fraction']), 'stages': stages,
                  'diagnostic': f"最大阶段误差位于{worst['stage']}；模拟电压总体{'偏高' if np.mean(residual)>0 else '偏低'}。此差异不能唯一归因于某个参数。",
                  'comparison_points': len(t), 'comparison_window_fully_covered': True}
        np.savetxt(folder / 'curve.csv', np.c_[t, observed, predicted], delimiter=',',
                   header='time_s,voltage_exp_V,voltage_sim_V', comments='')
        save(folder / 'diagnostic.json', result)
        return result
    proposer = None; llm_meta = None
    if settings['strategy'] == 'llm':
        proposer, llm_meta = llm_proposer(Path(__file__).resolve().parents[2] / 'data/agent_llm.local.json')
    result = explore(settings, evaluate, out, proposer)
    result.update(dataset=dataset, cell=cell, rate=rate, parameter_set=parameter_set, model=config.get('model', 'SPM'),
                  governance_warnings=warnings, comparison_fraction=.98, comparison_end_s=float(t[-1]),
                  all_candidates_use_same_comparison_points=True, parameter_keys={k: PARAMETERS[k] for k in settings['bounds']},
                  pybamm_version=pybamm.__version__, llm=llm_meta,
                  observations_sha256=hashlib.sha256((out / 'observations.csv').read_bytes()).hexdigest(),
                  code_sha256={name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
                               for name in ('battery_agent.py', 'battery_agent_worker.py')})
    import battery_sim.simulation.baseline as replay_module
    import user_tools.rg_loop.physics as physics_module
    result['code_sha256'].update({name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                                 for name, module in [('replay_kernel', replay_module), ('physics', physics_module)]})
    curves = []
    if result['best']:
        curve = np.genfromtxt(out / f"round_{result['best']['round']:02d}" / 'curve.csv', delimiter=',', names=True)
        curves = [{'name': '最佳候选与实测', 'points': [[float(r['time_s']), float(r['voltage_sim_V']), float(r['voltage_exp_V'])]
                   for r in curve[::max(1, len(curve) // 500)]]}]
    save(out / 'result.json', result); save(out / 'ui_result.json', {'result': result, 'curves': curves})
    return result

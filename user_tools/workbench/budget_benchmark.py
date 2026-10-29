"""Predeclared finite ASC replay: resource budgets, honest baselines and ablations.

The selector only receives observed labels. Evaluator-owned historical means
are released after persisting each recommendation. Costs are explicit scenarios.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import platform
import time

import numpy as np
from scipy.stats import norm

from user_tools.rg_loop.public_graphite import read_asc, features, write_csv
from user_tools.workbench.ml_worker import fit_bundle, predict_bundle

POLICIES = ['random', 'doe_maximin', 'gp_ei', 'cost_gp_ei', 'gp_ucb',
            'dynamic_gp_ei', 'dynamic_gp_ucb']
SCENARIOS = ['equal_test_count', 'calendering_extra_50pct', 'independent_cost_sensitivity']
NUMERIC = ['coating_speed_m_min', 'coating_gap_um', 'graphite_dry_pct',
           'carbon_dry_pct', 'cmc_dry_pct', 'sbr_dry_pct', 'calendered']
INPUTS = NUMERIC + ['drying_temperature_label']
FIELDS = [{'key': k, 'label': k, 'kind': 'numeric' if k in NUMERIC else 'categorical',
           'stage': 'process'} for k in INPUTS]
LABELS = {'random': 'Random', 'doe_maximin': 'Maximin DOE', 'gp_ei': 'Fixed GP / EI',
          'cost_gp_ei': 'Fixed GP / EI per cost', 'gp_ucb': 'Fixed GP / UCB',
          'dynamic_gp_ei': 'Dynamic features / EI', 'dynamic_gp_ucb': 'Dynamic features / UCB'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def scenario_cost(row, scenario):
    if scenario == 'equal_test_count':
        return 1.
    if scenario == 'calendering_extra_50pct':
        return 1. + .5 * float(row['calendered'])
    if scenario == 'independent_cost_sensitivity':
        code = int(hashlib.sha256(('20261014:' + row['record_id']).encode()).hexdigest()[:8], 16)
        return [1., 1.5, 2.][code % 3]
    raise ValueError('Unknown cost scenario')


def affordable(candidates, remaining):
    return [r for r in candidates if float(r['cost_units']) <= remaining + 1e-10]


def expected_improvement(mu, sd, incumbent):
    mu = np.asarray(mu, dtype=float)
    sd = np.asarray(sd, dtype=float)
    positive = sd > 1e-12
    result = np.maximum(mu - incumbent, 0.)
    z = np.zeros_like(mu)
    z[positive] = (mu[positive] - incumbent) / sd[positive]
    result[positive] = ((mu[positive] - incumbent) * norm.cdf(z[positive])
                        + sd[positive] * norm.pdf(z[positive]))
    return np.maximum(result, 0.)


def doe_order(candidates, initial_ids):
    """Freeze a maximin sequence using known inputs only, before revealing labels."""
    x, _ = features(candidates)
    by_id = {r['record_id']: i for i, r in enumerate(candidates)}
    seen = [by_id[k] for k in initial_ids]
    order = []
    remaining = [i for i in range(len(candidates)) if i not in seen]
    while remaining:
        distance = np.linalg.norm(x[remaining, None] - x[None, seen], axis=2).min(axis=1)
        pick = remaining[int(np.argmax(distance))]
        order.append(candidates[pick]['record_id'])
        seen.append(pick)
        remaining.remove(pick)
    return order


def select_action(observed, candidates, policy, *, seed, step, threshold, order=()):
    if not candidates or any('target' in r for r in candidates):
        raise ValueError('Selection needs nonempty candidates without hidden labels')
    if policy not in POLICIES:
        raise ValueError('Unknown policy')
    if policy == 'random':
        ix = int(np.random.default_rng(seed * 1009 + step).integers(len(candidates)))
        return candidates[ix]['record_id'], None
    if policy == 'doe_maximin':
        available_ids = {r['record_id'] for r in candidates}
        chosen = next(k for k in order if k in available_ids)
        return chosen, None
    config = {'features': INPUTS, 'selector': 'spearman' if policy.startswith('dynamic') else 'manual',
              'top_k': 3, 'noise_fraction': .05}
    model = fit_bundle(observed, FIELDS, config, 'gp')
    mu, sd = predict_bundle(model, candidates, std=True)
    if not np.isfinite(mu).all() or not np.isfinite(sd).all():
        raise ValueError('Nonfinite GP prediction')
    ei = expected_improvement(mu, sd, max(r['target'] for r in observed))
    score = mu + 2 * sd if policy.endswith('ucb') else ei
    if policy == 'cost_gp_ei':
        score = score / np.array([r['cost_units'] for r in candidates])
    ix = int(np.argmax(score))
    sigma = float(sd[ix])
    probability = float(norm.cdf((mu[ix] - threshold) / max(sigma, 1e-12)))
    forecast = {'mean': float(mu[ix]), 'latent_sd': sigma, 'probability_above_threshold': probability,
                'declares_by_mean': bool(mu[ix] >= threshold), 'posterior_probability_ge_0p9': probability >= .9,
                'selected_features': model['selected'], 'acquisition': float(score[ix]),
                'calibrated': False, 'scope': 'Conditional fixed-kernel GP; not validated material coverage'}
    return candidates[ix]['record_id'], forecast


def one_campaign(rows, policy, scenario, *, seed, budget, threshold, decisions):
    truth = {r['record_id']: float(r['target']) for r in rows}  # Evaluator only.
    candidates = [{k: v for k, v in r.items() if k != 'target'} for r in rows]
    for row in candidates:
        row['cost_units'] = scenario_cost(row, scenario)
    by_id = {r['record_id']: r for r in candidates}
    initial = np.random.default_rng(seed).choice(len(rows), 5, replace=False).tolist()
    initial_ids = [rows[i]['record_id'] for i in initial]
    order = doe_order(candidates, initial_ids) if policy == 'doe_maximin' else []
    spent = sum(by_id[k]['cost_units'] for k in initial_ids)
    if spent > budget + 1e-10:
        raise ValueError('Shared initial design exceeds total budget')
    observed = [{**by_id[k], 'target': truth[k]} for k in initial_ids]
    seen = set(initial_ids)
    best = max(r['target'] for r in observed)
    hit_cost = spent if best >= threshold else None
    traces = [{'scenario': scenario, 'seed': seed, 'policy': policy, 'cost_units': spent,
               'conditions_observed': len(observed), 'best_D5_mAh_g': best}]
    mean_calls = mean_errors = confident_calls = confident_errors = 0
    step = 0
    while True:
        pool = affordable([r for r in candidates if r['record_id'] not in seen], budget - spent)
        if not pool:
            break
        chosen, forecast = select_action(observed, pool, policy, seed=seed, step=step,
                                         threshold=threshold, order=order)
        record = {'scenario': scenario, 'seed': seed, 'policy': policy, 'step': step,
                  'spent_before': spent, 'remaining_before': budget - spent,
                  'initial_ids': initial_ids, 'observed_ids': [r['record_id'] for r in observed],
                  'observed_payload_sha256': digest(observed), 'candidate_payload_sha256': digest(pool),
                  'candidate_payload_has_target': False, 'selected_id': chosen,
                  'selected_cost_units': by_id[chosen]['cost_units'], 'forecast': forecast}
        decisions.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + '\n')
        decisions.flush()  # Persist recommendation before releasing historical outcome.
        outcome = truth[chosen]
        spent += by_id[chosen]['cost_units']
        if spent > budget + 1e-10:
            raise AssertionError('Budget exceeded')
        observed.append({**by_id[chosen], 'target': outcome})
        seen.add(chosen)
        best = max(best, outcome)
        if hit_cost is None and outcome >= threshold:
            hit_cost = spent
        if forecast:
            if forecast['declares_by_mean']:
                mean_calls += 1
                mean_errors += int(outcome < threshold)
            if forecast['posterior_probability_ge_0p9']:
                confident_calls += 1
                confident_errors += int(outcome < threshold)
        traces.append({'scenario': scenario, 'seed': seed, 'policy': policy, 'cost_units': spent,
                       'conditions_observed': len(observed), 'best_D5_mAh_g': best,
                       'selected_id': chosen, 'revealed_D5_mAh_g': outcome,
                       'prediction_mean': forecast['mean'] if forecast else None})
        step += 1
    # Reference uses revealed measurements only; no new material truth claim.
    final = {'scenario': scenario, 'seed': seed, 'policy': policy, 'budget_units': budget,
             'spent_units': spent, 'unused_budget_units': budget - spent,
             'conditions_observed': len(observed), 'initial_ids': ';'.join(initial_ids),
             'selected_ids': ';'.join(r['record_id'] for r in observed), 'best_D5_mAh_g': best,
             'hit': hit_cost is not None, 'first_historical_hit_cost_units': hit_cost,
             'budget_restricted_hit_cost_units': hit_cost if hit_cost is not None else budget,
             'right_censored': hit_cost is None, 'mean_calls': mean_calls, 'mean_errors': mean_errors,
             'posterior_0p9_calls': confident_calls, 'posterior_0p9_errors': confident_errors}
    return final, traces


def paired_statistics(values, reference, seed=20261014):
    delta = np.asarray(values, dtype=float) - np.asarray(reference, dtype=float)
    if len(delta) < 2:
        raise ValueError('At least two paired seeds required')
    boot = np.random.default_rng(seed).choice(delta, size=(4000, len(delta)), replace=True).mean(axis=1)
    lo, hi = np.quantile(boot, [.025, .975])
    return {'paired_mean': float(delta.mean()), 'paired_standard_error': float(delta.std(ddof=1) / np.sqrt(len(delta))),
            'bootstrap_95_lower': float(lo), 'bootstrap_95_upper': float(hi),
            'wins': int(np.sum(delta > 1e-9)), 'ties': int(np.sum(np.abs(delta) <= 1e-9)),
            'losses': int(np.sum(delta < -1e-9))}


def summaries(campaigns, seeds):
    output = []
    for scenario in SCENARIOS:
        grouped = {policy: sorted([r for r in campaigns if r['scenario'] == scenario and r['policy'] == policy],
                                  key=lambda r: r['seed']) for policy in POLICIES}
        baseline = np.array([r['best_D5_mAh_g'] for r in grouped['random']])
        for policy, records in grouped.items():
            values = np.array([r['best_D5_mAh_g'] for r in records])
            mean_calls = sum(r['mean_calls'] for r in records)
            confident_calls = sum(r['posterior_0p9_calls'] for r in records)
            stats = paired_statistics(values, baseline)
            output.append({'scenario': scenario, 'policy': policy, 'seeds': seeds,
                           'mean_best_D5_mAh_g': float(values.mean()), 'std_best_D5_mAh_g': float(values.std(ddof=1)),
                           **{'vs_random_' + k: v for k, v in stats.items()},
                           'historical_hit_fraction': float(np.mean([r['hit'] for r in records])),
                           'mean_restricted_hit_cost_units': float(np.mean([r['budget_restricted_hit_cost_units'] for r in records])),
                           'mean_actual_spent_units': float(np.mean([r['spent_units'] for r in records])),
                           'mean_conditions_observed': float(np.mean([r['conditions_observed'] for r in records])),
                           'mean_call_count': mean_calls, 'mean_call_error_count': sum(r['mean_errors'] for r in records),
                           'mean_call_error_fraction': sum(r['mean_errors'] for r in records) / mean_calls if mean_calls else None,
                           'posterior_0p9_call_count': confident_calls,
                           'posterior_0p9_error_fraction': sum(r['posterior_0p9_errors'] for r in records) / confident_calls if confident_calls else None})
    ablations = []
    for scenario in SCENARIOS:
        def values(policy):
            return [r['best_D5_mAh_g'] for r in sorted(campaigns, key=lambda r: r['seed'])
                    if r['scenario'] == scenario and r['policy'] == policy]
        for proposed, reference in [('dynamic_gp_ei', 'gp_ei'), ('dynamic_gp_ucb', 'gp_ucb'), ('cost_gp_ei', 'gp_ei')]:
            ablations.append({'scenario': scenario, 'policy': proposed, 'reference': reference,
                              **paired_statistics(values(proposed), values(reference))})
    return output, ablations


def render(result, out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size': 9, 'axes.spines.top': False, 'axes.spines.right': False})
    colors = ['#7e8796', '#15998f', '#e58b36', '#8559b6', '#bc596c', '#2875b9', '#1b466b']
    fig, axs = plt.subplots(2, 2, figsize=(14, 9), constrained_layout=True)
    fig.suptitle('ASC graphite | finite historical replay under shared resource budgets', fontsize=14, weight='bold')
    for policy, color in zip(POLICIES, colors):
        rows = [r for r in result['traces'] if r['scenario'] == 'equal_test_count' and r['policy'] == policy]
        by = defaultdict(list)
        for row in rows:
            by[int(row['conditions_observed'])].append(row['best_D5_mAh_g'])
        xs = sorted(by)
        mean = np.array([np.mean(by[x]) for x in xs])
        se = np.array([np.std(by[x], ddof=1) / np.sqrt(len(by[x])) for x in xs])
        axs[0, 0].plot(xs, mean, color=color, lw=1.6, label=LABELS[policy])
        axs[0, 0].fill_between(xs, mean-se, mean+se, color=color, alpha=.07)
    axs[0, 0].set(xlabel='Conditions observed (unit cost)', ylabel='Best historical D5 (mAh/g)',
                  title=f"A  Equal test count | {result['config']['seeds']} seeds | shading: +/-1 SE")
    axs[0, 0].legend(frameon=False, fontsize=7, ncol=2)
    equal = [r for r in result['summary'] if r['scenario'] == 'equal_test_count' and r['policy'] != 'random']
    for i, row in enumerate(equal):
        mu = row['vs_random_paired_mean']
        axs[0, 1].errorbar(mu, i, xerr=[[mu-row['vs_random_bootstrap_95_lower']],
                                      [row['vs_random_bootstrap_95_upper']-mu]],
                           fmt='o', color=colors[POLICIES.index(row['policy'])], capsize=3)
    axs[0, 1].axvline(0, color='#777', ls='--', lw=.8)
    axs[0, 1].set(yticks=range(len(equal)), yticklabels=[LABELS[r['policy']] for r in equal],
                  xlabel='Paired final D5 difference from random (mAh/g)',
                  title='B  Bootstrap 95% intervals | conditional on this pool')
    axs[0, 1].invert_yaxis()
    matrix = np.array([[next(r['vs_random_paired_mean'] for r in result['summary'] if r['scenario'] == s and r['policy'] == p)
                        for p in POLICIES] for s in SCENARIOS])
    limit = max(1., float(np.abs(matrix).max()))
    im = axs[1, 0].imshow(matrix, cmap='RdBu', vmin=-limit, vmax=limit, aspect='auto')
    for i in range(len(SCENARIOS)):
        for j in range(len(POLICIES)):
            axs[1, 0].text(j, i, f'{matrix[i,j]:+.1f}', ha='center', va='center', fontsize=8,
                          color='white' if abs(matrix[i,j]) > limit*.65 else '#18212d')
    axs[1, 0].set(xticks=range(len(POLICIES)), xticklabels=['Random', 'DOE', 'EI', 'EI/cost', 'UCB', 'Dyn EI', 'Dyn UCB'],
                  yticks=range(3), yticklabels=['Unit cost', 'Calendering +50%*', 'Independent costs*'],
                  title='C  Mean final difference vs random | *ASSUMED costs')
    fig.colorbar(im, ax=axs[1, 0], label='mAh/g', shrink=.8)
    extra = [r for r in result['summary'] if r['scenario'] == 'calendering_extra_50pct']
    hit = [r['historical_hit_fraction'] for r in extra]
    axs[1, 1].bar(range(7), hit, color=colors)
    axs[1, 1].set(xticks=range(7), xticklabels=['Random', 'DOE', 'EI', 'EI/cost', 'UCB', 'Dyn EI', 'Dyn UCB'],
                  ylim=(0, 1.05), ylabel='Fraction of seeds finding historical mean above threshold',
                  title=f"D  Assumed calendering cost | demo target D5 >= {result['config']['threshold']:g}")
    fig.savefig(out/'budget_dashboard.png', dpi=180, bbox_inches='tight')
    fig.savefig(out/'budget_dashboard.svg', bbox_inches='tight')
    plt.close(fig)


def write_report(result, out):
    equal = [r for r in result['summary'] if r['scenario'] == 'equal_test_count']
    lines = ['# 同预算历史回放：实测结果', '',
             '2026-10-14。本轮运行当前策略及对照，不是新专利算法或A/B材料前瞻验证。', '',
             f"数据：{result['candidate_count']}个可用条件，{result['independent_ink_groups']}个INK组，"
             f"{result['config']['seeds']}个初始化种子；共同初始5组，总预算{result['config']['budget']:g}单位。", '',
             '## 每个条件相同成本', '',
             '| 方法 | 最佳D5均值 mAh/g | 相对随机配对差 | 配对bootstrap 95%区间 | 胜/平/负 |',
             '|---|---:|---:|---|---|']
    for row in equal:
        lines.append(f"| {LABELS[row['policy']]} | {row['mean_best_D5_mAh_g']:.3f} | {row['vs_random_paired_mean']:+.3f} | "
                     f"[{row['vs_random_bootstrap_95_lower']:.3f}, {row['vs_random_bootstrap_95_upper']:.3f}] | "
                     f"{row['vs_random_wins']}/{row['vs_random_ties']}/{row['vs_random_losses']} |")
    lines += ['', '## 对应消融', '', '| 场景 | 方法相对对照 | 配对差 mAh/g | bootstrap 95%区间 |', '|---|---|---:|---|']
    for row in result['ablations']:
        lines.append(f"| {row['scenario']} | {LABELS[row['policy']]} vs {LABELS[row['reference']]} | "
                     f"{row['paired_mean']:+.3f} | [{row['bootstrap_95_lower']:.3f}, {row['bootstrap_95_upper']:.3f}] |")
    lines += ['', '## 达标和错误判定', '',
              f"D5≥{result['config']['threshold']:g} mAh/g只是预先固定的统计演示阈值。没有ICE、收率或新的重复确认，不能称合格再生石墨。", '',
              '| 场景/方法 | 历史达标率 | 预算截断发现成本 | 实际支出均值 | 新选点均值判达标误判/宣称次数 |',
              '|---|---:|---:|---:|---|']
    for row in result['summary']:
        calls = f"{row['mean_call_error_count']}/{row['mean_call_count']}" if row['mean_call_count'] else '不适用/没有宣称'
        lines.append(f"| {row['scenario']} / {LABELS[row['policy']]} | {row['historical_hit_fraction']:.1%} | "
                     f"{row['mean_restricted_hit_cost_units']:.3f} | {row['mean_actual_spent_units']:.3f} | {calls} |")
    lines += ['', '## 解释范围', '',
              '- 三个场景成本表在运行前固定，不是实测元/电费/机时。相同单位成本下EI/cost与EI应完全一致，作为控制检查。',
              '- 高于随机的均值不自动说明稳定优势；区间跨零、胜率和配对消融都需一起看。bootstrap未作多重比较校正，也不代表跨材料不确定性。',
              '- 50种子是同一个历史候选池的重复初始化，不是50次新的材料实验；观察某INK的一个辊压状态后查询另一状态是合法序贯观测，不是独立INK泛化验证。',
              '- D5协议尚未确认为1C；历史均值不是新制样的真实无噪声容量。公开作者的重复数和波动不同，见质量表。',
              '- GP后验区间和概率没有校准。误判统计只检验相应预测宣称；随机/DOE没有预测宣称，不能记成零错误。',
              '- 预算截断发现成本把未达标记为预算上限；实际支出另外报告。达到历史均值阈值不等于独立重复确认。',
              '- 现有动态描述符策略、成本EI与UCB都不是新发明；尚未实现G5/G6、参数耦合、模型失配统一驱动动作选择。', '',
              '## 文件', '', '[总览图](budget_dashboard.png) · [完整CSV](summary.csv) · [对应消融](ablations.csv) · '
              '[各种子轨迹](campaigns.csv) · [完整记录](result.json) · [推荐先于反馈的日志](decisions.jsonl)', '',
              '复现与预先方案见项目 docs/resource_budget_benchmark_20261014_plan.md。']
    (out/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    parser.add_argument('--seeds', type=int, default=50)
    parser.add_argument('--budget', type=float, default=12.)
    parser.add_argument('--threshold', type=float, default=360.)
    args = parser.parse_args()
    if not 2 <= args.seeds <= 100 or not 10 <= args.budget <= 18 or not np.isfinite(args.threshold):
        raise ValueError('Need 2–100 seeds, budget 10–18 units, finite threshold')
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    config = {'seeds': args.seeds, 'budget': args.budget, 'threshold': args.threshold,
              'initial_conditions': 5, 'policies': POLICIES, 'scenarios': SCENARIOS,
              'kernel': 'workstation fixed Matern 2.5', 'noise_fraction': .05, 'ucb_beta': 2,
              'dynamic_selector': 'observed-only Spearman top 3', 'data_kind': 'historical_public_ASC'}
    (out/'config.json').write_text(json.dumps(config, indent=2), encoding='utf-8')
    project = Path(__file__).resolve().parents[2]
    source = project/'data/external/graphite_manufacturing_4dh2h3tsf4_v1/extracted'
    cells, conditions, flags = read_asc(source)
    usable = [r for r in conditions if r['eligible']]
    rows = [{'record_id': r['candidate_id'], 'group_id': r['sample_id'], 'batch_id': 'public_ASC',
             'target': float(r['D5_mean_mAh_g']), **{k: r[k] for k in INPUTS}} for r in usable]
    write_csv(out/'cell_quality.csv', cells)
    write_csv(out/'condition_quality.csv', conditions)
    cost_table = [{**{k: v for k, v in row.items() if k != 'target'},
                   **{s: scenario_cost(row, s) for s in SCENARIOS}} for row in rows]
    write_csv(out/'cost_scenarios.csv', cost_table)
    file_sources = sorted(source.rglob('ASC-Cell_Data-Azar-Stavros.xlsx')) + sorted(source.rglob('ASC results-live.xlsx'))
    hashes = {str(p.relative_to(project)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in file_sources+[Path(__file__), project/'user_tools/workbench/ml_worker.py',
                                     project/'user_tools/rg_loop/public_graphite.py',
                                     project/'docs/resource_budget_benchmark_20261014_plan.md']}
    (out/'source_hashes.json').write_text(json.dumps(hashes, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'started': True, 'conditions': len(rows), 'ink_groups': len({r['group_id'] for r in rows}),
                      'config': config}, ensure_ascii=False), flush=True)
    started = time.perf_counter()
    campaigns, traces = [], []
    with (out/'decisions.jsonl').open('w', encoding='utf-8') as decisions:
        for scenario in SCENARIOS:
            for seed in range(args.seeds):
                for policy in POLICIES:
                    final, trace = one_campaign(rows, policy, scenario, seed=seed, budget=args.budget,
                                                threshold=args.threshold, decisions=decisions)
                    campaigns.append(final)
                    traces.extend(trace)
                if (seed+1) % 10 == 0:
                    print(json.dumps({'scenario': scenario, 'seeds_done': seed+1,
                                      'elapsed_s': round(time.perf_counter()-started, 1)}), flush=True)
    summary, ablations = summaries(campaigns, args.seeds)
    result = {'config': config, 'candidate_count': len(rows), 'independent_ink_groups': len({r['group_id'] for r in rows}),
              'summary': summary, 'ablations': ablations, 'campaigns': campaigns, 'traces': traces,
              'quality_flags': flags, 'elapsed_s': time.perf_counter()-started, 'python': platform.python_version(),
              'scope': 'Historical finite-pool replay. D5 not verified as 1C; relative cost assumptions, no A/B regeneration benefit.'}
    # In a unit-cost scenario EI and EI/cost must be identical for every paired seed.
    lookup = {(r['scenario'], r['seed'], r['policy']): r for r in campaigns}
    for seed in range(args.seeds):
        if lookup[('equal_test_count', seed, 'gp_ei')]['selected_ids'] != lookup[('equal_test_count', seed, 'cost_gp_ei')]['selected_ids']:
            raise AssertionError('Unit-cost control differs between EI and EI/cost')
    write_csv(out/'summary.csv', summary)
    write_csv(out/'ablations.csv', ablations)
    write_csv(out/'campaigns.csv', campaigns)
    write_csv(out/'traces.csv', traces)
    (out/'result.json').write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    render(result, out)
    write_report(result, out)
    print(json.dumps({'completed': True, 'output': str(out), 'elapsed_s': round(result['elapsed_s'], 1),
                      'equal_cost_summary': [r for r in summary if r['scenario'] == 'equal_test_count']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()

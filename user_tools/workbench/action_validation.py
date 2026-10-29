"""Synthetic, finite, multi-action decision pilot; NOT a material simulation.

The selector has no oracle argument. Joint linear-Gaussian conditioning and
one-step cost-normalized knowledge gradient are established methods, not an
original optimization algorithm. This tests an implementable action interface.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from numpy.polynomial.hermite import hermgauss
from scipy.stats import norm

SCENARIOS = ('matched_no_coupling', 'coupled_ranking_stable',
             'coupled_ranking_sensitive', 'cubic_discrepancy', 'outside_model_sinusoid')
POLICIES = ('random_actions', 'd_optimal_per_cost', 'direct_ei', 'direct_ei_per_cost',
            'joint_cost_kg', 'fixed_radius_cost_kg', 'no_discrepancy_cost_kg')
PRIOR_SD = np.array([.5, 1., .8, .7, 1.4, 1.])
NAMES = ('intercept', 'slope', 'curvature', 'radius_coordinate',
         'diffusion_coordinate', 'target_protocol_discrepancy')


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, allow_nan=False).encode()).hexdigest()


def keyed_rng(*parts):
    key = int(hashlib.sha256(':'.join(map(str, parts)).encode()).hexdigest()[:16], 16)
    return np.random.default_rng(key)


@dataclass
class Posterior:
    mean: np.ndarray
    covariance: np.ndarray

    def update(self, h, value, noise_sd, offset=0.):
        h = np.asarray(h, dtype=float)
        if not np.isfinite(value) or noise_sd <= 0:
            raise ValueError('Finite observation and positive noise required')
        cross = self.covariance @ h
        variance = float(h @ cross + noise_sd**2)
        mean = self.mean + cross * (float(value) - offset - h @ self.mean) / variance
        covariance = self.covariance - np.outer(cross, cross) / variance
        covariance = (covariance + covariance.T) / 2
        if np.linalg.eigvalsh(covariance).min() < -1e-9:
            raise ValueError('Non-PSD posterior')
        return Posterior(mean, covariance)


def initial_posterior(policy):
    sd = PRIOR_SD.copy()
    if policy == 'fixed_radius_cost_kg':
        sd[3] = 1e-6  # Ablation: treats radius coordinate as known zero.
    if policy == 'no_discrepancy_cost_kg':
        sd[5] = 1e-6  # Ablation: target/reference protocol mismatch omitted.
    return Posterior(np.zeros(6), np.diag(sd**2))


def public_design(scenario):
    if scenario not in SCENARIOS:
        raise ValueError('Unknown scenario')
    rows = []
    for i, x in enumerate(np.linspace(-1, 1, 13)):
        tau = 0. if scenario == 'matched_no_coupling' else (.6 if scenario == 'coupled_ranking_stable' else .3*x*x)
        radius = 0. if scenario in ('matched_no_coupling', 'coupled_ranking_stable') else 2*x
        reference = [1., x, x*x, -2*tau, tau, 0.]
        target = [1., x, x*x, -2*tau+radius, tau, 2*x**3]
        rows.append({'id': f'x{i:02d}', 'x': float(x), 'offset': float(-2*x*x),
                     'reference_h': list(map(float, reference)), 'target_h': list(map(float, target))})
    return rows


def action(kind, candidate, repeat, h, offset, noise_sd, cost):
    return {'id': f'{kind}:{candidate}:{repeat}', 'kind': kind, 'candidate_id': candidate,
            'repeat': repeat, 'h': list(map(float, h)), 'offset': float(offset),
            'noise_sd': float(noise_sd), 'cost': float(cost)}


def available_actions(design, counts, remaining):
    rows = []
    for r in design:
        for kind, sd, cost, maximum in (
                ('reference', .18, .6+.1*abs(r['x']), 2),
                ('target', .2, 1.8+.4*abs(r['x']), 3)):
            n = counts[(kind, r['id'])]
            if n < maximum:
                # Explicit same-preparation repeated response, lower mock fee.
                fee = 1.2 if kind == 'target' and n else cost
                rows.append(action(kind, r['id'], n, r[kind+'_h'], r['offset'], sd, fee))
    for kind, h, sd, cost, maximum in (
            ('tau_protocol', [0,0,0,-2,1,0], .12, .4, 3),
            ('radius_characterization', [0,0,0,1,0,0], .15, .7, 2),
            ('alternative_protocol', [0,0,0,-.5,1,0], .12, .9, 2)):
        n = counts[(kind, 'global')]
        if n < maximum:
            rows.append(action(kind, 'global', n, h, 0, sd, cost))
    return [r for r in rows if r['cost'] <= remaining + 1e-10]


def target_posterior(posterior, design):
    f = np.asarray([r['target_h'] for r in design])
    offset = np.asarray([r['offset'] for r in design])
    mean = offset + f @ posterior.mean
    covariance = f @ posterior.covariance @ f.T
    return mean, covariance, f


def kg_scores(posterior, design, actions, quadrature=31):
    """E[max posterior target mean after a scalar observation] - max now.

    1-D Gauss-Hermite quadrature integrates the predictive observation. The
    corresponding expected simple-regret reduction equals this KG, since
    E[max true utility] cancels under conditional expectation. No new rule.
    """
    mean, _, f = target_posterior(posterior, design)
    h = np.asarray([a['h'] for a in actions])
    cross = posterior.covariance @ h.T
    sd_y = np.sqrt(np.sum(h.T * cross, axis=0) + np.array([a['noise_sd']**2 for a in actions]))
    slopes = (f @ cross) / sd_y
    nodes, weights = hermgauss(quadrature)
    future = mean[None,None,:] + np.sqrt(2)*nodes[:,None,None]*slopes.T[None,:,:]
    score = weights @ future.max(axis=2) / np.sqrt(np.pi) - mean.max()
    return np.maximum(score, 0.)


def select_action(posterior, design, actions, policy, *, instance, step, quadrature=31):
    if not actions or any('truth' in a or 'value' in a for a in actions):
        raise ValueError('Selector requires label-free, nonempty available actions')
    if policy not in POLICIES:
        raise ValueError('Unknown policy')
    cost = np.array([a['cost'] for a in actions])
    if policy == 'random_actions':
        pick = int(keyed_rng('selector', instance, step).integers(len(actions)))
        score = np.zeros(len(actions))
    elif policy == 'd_optimal_per_cost':
        h = np.asarray([a['h'] for a in actions])
        variance = np.sum((h @ posterior.covariance) * h, axis=1)
        score = .5*np.log1p(variance/np.array([a['noise_sd']**2 for a in actions])) / cost
        pick = int(np.argmax(score))
    elif policy in ('direct_ei', 'direct_ei_per_cost'):
        mu, cov, _ = target_posterior(posterior, design)
        sd = np.sqrt(np.maximum(np.diag(cov), 1e-12))
        improvement = mu - mu.max()
        z = improvement / sd
        ei = improvement*norm.cdf(z) + sd*norm.pdf(z)
        by_id = {r['id']: i for i, r in enumerate(design)}
        score = np.array([ei[by_id[a['candidate_id']]] if a['kind'] == 'target' else 0. for a in actions])
        if policy == 'direct_ei_per_cost':
            score /= cost
        pick = int(np.argmax(score))
    else:
        score = kg_scores(posterior, design, actions, quadrature) / cost
        pick = int(np.argmax(score))
    if policy != 'random_actions' and score[pick] <= 1e-12:
        # Avoid spending a real mock fee for zero decision value or roundoff.
        return None, {'score': float(score[pick]), 'selector_kind': policy,
                      'candidate_count': len(actions), 'stop_reason': 'no_positive_acquisition'}
    return actions[pick], {'score': float(score[pick]), 'selector_kind': policy,
                           'candidate_count': len(actions)}


class SyntheticWorld:
    """Evaluator-owned truth; never passed into select_action()."""
    def __init__(self, scenario, instance):
        self.scenario, self.instance = scenario, instance
        self.theta = keyed_rng('truth', scenario, instance).normal(size=6)*PRIOR_SD
        if scenario != 'cubic_discrepancy':
            self.theta[5] = 0.
        self.sin_amplitude = (float(keyed_rng('outside', instance).normal(0, 1.5))
                              if scenario == 'outside_model_sinusoid' else 0.)

    def target_truth(self, r):
        return float(r['offset'] + np.asarray(r['target_h']) @ self.theta
                     + self.sin_amplitude*np.sin(2*np.pi*r['x']))

    def observe(self, a, design):
        value = a['offset'] + np.asarray(a['h']) @ self.theta
        if a['kind'] == 'target':
            value = self.target_truth(next(r for r in design if r['id'] == a['candidate_id']))
        noise = keyed_rng('observation', self.scenario, self.instance, a['id']).normal(0, a['noise_sd'])
        return float(value + noise)

    def confirm(self, r):
        # New noise, no training feedback; simulated same-preparation confirmation.
        noise = keyed_rng('final_confirmation', self.scenario, self.instance, r['id']).normal(0, .2, 3)
        return float(self.target_truth(r) + noise.mean())


def run_campaign(world, policy, budget, quadrature, decisions, final_decisions):
    design = public_design(world.scenario)
    posterior = initial_posterior(policy)
    counts = Counter()
    observations = []
    spent = 0.
    confirmation_fee = 1.6
    # Shared, known, fixed initial reference measurements; not target labels.
    initial_ids = [('tau_protocol', 'global'), ('reference', 'x00'),
                   ('reference', 'x06'), ('reference', 'x12')]
    for kind, candidate in initial_ids:
        candidates = available_actions(design, counts, budget-confirmation_fee-spent)
        a = next((v for v in candidates if v['kind'] == kind and v['candidate_id'] == candidate), None)
        if a is None:
            raise ValueError('Budget cannot afford shared initial design and confirmation')
        value = world.observe(a, design)
        posterior = posterior.update(a['h'], value, a['noise_sd'], a['offset'])
        counts[(kind, candidate)] += 1
        spent += a['cost']
        observations.append({**a, 'value': value, 'phase': 'initial'})
    initial_snapshot = digest(observations)
    traces = []
    step = 0
    stop_reason = 'no_affordable_action'
    while True:
        actions = available_actions(design, counts, budget-confirmation_fee-spent)
        if not actions:
            break
        a, score = select_action(posterior, design, actions, policy, instance=world.instance,
                                 step=step, quadrature=quadrature)
        if a is None:
            stop_reason = score['stop_reason']
            break
        record = {'scenario': world.scenario, 'instance': world.instance, 'policy': policy,
                  'step': step, 'spent_before': spent, 'reserved_confirmation_fee': confirmation_fee,
                  'initial_snapshot': initial_snapshot, 'observations_sha256': digest(observations),
                  'available_actions_sha256': digest(actions), 'selected_action': a,
                  'posterior_mean': posterior.mean.tolist(), 'posterior_covariance': posterior.covariance.tolist(),
                  'selector': score}
        decisions.write(json.dumps(record, allow_nan=False)+'\n')
        decisions.flush()  # Must precede oracle access.
        value = world.observe(a, design)
        posterior = posterior.update(a['h'], value, a['noise_sd'], a['offset'])
        observations.append({**a, 'value': value, 'phase': 'adaptive'})
        spent += a['cost']
        if spent + confirmation_fee > budget + 1e-9:
            raise AssertionError('Budget exceeded')
        counts[(a['kind'], a['candidate_id'])] += 1
        traces.append({'scenario': world.scenario, 'instance': world.instance, 'policy': policy,
                       'step': step, 'action_id': a['id'], 'kind': a['kind'], 'repeat': a['repeat'],
                       'value': value, 'cost': a['cost'], 'spent': spent, 'score': score['score']})
        step += 1
    mu, covariance, _ = target_posterior(posterior, design)
    choice = int(np.argmax(mu))  # All policies use identical terminal rule.
    sd = np.sqrt(np.maximum(np.diag(covariance), 0))
    observed_confirmation_sd = np.sqrt(sd[choice]**2+.2**2/3)
    final_record = {'scenario': world.scenario, 'instance': world.instance, 'policy': policy,
                    'phase': 'final_decision', 'selected_id': design[choice]['id'],
                    'spent_before_confirmation': spent, 'reserved_confirmation_fee': confirmation_fee,
                    'budget': budget, 'initial_snapshot': initial_snapshot,
                    'observations_sha256': digest(observations),
                    'target_posterior_mean': mu.tolist(),
                    'target_posterior_covariance': covariance.tolist(),
                    'prediction_mean': float(mu[choice]),
                    'confirmation_prediction_interval_95': [float(mu[choice]-1.96*observed_confirmation_sd),
                                                           float(mu[choice]+1.96*observed_confirmation_sd)]}
    final_decisions.write(json.dumps(final_record, allow_nan=False)+'\n')
    final_decisions.flush()  # Freeze terminal choice BEFORE oracle truth or confirmation.
    truth = np.array([world.target_truth(r) for r in design])  # Evaluator only.
    selected_truth = float(truth[choice])
    confirmation = world.confirm(design[choice])
    spent += confirmation_fee
    result = {'scenario': world.scenario, 'instance': world.instance, 'policy': policy,
              'budget': budget, 'spent': spent, 'initial_snapshot': initial_snapshot,
              'confirmation_fee': confirmation_fee, 'confirmation_used_for_training': False,
              'confirmation_mean': confirmation, 'recommendation_id': design[choice]['id'],
              'recommendation_truth': selected_truth, 'oracle_max': float(truth.max()),
              'simple_regret': float(truth.max()-selected_truth),
              'exact_best': bool(truth.max()-selected_truth < 1e-9),
              'within_0p5': bool(truth.max()-selected_truth <= .5),
              'rmse_all_candidates': float(np.sqrt(np.mean((mu-truth)**2))),
              'latent_interval_95_fraction': float(np.mean(np.abs(mu-truth) <= 1.96*sd)),
              'selected_confirmation_interval_hit': bool(abs(confirmation-mu[choice]) <= 1.96*observed_confirmation_sd),
              'posterior_radius_sd': float(np.sqrt(posterior.covariance[3,3])),
              'posterior_radius_diffusion_correlation': float(posterior.covariance[3,4]/np.sqrt(posterior.covariance[3,3]*posterior.covariance[4,4])),
              'adaptive_actions': step, 'stop_reason': stop_reason, 'observations': observations,
              'truth_theta': world.theta.tolist(), 'sin_amplitude': world.sin_amplitude}
    for kind in ('reference', 'target', 'radius_characterization', 'tau_protocol', 'alternative_protocol'):
        result[kind+'_adaptive_cost'] = float(sum(t['cost'] for t in traces if t['kind'] == kind))
        result[kind+'_adaptive_count'] = sum(t['kind'] == kind for t in traces)
    return result, traces


def write_csv(path, rows):
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def summarise(campaigns):
    summary, comparisons = [], []
    for scenario in SCENARIOS:
        grouped = {p: sorted([r for r in campaigns if r['scenario'] == scenario and r['policy'] == p],
                             key=lambda r:r['instance']) for p in POLICIES}
        for policy, rows in grouped.items():
            if not rows:
                continue
            summary.append({'scenario': scenario, 'policy': policy, 'instances': len(rows),
                            **{k+'_mean': float(np.mean([r[k] for r in rows])) for k in
                               ('simple_regret', 'spent', 'exact_best', 'within_0p5', 'rmse_all_candidates',
                                'latent_interval_95_fraction', 'selected_confirmation_interval_hit',
                                'posterior_radius_sd', 'radius_characterization_adaptive_cost',
                                'alternative_protocol_adaptive_cost', 'target_adaptive_cost',
                                'reference_adaptive_cost', 'tau_protocol_adaptive_cost')},
                            'simple_regret_sd': float(np.std([r['simple_regret'] for r in rows], ddof=1))})
        full = grouped['joint_cost_kg']
        for reference in ('direct_ei_per_cost', 'd_optimal_per_cost', 'fixed_radius_cost_kg',
                          'no_discrepancy_cost_kg', 'random_actions'):
            delta = np.array([a['simple_regret']-b['simple_regret'] for a,b in zip(full,grouped[reference])])
            boot = keyed_rng('bootstrap', scenario, reference).choice(delta, size=(4000,len(delta)), replace=True).mean(axis=1)
            low, high = np.quantile(boot, [.025,.975])
            comparisons.append({'scenario': scenario, 'method': 'joint_cost_kg', 'reference': reference,
                                'instances': len(delta), 'regret_difference_mean': float(delta.mean()),
                                'paired_bootstrap_95_low': float(low), 'paired_bootstrap_95_high': float(high),
                                'wins': int((delta < -1e-9).sum()), 'ties': int((abs(delta) <= 1e-9).sum()),
                                'losses': int((delta > 1e-9).sum())})
    return summary, comparisons


def plot(summary, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    labels = ['No coupling', 'Coupling / stable rank', 'Coupling / sensitive rank',
              'Cubic discrepancy', 'Outside model / sine']
    names = {'joint_cost_kg':'Joint model / cost KG', 'direct_ei_per_cost':'Direct EI / cost',
             'd_optimal_per_cost':'D-optimal / cost', 'fixed_radius_cost_kg':'Fix radius / KG',
             'no_discrepancy_cost_kg':'Omit discrepancy / KG', 'random_actions':'Random actions'}
    by = {(r['scenario'], r['policy']): r for r in summary}
    fig, axs = plt.subplots(1, 2, figsize=(14,5.2), constrained_layout=True)
    styles = ['o-', 's--', '^--', 'v:', 'D:', 'x--']
    for (policy,label), style in zip(names.items(), styles):
        rows = [by[(s,policy)] for s in SCENARIOS]
        axs[0].plot(range(5), [r['simple_regret_mean'] for r in rows], style, label=label, ms=5)
        axs[1].plot(range(5), [r['within_0p5_mean'] for r in rows], style, label=label, ms=5)
    for ax in axs:
        ax.set_xticks(range(5), labels, rotation=18, ha='right')
        ax.grid(alpha=.2)
    axs[0].set_ylabel('Mean simple regret (synthetic utility; lower is better)')
    axs[1].set_ylabel('Fraction within 0.5 of oracle best (higher is better)')
    axs[1].set_ylim(0,1.05)
    axs[0].legend(fontsize=8)
    fig.suptitle('Synthetic multi-action pilot; equal mock resource budget, no material claims')
    fig.savefig(output/'action_validation.png', dpi=180)
    fig.savefig(output/'action_validation.svg')
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--instances', type=int, default=40)
    parser.add_argument('--first-instance', type=int, default=1000)
    parser.add_argument('--budget', type=float, default=10.)
    parser.add_argument('--quadrature', type=int, default=31)
    args = parser.parse_args()
    if args.instances < 2 or args.budget < 4.5 or args.quadrature < 5:
        raise ValueError('Invalid pilot configuration')
    if args.output.exists():
        raise FileExistsError('Use a new output directory; previous evidence stays immutable')
    args.output.mkdir(parents=True)
    code_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    protocol = {'evidence_type':'simulation_only', 'original_algorithm_claim':False,
                'material_validation':False, 'scope':'Finite scalar linear-Gaussian action-selection pilot',
                'scenarios':list(SCENARIOS), 'policies':list(POLICIES),
                'instances_per_scenario':args.instances, 'first_instance':args.first_instance,
                'budget':args.budget, 'quadrature':args.quadrature, 'code_sha256':code_hash,
                'cost_kind':'Predeclared relative mock resource units, not CNY or LCA',
                'noise_kind':'Known Gaussian noise; no fit of unknown noise',
                'target':'Dimensionless synthetic utility, not capacity or ICE',
                'confirmation':'Simulated same-preparation 3-read mean, withheld from training, fixed fee 1.6',
                'claim_limits':['Matched linear models are numerical controls, not independent physical validation',
                                'Outside-model sine is not represented in any learner',
                                'EI is a plug-in mean-incumbent baseline, not qNEI',
                                'D-optimal maximizes total latent information, not target value',
                                'No strong ARD GP / HVKG multi-objective comparison or real experiment',
                                'No coverage guarantee under adaptive selection',
                                'Bootstrap intervals are exploratory without multiplicity adjustment'],
                'selection':'one-step expected target maximum posterior mean gain / cost (standard KG)'}
    protocol['numerical_zero_acquisition_stop'] = 1e-12
    protocol['terminal_decision_persisted_before_truth_and_confirmation'] = True
    # Persist frozen settings and exact source BEFORE any oracle evaluation.
    (args.output/'protocol.json').write_text(json.dumps(protocol, indent=2), encoding='utf-8')
    (args.output/'source_snapshot.py').write_bytes(Path(__file__).read_bytes())
    (args.output/'EXPERIMENT_TRACKER.md').write_text('# 合成动作决策验证\n\n状态：IN_PROGRESS。\n', encoding='utf-8')
    started = time.monotonic()
    campaigns, traces = [], []
    with (args.output/'decisions.jsonl').open('w', encoding='utf-8') as stream, \
            (args.output/'final_decisions.jsonl').open('w', encoding='utf-8') as final_stream:
        for scenario in SCENARIOS:
            for instance in range(args.first_instance,args.first_instance+args.instances):
                world = SyntheticWorld(scenario, instance)
                for policy in POLICIES:
                    r,t = run_campaign(world, policy, args.budget, args.quadrature, stream, final_stream)
                    campaigns.append(r)
                    traces.extend(t)
            print(json.dumps({'scenario':scenario, 'campaigns_completed':len(campaigns)}, ensure_ascii=False), flush=True)
    summary, comparisons = summarise(campaigns)
    write_csv(args.output/'summary.csv', summary)
    write_csv(args.output/'paired_comparisons.csv', comparisons)
    write_csv(args.output/'campaigns.csv', [{k:v for k,v in r.items() if k not in ('observations','truth_theta')} for r in campaigns])
    write_csv(args.output/'traces.csv', traces)
    payload = {'protocol':protocol, 'elapsed_s':time.monotonic()-started, 'summary':summary,
               'paired_comparisons':comparisons, 'campaigns':campaigns}
    (args.output/'result.json').write_text(json.dumps(payload, indent=2, allow_nan=False), encoding='utf-8')
    plot(summary,args.output)
    (args.output/'EXPERIMENT_TRACKER.md').write_text(
        f'# 合成动作决策验证\n\n状态：DONE。5类数学场景，每类{args.instances}个独立真值/噪声实例，'
        f'7种策略，{len(campaigns)}场。预算{args.budget}相对单位，含共同初始信息与最终模拟确认费用。\n\n'
        '这不是PyBaMM半电池验证、真实再生工艺、原版FDA或新算法创新证明。\n', encoding='utf-8')
    print(json.dumps({'status':'completed','campaigns':len(campaigns),'elapsed_s':payload['elapsed_s'],
                      'output':str(args.output)},ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()

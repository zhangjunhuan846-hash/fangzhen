"""Render the archived ASC public replay without refitting or altering the results."""
import csv
import json
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def rows(path):
    with path.open(encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))


def main():
    root = Path(__file__).resolve().parents[2]
    source = root / 'outputs/workbench_research_final_tests/jobs/4e18baddf0c5495c8ce950c4423dd50f/physics'
    out = root / 'outputs/analysis/public_graphite_v038_demo'
    out.mkdir(parents=True, exist_ok=True)
    result = json.loads((source / 'result.json').read_text(encoding='utf-8'))
    model = result['model_comparison']
    comparisons = model['comparisons']
    replay = rows(source / 'replay.csv')
    quality = rows(source / 'condition_quality_audit.csv')
    oof = [r for r in model['oof'] if r['model'] == model['selected_model']]

    plt.rcParams.update({'font.size': 10, 'axes.spines.top': False,
                         'axes.spines.right': False, 'savefig.dpi': 180})
    fig, axs = plt.subplots(2, 2, figsize=(12, 8), constrained_layout=True)
    fig.suptitle('Public graphite electrode manufacturing | ASC historical replay', fontsize=14, weight='bold')

    names = [r['model'].replace('_', ' ').title() for r in comparisons]
    mae = [r['metrics']['mae'] for r in comparisons]
    colors = ['#3066be' if r['model'] == model['selected_model'] else '#9bb6d9' for r in comparisons]
    axs[0, 0].barh(names, mae, color=colors)
    axs[0, 0].invert_yaxis()
    axs[0, 0].set_xlabel('Grouped CV MAE (mAh/g; lower is better)')
    axs[0, 0].set_title('Six models, 10 independent INK groups')

    observed = np.array([r['observed'] for r in oof], dtype=float)
    predicted = np.array([r['predicted'] for r in oof], dtype=float)
    axs[0, 1].scatter(observed, predicted, color='#3066be', alpha=.75, s=42)
    lo = min(observed.min(), predicted.min()) - 5
    hi = max(observed.max(), predicted.max()) + 5
    axs[0, 1].plot([lo, hi], [lo, hi], '--', color='#63758a', lw=1)
    axs[0, 1].set(xlim=(lo, hi), ylim=(lo, hi), xlabel='Measured D5 specific capacity (mAh/g)',
                  ylabel='Held-out prediction (mAh/g)', title='Selected random forest: grouped holdout')
    axs[0, 1].text(.03, .97, 'MAE 30.85 mAh/g | R² -0.35', transform=axs[0, 1].transAxes,
                   va='top', fontsize=9, bbox={'facecolor': 'white', 'alpha': .85, 'edgecolor': 'none'})

    by = defaultdict(lambda: defaultdict(list))
    for row in replay:
        by[row['strategy']][int(row['observations'])].append(float(row['best_D5_mAh_g']))
    order = [('random', '#777777'), ('spacefill', '#12a89d'),
             ('gp_fixed', '#f09038'), ('gp_dynamic', '#3066be')]
    for strategy, color in order:
        xs = sorted(by[strategy])
        matrix = [np.asarray(by[strategy][x]) for x in xs]
        means = np.array([a.mean() for a in matrix])
        se = np.array([a.std(ddof=1) / np.sqrt(len(a)) for a in matrix])
        axs[1, 0].plot(xs, means, 'o-', lw=1.8, ms=3, color=color, label=strategy)
        axs[1, 0].fill_between(xs, means - se, means + se, color=color, alpha=.12)
    axs[1, 0].legend(frameon=False, fontsize=8, ncol=2)
    axs[1, 0].set(xlabel='Observed conditions (same budget)', ylabel='Mean best measured D5 (mAh/g)',
                  title='20 replay seeds; shading = ±1 SE across seeds')

    eligible = [r for r in quality if r['eligible'] == 'True']
    values = np.array([float(r['D5_mean_mAh_g']) for r in eligible])
    sds = np.array([float(r['D5_sd_mAh_g']) if r['D5_sd_mAh_g'] else 0 for r in eligible])
    ix = np.argsort(values)
    axs[1, 1].errorbar(np.arange(len(ix)), values[ix], yerr=sds[ix], fmt='o', ms=4,
                       color='#3066be', ecolor='#e27362', capsize=2)
    axs[1, 1].set(xlabel='18 eligible historical conditions, sorted by mean',
                  ylabel='D5 specific capacity (mAh/g)',
                  title='Cell-to-cell SD; two conditions are highly variable')
    fig.text(.5, -.012, 'D5 protocol is not verified as 1C. Historical manufacturing data, not recycled-graphite regeneration.',
             ha='center', fontsize=9, color='#566477')
    fig.savefig(out / 'public_graphite_dashboard.png', bbox_inches='tight')
    plt.close(fig)

    report = {
        'source_job': source.parent.name,
        'dataset': 'ASC public graphite electrode manufacturing, Mendeley Data 10.17632/4dh2h3tsf4.1',
        'eligible_conditions': result['candidate_count'],
        'independent_ink_groups': result['independent_ink_groups'],
        'selected_model': model['selected_model'],
        'selected_model_grouped_cv': next(r['metrics'] for r in comparisons if r['model'] == model['selected_model']),
        'replay_summary': result['replay_summary'],
        'figure': 'public_graphite_dashboard.png',
        'interpretation': 'Engineering validation and historical replay only; no stable optimizer superiority or regenerated-graphite result.'
    }
    (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(out / 'public_graphite_dashboard.png')


if __name__ == '__main__':
    main()

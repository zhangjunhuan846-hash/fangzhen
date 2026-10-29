"""Post-run diagnostics. Does not change selections, costs, thresholds or metrics."""
from collections import defaultdict
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def main():
    root = Path(__file__).resolve().parents[2]/'outputs/analysis/resource_budget_20261014'
    result = json.loads((root/'result.json').read_text(encoding='utf-8'))
    threshold = result['config']['threshold']
    rows = [r for r in result['traces'] if r['scenario']=='equal_test_count' and
            r['policy']=='dynamic_gp_ucb' and r.get('prediction_mean') is not None]
    predictions = np.array([r['prediction_mean'] for r in rows])
    observed = np.array([r['revealed_D5_mAh_g'] for r in rows])
    records = [json.loads(line) for line in (root/'decisions.jsonl').read_text(encoding='utf-8').splitlines()]
    lookup = {(r['scenario'], r['seed'], r['policy'], r['conditions_observed']-6):r['revealed_D5_mAh_g']
              for r in result['traces'] if r.get('selected_id') is not None}
    buckets = defaultdict(list)
    for record in records:
        if record['scenario']!='equal_test_count' or record['policy']!='dynamic_gp_ucb':
            continue
        prob=record['forecast']['probability_above_threshold']
        value=lookup[(record['scenario'],record['seed'],record['policy'],record['step'])]
        index=min(4,int(prob*5))
        buckets[index].append((prob, int(value>=threshold)))
    calibration=[{'bucket':i, 'predicted_mean_probability':float(np.mean([r[0] for r in values])),
                  'historical_hit_fraction':float(np.mean([r[1] for r in values])), 'calls':len(values)}
                 for i,values in sorted(buckets.items())]
    initial = [r for r in result['traces'] if r['policy']=='random' and r['scenario']=='equal_test_count'
               and r['conditions_observed']==5]
    high = [r for r in records if r['scenario']=='equal_test_count' and r['policy']=='dynamic_gp_ucb'
            and r['forecast']['posterior_probability_ge_0p9']]
    errors=sum(lookup[(r['scenario'],r['seed'],r['policy'],r['step'])]<threshold for r in high)
    facts={'initial_design_historical_hits':sum(r['best_D5_mAh_g']>=threshold for r in initial),
           'seeds':len(initial), 'threshold':threshold, 'selected_prediction_calls':len(rows),
           'selected_prediction_mae_mAh_g':float(np.mean(np.abs(predictions-observed))),
           'uncalibrated_probability_ge_0p9_calls':len(high), 'historical_threshold_misses_among_these':errors,
           'probability_buckets':calibration,
           'scope':'Post-run descriptive diagnostics, adaptive historical choices with repeated conditions across seeds; not independent held-out materials or calibrated coverage.'}
    (root/'prediction_diagnostics.json').write_text(json.dumps(facts,indent=2),encoding='utf-8')
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,axs=plt.subplots(1,2,figsize=(11,4.6),constrained_layout=True)
    fig.suptitle('Dynamic GP / UCB | selected, previously hidden historical conditions',weight='bold')
    axs[0].scatter(predictions,observed,s=16,alpha=.2,color='#2875b9')
    lo=min(predictions.min(),observed.min())-5;hi=max(predictions.max(),observed.max())+5
    axs[0].plot([lo,hi],[lo,hi],'--',color='#777',lw=1)
    axs[0].set(xlabel='One-step predicted D5 (mAh/g)',ylabel='Revealed historical D5 (mAh/g)',
               title=f'A  {len(rows)} adaptive prediction calls; repeated conditions')
    axs[1].plot([0,1],[0,1],'--',color='#777',lw=1,label='Perfect reliability')
    xx=[r['predicted_mean_probability'] for r in calibration]
    yy=[r['historical_hit_fraction'] for r in calibration]
    axs[1].plot(xx,yy,'o-',color='#bc596c',label='Historical outcomes')
    for row in calibration:
        axs[1].annotate(f"n={row['calls']}",(row['predicted_mean_probability'],row['historical_hit_fraction']),
                        xytext=(-3,8),textcoords='offset points',fontsize=8,ha='right')
    axs[1].set(xlim=(-.03,1.03),ylim=(-.03,1.1),xlabel='Mean uncalibrated P(D5 >= 360)',
               ylabel='Fraction with historical D5 >= 360',title=f'B  >=90% calls: {errors} misses / {len(high)} calls')
    axs[1].legend(frameon=False,fontsize=8)
    fig.savefig(root/'prediction_diagnostics.png',dpi=180,bbox_inches='tight')
    fig.savefig(root/'prediction_diagnostics.svg',bbox_inches='tight')
    plt.close(fig)
    lines=['# 本轮结果解释', '', '2026-10-14。依据本轮已保存结果；没有重新选点或改变预先阈值。', '',
           '1. 等条件次数下，动态描述符GP-EI相对固定GP-EI的配对最佳D5增加4.415 mAh/g，bootstrap 95%区间[1.704,7.308]；这是当前有限池的描述性消融结果，未作多重比较校正。',
           '2. 动态GP-EI相对随机增加2.285 mAh/g，区间[-0.668,5.441]跨零；动态UCB相对随机的区间同样跨零。因此没有证明稳定优于随机，更不能推成真实回收石墨收益。',
           '3. EI/成本相对同一GP-EI：假设辊压多50%成本时增加2.367 mAh/g；标签独立哈希成本场景时反而降低2.127。按当前这一个费用表/候选池评估，不能宣称成本感知一定更好，假设单位也不是实测费用。',
           f"4. 演示阈值360 mAh/g在初始5条件时已有{facts['initial_design_historical_hits']}/{facts['seeds']}种子达到。等条件次数下各方法最终全部达标，检测能力存在天花板；本轮未证明达标成本下降。后续阈值应按真实应用需求预设，不能从本次结果挑最有利门槛。",
           f"5. 动态GP-UCB给出未经校准的≥90%达标后验概率的{len(high)}次新选点中，有{errors}次历史D5均值未达标。每次针对的训练集不同，而且同条件可在不同种子出现；这不是独立材料覆盖率估计。",
           '6. 这些GP基线是探索策略；本轮没有启用完整工作站的独立校准/拒绝推荐、G5/G6或级联决策。这些诊断不能表述为“完整平台已作出85次可信推荐”。', '',
           '本轮实现了同预算对照、描述符对应消融和风险诊断。进一步算法研究需要针对耦合、失配和动作费用提出具体决策方法；目前没有完成新算法，也没有证明真实材料性能、实验费用或经独立重复验证的错误推荐率改善。', '',
           '[总览](budget_dashboard.png) · [预测诊断图](prediction_diagnostics.png) · [原始结果](result.json) · [完整表](summary.csv)']
    (root/'interpretation.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(facts,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()

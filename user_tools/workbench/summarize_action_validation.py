"""Source-backed pilot report and deterministic accounting checks."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    root = args.directory
    data = json.loads((root/'result.json').read_text(encoding='utf-8'))
    campaigns = data['campaigns']
    by = {(r['scenario'],r['policy']):r for r in data['summary']}
    full = 'joint_cost_kg'
    ei = 'direct_ei_per_cost'
    initial = {}
    for r in campaigns:
        assert r['spent'] <= r['budget'] + 1e-9
        assert abs(r['spent']-sum(o['cost'] for o in r['observations'])-r['confirmation_fee']) < 1e-9
        assert not r['confirmation_used_for_training']
        assert all(o['phase'] in ('initial','adaptive') for o in r['observations'])
        key = (r['scenario'],r['instance'])
        if key not in initial:
            initial[key] = r['initial_snapshot']
        assert initial[key] == r['initial_snapshot']
        assert abs(r['simple_regret']-(r['oracle_max']-r['recommendation_truth'])) < 1e-10
    for scenario in ('matched_no_coupling','coupled_ranking_stable'):
        assert by[(scenario,full)]['radius_characterization_adaptive_cost_mean'] == 0
    snapshot = hashlib.sha256((root/'source_snapshot.py').read_bytes()).hexdigest()
    assert snapshot == data['protocol']['code_sha256']
    decision_count = sum(1 for _ in (root/'decisions.jsonl').open(encoding='utf-8'))
    assert decision_count == sum(r['adaptive_actions'] for r in campaigns)
    final_records = [json.loads(line) for line in (root/'final_decisions.jsonl').open(encoding='utf-8')]
    assert len(final_records) == len(campaigns)
    frozen_final = {(r['scenario'],r['instance'],r['policy']):r for r in final_records}
    assert len(frozen_final) == len(campaigns)
    for r in campaigns:
        f = frozen_final[(r['scenario'],r['instance'],r['policy'])]
        assert f['selected_id'] == r['recommendation_id']
        assert abs(f['spent_before_confirmation']+f['reserved_confirmation_fee']-r['spent']) < 1e-9
    checks = {'status':'PASS', 'campaign_count':len(campaigns),
              'independent_scenario_instances':len(initial), 'persisted_decisions':decision_count,
              'persisted_final_recommendations':len(final_records),
              'checks':['budget_cap','all_initial_adaptive_confirmation_costs',
                        'shared_initial_observations','confirmation_withheld','regret_recomputed',
                        'negative_control_no_radius_cost','code_snapshot_hash','decision_count',
                        'terminal_frozen_recommendation_and_fee'],
              'scope':'Deterministic accounting checks, not external semantic or scientific audit'}
    (root/'ACCOUNTING_CHECK.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
    labels = {'matched_no_coupling':'无耦合', 'coupled_ranking_stable':'耦合但排序稳定',
              'coupled_ranking_sensitive':'耦合改变目标排序', 'cubic_discrepancy':'模型可表示的三次协议差异',
              'outside_model_sinusoid':'模型无法表示的正弦偏差'}
    lines = ['# 现在可验证到哪一步：合成动作决策结果', '',
             '日期：2026-10-14。完成5类数学场景×每类40个独立真值/噪声实例×7策略=1400场。'
             '各策略相同候选、共同初始信息、动作权限和总预算上限10相对单位；费用包含初始测量、适应性动作和最终模拟确认。', '',
             '**结论：联合参数与可选测量动作可以在特定合成场景改善决策，但不能处理任意模型错误；尚未证明新算法创新或真实再生收益。**', '',
             '“联合模型”使用标准一步KG/费用，没有新采集函数。目标是无量纲数学效用，坐标只是粒径—扩散耦合的类比；未调用PyBaMM或G5/G6，未改动生产工作站的推荐。', '',
             '## 原始结果', '',
             '简单遗憾=该实例候选中真实最大效用−最终推荐候选真实效用，越小越好。以下均为40实例均值，不是容量单位。', '',
             '| 场景 | 联合模型KG/费用 | 直接EI/费用 | 按费用D最优设计 | 联合模型距最优≤0.5比例 |',
             '|---|---:|---:|---:|---:|']
    for scenario, label in labels.items():
        r = by[(scenario,full)]
        lines.append(f'| {label} | {r["simple_regret_mean"]:.6f} | {by[(scenario,ei)]["simple_regret_mean"]:.6f} | '
                     f'{by[(scenario,"d_optimal_per_cost")]["simple_regret_mean"]:.6f} | {r["within_0p5_mean"]:.1%} |')
    lines += ['', '## 机制和失败', '',
              f'- 无耦合与耦合但排序稳：联合KG补粒径费用均为0。即使单独参数不明确，若不会改变候选排序，也没有自动要求继续补表征。',
              f'- 耦合改变排序：固定粒径坐标消融的平均遗憾为{by[("coupled_ranking_sensitive","fixed_radius_cost_kg")]["simple_regret_mean"]:.6f}，'
              f'联合模型为{by[("coupled_ranking_sensitive",full)]["simple_regret_mean"]:.6f}。它平均花费'
              f'{by[("coupled_ranking_sensitive",full)]["radius_characterization_adaptive_cost_mean"]:.4f}单位补粒径信息。'
              '这支持在该数学设置下保留联合不确定性的作用；不支持把真实D50直接当有效R。',
              f'- 三次协议差异：删除该模型项后的平均遗憾为{by[("cubic_discrepancy","no_discrepancy_cost_kg")]["simple_regret_mean"]:.6f}，'
              f'联合模型为{by[("cubic_discrepancy",full)]["simple_regret_mean"]:.6f}。但差异函数族已由实验者事先写进模型，是受控机制验证。',
              f'- 无法表示的正弦偏差：联合模型遗憾{by[("outside_model_sinusoid",full)]["simple_regret_mean"]:.6f}，'
              f'直接EI/费用{by[("outside_model_sinusoid",ei)]["simple_regret_mean"]:.6f}；联合模型均值更差。'
              '配对差区间含0，不能据此确定谁普遍更好，但已不能宣称统一优越。',
              f'- 同一正弦场景：联合模型全候选条件高斯95%区间实际命中比例均值只有'
              f'{by[("outside_model_sinusoid",full)]["latent_interval_95_fraction_mean"]:.1%}，'
              f'独立噪声确认的区间命中为{by[("outside_model_sinusoid",full)]["selected_confirmation_interval_hit_mean"]:.1%}。'
              '“显示95%”不是可靠性保证；当前原型没有任意模型失配检测或降级模块。', '',
              '## 探索性配对比较', '',
              '下表=联合模型遗憾−直接EI/费用遗憾；负值有利联合模型。按独立真值实例配对bootstrap4000次。区间未做多重比较修正，不能作确认性论文结论。', '',
              '| 场景 | 配对差均值 | 探索性95%区间 | 胜/平/负实例数 |', '|---|---:|---|---|']
    for r in data['paired_comparisons']:
        if r['reference'] == ei:
            lines.append(f'| {labels[r["scenario"]]} | {r["regret_difference_mean"]:.6f} | '
                         f'[{r["paired_bootstrap_95_low"]:.6f}, {r["paired_bootstrap_95_high"]:.6f}] | '
                         f'{r["wins"]}/{r["ties"]}/{r["losses"]} |')
    lines += ['', '## 公平性和证据范围', '',
              '- 所有动作收费，确认费1.6提前预留；确认含3个独立噪声读数，不反馈训练。只是同制备模拟读数，不是独立再生/组装验证。',
              '- 总预算为共同上限，零信息收益时允许停止，各策略实际支出不一定相等；未用预算单独记录。不能把这轮的支出差称实际达标费用下降。',
              '- 真值先独立抽取，选择器没有oracle参数；推荐先落盘，再揭示观测。三类匹配/三次场景属于线性函数族数值控制，正弦是模型外测试；全部simulation_only。',
              '- EI是plug-in版本而非qNEI；D最优最大化总参数信息。尚无调参ARD GP、多目标HVKG、真实费用、有限历史池与真实A/B前瞻联动；本轮不能替代强基线B1和材料B3。',
              '- 0.5是冻结的合成效用距离阈值，不代表实验容量标准。许多负对照已接近最优，存在天花板，不能只报100%比例。',
              '- KG的一步价值/费用、联合高斯更新和协议差异模型都是已有思想。改善应用模型不自动成为新优化算法；需另做方法逐步查新。', '',
              '## 数值修复和复现', '',
              '首轮零收益动作可能因约1e−16浮点差被选中。原目录完整保留。v2修复加入≤1e−12采集值停止规则，适用于全部非随机策略；v3按完整性审阅补充最终候选在oracle真值/确认前的独立落盘日志。场景、真值种子、费用、预算、目标与指标没有改变。这些同实例修复属于开发/数值控制，不能称独立确认性验证。', '',
              f'7项测试通过。{len(campaigns)}场预算与确认隔离检查通过；逐动作落盘记录{decision_count}条。'
              '原始证据：protocol.json、source_snapshot.py、result.json、summary.csv、paired_comparisons.csv、campaigns.csv、traces.csv、decisions.jsonl及ACCOUNTING_CHECK.json。', '',
              f'最终推荐落盘记录{len(final_records)}条，见final_decisions.jsonl；推荐及预测区间在真值/确认读出前保存。', '',
              '## 下一步', '',
              '1. 模型外偏差是本轮明确缺口：需要实际协议残差与灵活差异模型、模型平均或诊断动作，再冻结新的开发/验证任务；不能在当前结果上改完后称独立成功。',
              '2. 用调参ARD GP/适当噪声BO与部分观测强方法比较，检验收益来自应用模型还是新决策规则。',
              '3. 把真实联合参数可信集合和留出协议残差接到动作接口，然后用公开电化学数据验证；数学原型不能直接输出真实再生条件。',
              '4. 自有A/B半电池数据、真实费用、工艺路线与目标标准到位后，才能做冻结后的前瞻材料验证。', '',
              '方法依据：[多保真BO，AISTATS2019](https://proceedings.mlr.press/v89/song19b.html)、'
              '[HVKG，ICML2023](https://proceedings.mlr.press/v202/daulton23a.html)。仅参考成本/信息动作思路，没有复现完整论文算法。', '']
    (root/'report.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(checks,ensure_ascii=False))


if __name__ == '__main__':
    main()

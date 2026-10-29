"""Generate a source-backed scoped report after the frozen analysis completes."""
import csv
import hashlib
import importlib.metadata
import json
from pathlib import Path
import numpy as np
from user_tools.workbench.action_validation import write_csv

ROOT=Path('outputs/analysis/action_study_20261015')
SCENARIOS=['matched_no_coupling','coupled_ranking_stable','coupled_ranking_sensitive','cubic_discrepancy','outside_model_sinusoid']
SCENE_LABELS=['无耦合','耦合但排序稳','耦合影响排序','模型内协议差异','模型外正弦偏差']


def main():
    data=json.loads((ROOT/'validation/analysis.json').read_text())
    dev=json.loads((ROOT/'development/result.json').read_text())
    protocol=json.loads((ROOT/'frozen_protocol.json').read_text())
    precision=json.loads((ROOT/'numerical/summary.json').read_text())
    refined=json.loads((ROOT/'numerical/quad_refinement.json').read_text())
    primary=data['contrasts'][0]; by={(r['scenario'],r['policy']):r for r in data['summary']}
    contrasts={r['comparison']:r for r in data['contrasts']}
    n=protocol['instances_per_scenario']
    means={p:float(np.mean([by[s,p]['simple_regret_mean'] for s in SCENARIOS]))
           for p in ['full__kg','full__contrast_variance','full__ei']}
    d={(r['scenario'],r['instance'],r['policy']):r for r in dev['campaigns']}
    exact_minus_gh=[]; changed=0
    for key,r in d.items():
        if key[2]=='full__kg':
            gh=d[key[0],key[1],'full__gh31']
            exact_minus_gh.append(r['simple_regret']-gh['simple_regret'])
            changed+=r['selected_id']!=gh['selected_id']
    path_check={'development_instances':len(exact_minus_gh),'changed_terminal_candidates':changed,
                'exact_minus_gh31_mean_regret':float(np.mean(exact_minus_gh)),
                'scope':'paired development paths, not held-out or novel algorithm evidence'}
    legacy=json.loads(Path('outputs/analysis/action_validation_20261014_v3/result.json').read_text())
    legacy_cases={(r['scenario'],r['seed'] if 'seed' in r else r['instance']):r
                  for r in legacy['campaigns'] if r['policy']=='joint_cost_kg'}
    for key,r in d.items():
        if key[2]!='full__gh31': continue
        old=legacy_cases[key[0],key[1]]
        assert old['recommendation_id']==r['selected_id']
        assert abs(old['simple_regret']-r['simple_regret'])<1e-10
        assert abs(old['spent']-r['spent'])<1e-10
        assert old['observations']==r['observations']
    path_check['gh31_reproduces_original_full_model_episodes']=len(legacy_cases)
    (ROOT/'numerical/path_comparison.json').write_text(json.dumps(path_check,indent=2),encoding='utf-8')
    frozen_hash=hashlib.sha256((ROOT/'frozen_protocol.json').read_bytes()).hexdigest()
    for filename,wanted in protocol['source_hashes'].items():
        assert hashlib.sha256(Path(filename).read_bytes()).hexdigest()==wanted
    lines=['# 测量动作选择合成验证：最终结论与证据', '',
        '日期：2026-10-15。范围：原有13候选、单目标、5类数学场景；没有扩展平台或真实材料实验。', '',
        '**主要结论：锁定验证集未证明KG/费用相对目标对比方差缩减/费用具有预定的总体优势。支持的机制证据主要是：保留联合参数不确定性及协议差异项，在两种选点准则下均有收益。未发现新的优化采集函数。**', '',
        '## 1. 核心问题和事先标准', '',
        '唯一主要比较是完整联合模型的解析KG/费用与同模型目标A最优对比方差缩减/费用。两者共享相同先验、初始观测、观测映射、候选和测量权限、费用、停止、预算及终端规则。固定r与删除差异项仅作模型消融，不能替代强对手。EI/费用只是第三个传统参考。', '',
        f'五类场景等权；每类{n}个新独立真值/噪声实例，编号20000—{20000+n-1}。共{5*n}个统计单位、{5*n*7}个配对方法场次；不能把全部方法场次当独立样本。原实例1000—1039、旧烟测和本轮开发比较都未进入新验证统计。', '',
        '主要指标为终端简单遗憾（有限候选真实最大效用−最终所选效用），单位是无量纲合成效用。总预算上限10相对单位，初始费用2.4、预留最终确认费1.6，搜索最多6；实际支出可以不同，余额单列。没有人民币、LCA或实际材料性能解释。', '',
        '成功标准在验证前冻结：整体配对差Δ=KG遗憾−A最优遗憾的分层bootstrap双侧95%区间上端小于−0.01。0.01是数学研究中斜率先验标准差1的1%，不是实验实用收益门槛。', '',
        f'开发方差计算的n_required={protocol["n_required_by_development_variance"]}，按预定40/80/160档取{n}。目标是整体区间半宽约0.03的精度规划，不保证检出0.01效应。冻结UTC时间：{protocol["frozen_at_utc"]}；协议SHA-256：`{frozen_hash}`。这是本地冻结，不是外部预注册。', '',
        '## 2. 主要结果', '',
        '| 完整观测模型下的方法 | 五场景等权平均简单遗憾 |', '|---|---:|',
        f'| 解析KG/费用 | {means["full__kg"]:.6f} |',
        f'| 目标对比方差缩减/费用 | {means["full__contrast_variance"]:.6f} |',
        f'| plug-in EI/费用 | {means["full__ei"]:.6f} |', '',
        f'主要差Δ={primary["mean_difference"]:.6f}，95%区间[{primary["bootstrap_95_lower"]:.6f}, {primary["bootstrap_95_upper"]:.6f}]。**未达到事先标准，区间也包含零，不能声称总体优越或等效。**', '',
        f'逐实例胜/平/负为{primary["wins"]}/{primary["ties"]}/{primary["losses"]}，配对差中位数{primary["median_difference"]:.6f}；最大单实例差绝对值{primary["maximum_absolute_instance_difference"]:.6f}，删去一个实例最多改变整体均值约{primary["leave_one_out_max_mean_change"]:.6f}。整体均值和区间必须一起解释，不能只报获胜比例或开发集改善。', '',
        '| 场景 | KG遗憾 | 目标方差准则遗憾 | EI遗憾 | KG实际支出 | KG名义95%区间真值命中 |',
        '|---|---:|---:|---:|---:|---:|']
    for s,label in zip(SCENARIOS,SCENE_LABELS):
        r=by[s,'full__kg']
        lines.append(f'| {label} | {r["simple_regret_mean"]:.6f} | {by[s,"full__contrast_variance"]["simple_regret_mean"]:.6f} | '
            f'{by[s,"full__ei"]["simple_regret_mean"]:.6f} | {r["spent_mean"]:.4f} | {r["interval_fraction_mean"]:.1%} |')
    lines += ['', '这些分场景数字用于解释，不能事后删除不利场景或替换主要比较。模型外正弦情形中，KG的误差仍很大、区间覆盖明显不足；其名义95%不是覆盖保证。', '',
        '## 3. 收益来源：观测模型×选点准则', '',
        '模型效应=完整模型遗憾−对应消融遗憾，负值有利完整模型；交互效应=KG下模型效应−方差准则下模型效应。7项次要检验为同一Holm校正族，p值采用分层标准误与Satterthwaite近似t检验，并要求bootstrap区间也排除0。Holm只覆盖这七项次要检验，未宣称整篇所有主张的联合错误率。近似推断不构成有限样本保证。', '',
        '| 对比 | 差均值 | 95%配对区间 | Holm校正p | 支持 |', '|---|---:|---|---:|---|']
    labels={'secondary_kg_vs_ei':'KG−EI（完整模型）','radius_effect_kg':'联合r不确定性：KG',
        'radius_effect_variance':'联合r不确定性：方差准则','discrepancy_effect_kg':'协议差异项：KG',
        'discrepancy_effect_variance':'协议差异项：方差准则','radius_interaction':'r模型×选点准则交互',
        'discrepancy_interaction':'差异模型×选点准则交互'}
    for r in data['contrasts'][1:]:
        lines.append(f'| {labels[r["comparison"]]} | {r["mean_difference"]:.6f} | '
            f'[{r["bootstrap_95_lower"]:.6f}, {r["bootstrap_95_upper"]:.6f}] | {r["holm_adjusted_p"]:.5g} | '
            f'{"是" if r["secondary_supported"] else "否"} |')
    lines += ['', '两种准则下的模型效应均受到支持，而交互证据不足。这与“改善不依赖KG独有机制”的解释一致；不能据此证明交互严格为零，也不能把改善完全归因于某一组件。固定坐标消融还包含把未知参数错误地当作已知的影响，结论应限定于这个明确的对照。', '',
        '## 4. 数值核验与旧结果重建', '',
        '原1400场从真值种子、原始观测、动作、后验和终端记录重建；独立实现使用白化批量精度矩阵求解，没有导入实验实现。旧v2全指标/采集分数审计通过两个版本定位改动适配到历史冻结源码后重新执行；原文件和结果不变，再由v3终端审计验证等价。记录见original_reconstruction.json和reconstruction/receipt.json。', '',
        '旧v2没有单独保存先于真值/确认读取的终端承诺；v3已补上该承诺，但两版确认仍仅保存均值。旧三读数可按种子重建，不等于当时逐项留存。新开发与新验证才同时保存终端承诺及全部三个确认原始读数。', '',
        f'原KG类决策共{precision["states"]}个状态、{precision["all_available_action_scores_crosschecked"]}个可用动作分数，经解析包络与独立全交点积分交叉计算，最大差{precision["independent_crossing_max_error"]:.3g}。', '',
        '| 近似 | 相对解析KG的动作/停止差异数 | 状态数 | 最大采集分数误差 |', '|---|---:|---:|---:|']
    for q,r in precision['counts'].items():
        lines.append(f'| GH{q} | {r["different_actions"]} | {precision["states"]} | {r["max_score_error"]:.6f} |')
    lines += ['', '动作ID差异中可包含等分并列，不能全部解释为有意义的决策损失；frozen_state_comparison.csv另列每次选择在解析准则下的采集值损失。', '',
        f'同200个开发实例的完整路径对照中，解析KG与GH31的终端候选有{changed}例不同，平均遗憾差（解析−GH31）为{path_check["exact_minus_gh31_mean_regret"]:.6f}。GH31的全部200场完整观测、推荐、费用和遗憾与原v3联合模型一致，保证差异来自积分替换。这是数值近似对路径的影响，不是新算法收益。', '',
        f'35个SciPy自适应积分抽查最初有近重合交点导致的QUADPACK警告；summary保留当次误差估计，初始stderr未单独归档。工具会话中的警告摘录事后保存于numerical/initial_warning_transcript_excerpt.txt，并标明来源局限。按分离区间重算，警告数为{refined["warning_count"]}、最大绝对差{refined["max_absolute_error"]:.3g}。', '',
        '新验证的全部观测、后验、动作采集分数、终端推荐、真值、费用和三次确认读数由独立批量/交点实现重算，见validation_verification.json。分数并列只要求选中分数在数值容差内达到最大，不把独立浮点实现的同分ID差异误判为错误。', '',
        '## 5. 已有方法与增量定位', '',
        '在固定候选、可积目标、模型内部一致条件化及最大后验均值终端规则下，期望简单遗憾下降=标准KG。推导和假设见docs/action_study_20261015_method.md。除以费用是一步比值启发式，没有全预算最优性。解析上包络计算也属于已发表方法。', '',
        '一手依据：Frazier等2009相关正态KG的第3.1节、Algorithm1/2；Daulton等ICML2023的部分观测决策；Astudillo等NeurIPS2021及附录的预算/费用讨论；BoTorch固定提交的KG和cost-aware源码。归档PDF、补充材料、提交与哈希见references/index.json。', '',
        '运行环境没有torch、GPyTorch、BoTorch，本轮查阅了作者源文件，没有假称执行其代码。独立数值实现能检查公式与计算一致性，不能替代跨库复现或外部同行科学接受。当前贡献是受控观测模型/动作接口与可检查的验证流程，未证明新采集函数。', '',
        '## 6. 可用于论文的结论', '',
        '| 主张 | 状态 | 可以如何表述 / 还缺什么 |', '|---|---|---|',
        '| 实现了可复现的有限测量动作选择 | 可限定写入 | 说明线性高斯、确定模拟费用、有限候选及数值容差 |',
        '| 联合不确定性与差异项改善推荐 | 可限定写入 | 两种准则中的消融效应受到支持，限制于既定生成器和错误固定坐标对照 |',
        '| KG整体胜过目标方差准则或EI | 当前不支持 | 主要比较区间含零；EI次要比较亦未支持；不能以开发效果代替 |',
        '| 增益由KG独有交互带来 | 当前不支持 | 两项交互没有通过预定次要标准 |',
        '| 模型外可靠或95%覆盖 | 当前不支持 | 正弦偏差场景失败，名义区间明显欠覆盖 |',
        '| 提出新优化算法 | 当前不支持 | 规则和解析计算与已有KG同属已知方法，需另有明确且查新的方法增量 |',
        '| 降低真实费用或提高再生石墨性能 | 本轮未检验 | 需另行真实成本及独立材料验证，本轮范围不包含 |', '',
        '建议论文措辞：“在预先冻结的单目标合成测量任务中，联合参数不确定性和协议差异建模在两种采样准则下改善了相对指定消融的终端选择质量；KG/费用相对目标对比方差准则的预定总体优势未获支持，模型外偏差仍导致明显的区间欠覆盖。”', '',
        '## 7. 复现与限制', '',
        '完整命令见REPRODUCE.md。自适应测量动作先承诺，再揭示该动作的观测结果；终端候选先承诺，再读取真值和确认结果。原始观测本身并非揭示前已知。确认结果不反馈训练；三次读数逐项保存在confirmation_reads.csv。本模拟器没有随机制造失败，不能据此声称能处理真实失败。', '',
        '新验证与开发实例分离，但生成器、候选空间和费用仍是人为规定；这是对固定数学任务分布的局部确认，不是跨材料泛化。未新增强黑箱ARD-GP或多目标HVKG竞赛，因此不能概括所有BO。统计区间和t检验均为近似方法。外部人工复现和外部科学接受尚未取得；fresh-agent审阅及文档复跑见audit/，仅标记same-family/provisional。冻结清单不是整个软件环境锁文件；provenance/是事后环境与辅助源码收据，不能补成事前完整冻结。', '']
    (ROOT/'report.md').write_text('\n'.join(lines),encoding='utf-8')
    claims=[{'claim':'Frozen overall KG advantage','status':'not_supported','evidence':'validation/contrasts.csv:primary_kg_vs_variance'},
        {'claim':'Joint uncertainty model helps versus specified fixed-coordinate ablation','status':'supported_with_scope','evidence':'radius_effect_kg;radius_effect_variance'},
        {'claim':'Protocol discrepancy model helps versus omitted-term ablation','status':'supported_with_scope','evidence':'discrepancy_effect_kg;discrepancy_effect_variance'},
        {'claim':'KG-specific interaction','status':'not_supported','evidence':'radius_interaction;discrepancy_interaction'},
        {'claim':'Novel acquisition function','status':'not_supported','evidence':'docs/action_study_20261015_method.md'},
        {'claim':'Real material or actual cost improvement','status':'not_tested','evidence':'simulation_only'}]
    write_csv(ROOT/'claims.csv',claims)
    versions={k:importlib.metadata.version(k) for k in ['numpy','scipy','matplotlib']}
    (ROOT/'runtime_versions.json').write_text(json.dumps(versions,indent=2),encoding='utf-8')
    plots(data,by,precision)
    print(json.dumps({'report':str(ROOT/'report.md'),'primary':primary,'path_comparison':path_check},ensure_ascii=False))


def plots(data,by,precision):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    folder=ROOT/'figures'; folder.mkdir(exist_ok=True)
    fig,axs=plt.subplots(1,2,figsize=(14,5.3),constrained_layout=True)
    x=np.arange(5); labels=['No coupling','Stable rank','Sensitive rank','Cubic discrepancy','Outside model / sine']
    for j,(p,label,color) in enumerate([('full__kg','Exact KG / cost','#176b9a'),
        ('full__contrast_variance','Target A-optimal / cost','#dc8b26'),('full__ei','Plug-in EI / cost','#59945c')]):
        axs[0].bar(x+(j-1)*.24,[by[s,p]['simple_regret_mean'] for s in SCENARIOS],width=.23,label=label,color=color)
    axs[0].set_yscale('log'); axs[0].set_ylabel('Mean simple regret (synthetic utility, log scale)')
    axs[0].set_xticks(x,labels,rotation=20,ha='right'); axs[0].legend(fontsize=8); axs[0].grid(axis='y',alpha=.15)
    cs=data['contrasts']; names=['Primary: KG - target A-opt','KG - EI','Radius model / KG','Radius model / A-opt',
        'Discrepancy / KG','Discrepancy / A-opt','Radius interaction','Discrepancy interaction']
    for j,r in enumerate(cs):
        value=r['mean_difference']; low=r['bootstrap_95_lower']; high=r['bootstrap_95_upper']
        axs[1].errorbar(value,j,xerr=[[value-low],[high-value]],fmt='o',capsize=3,
                       color='#176b9a' if r.get('secondary_supported') else '#777777')
    axs[1].axvline(0,color='black',lw=.8); axs[1].set_yticks(range(len(cs)),names); axs[1].invert_yaxis()
    axs[1].set_xlabel('Paired mean regret contrast with 95% bootstrap interval')
    axs[1].set_title('Marginal intervals; blue: Holm-supported secondary',fontsize=9)
    axs[1].grid(axis='x',alpha=.15)
    fig.suptitle('Frozen validation: primary superiority not established; model effects supported within scope')
    fig.savefig(folder/'study_summary.png',dpi=180); fig.savefig(folder/'study_summary.svg'); plt.close(fig)
    fig,ax=plt.subplots(figsize=(6.7,4.0),constrained_layout=True)
    rates=[100*precision['counts'][str(n)]['different_actions']/precision['states'] for n in [31,63,127]]
    ax.bar(['31 nodes','63 nodes','127 nodes'],rates,color=['#377eaa','#62a4bd','#91bac9'])
    ax.set_ylabel('Action / stop ID differences versus exact KG (%)')
    ax.set_title('Development frozen states; ties may be included')
    for i,v in enumerate(rates): ax.text(i,v+.08,f'{v:.2f}%',ha='center')
    ax.set_ylim(0,max(rates)*1.25); ax.grid(axis='y',alpha=.15)
    fig.savefig(folder/'quadrature_differences.png',dpi=180); fig.savefig(folder/'quadrature_differences.svg'); plt.close(fig)

if __name__=='__main__': main()

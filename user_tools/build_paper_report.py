"""Source-anchored learning ledger for all supplied papers and audited code."""
from pathlib import Path
import html
import json

STUDIES=[
 {'id':'eis_2025','title':'Physics-Based Battery Model Parametrisation from Impedance Data','venue':'JES172,060507(2025)','repo':'hallemans_2025',
  'pages':'PDF2–15；TableII、Eq7/9、实验与附录B/C；封面/参考文献未逐条核查',
  'method':'离散模型线性化，用(jωM−J)x=B计算小信号频域阻抗；跨SOC共享分组参数拟合，随后进行锁定参数的时域验证。',
  'evidence':'PDF6TableII：τd=R²/D；PDF9–12：平坦OCP区域灵敏度下降，实测低频拟合仍有失配；优化重复运行的窄离散程度不能替代可辨识性分析。论文是LG M50LT全电池案例。',
  'code':['Fig10_EIS_Fitting_LGM50LT.py','Fig11_validationLGM50LT.py','Fig12_tauSensitivity.py','requirements.txt','LICENSE'],
  'hazards':'原文使用PyBaMM24.9，当前源码锁25.6，与本机26.8不同。脚本的电导率1e16是分组模型近似，不是材料实测值；OCP外推和不同PSO迭代数需记录。联合时域+EIS拟合是可借鉴的延伸，不是本文已经展示的联合目标验证。',
  'state':'已接入：谱CSV/单位/符号检查、Nyquist及Bode数值、公开模型EIS。版本适配，不是18参数拟合复现。',
  'next':'同样品OCP、跨SOC实测EIS、激励线性/稳态证据；跨状态拟合与留出时域验证。',
  'tests':'RC解析传递函数与时域积分一致；SPM全电池和石墨/Li半电池实际频域求解；Hz/rad/s及Ω/mΩ转换。'},
 {'id':'boed_2019','title':'Variational Bayesian Optimal Experimental Design','venue':'NeurIPS2019','repo':'boed_pyro',
  'pages':'主文PDF1–9；上传文件未包含文中引用的完整补充附录A–G',
  'method':'最大化预期信息增益EIG，提出后验变分下界、边际上界、VNMC及隐式似然估计器。',
  'evidence':'PDF1Eq1、PDF2Eq3/4、PDF3–5Eq6–14、PDF6收敛假设；模拟模型、先验、噪声和估计器近似共同决定设计可靠性。本文实验不是电池验证。',
  'code':['pyro/contrib/oed/eig.py','tests/contrib/oed/test_linear_models_eig.py','examples/contrib/oed'],
  'hazards':'原始vboed-reproduce分支使用旧Pyro/Torch；不能把当前API直接当原实验环境。小MC标准误不能说明变分偏差小；相关电压时间点不能随意当独立测量。',
  'state':'已建立线性高斯EIG解析基准与测试；未接入完整变分BOED或可靠真实电化学协议推荐。',
  'next':'明确目标参数组合/独立几何信息、协议生成器、先验和相关噪声模型，再验证候选协议选点。',
  'tests':'0.5logdet解析真值；无信息观测为0；更大噪声减少信息；相关观测不能按独立重复计算。'},
 {'id':'basq_2022','title':'Fast Bayesian Inference with Batch Bayesian Quadrature via Kernel Recombination','venue':'NeurIPS2022','repo':'basq',
  'pages':'主文PDF1–10、Algorithm1及电池案例；完整独立补充证明/原始电池实现未提供',
  'method':'GP/WSABI近似似然并计算证据与后验；非负核重组保存矩与质量，批量选择昂贵似然计算点。不是直接选新再生实验。',
  'evidence':'PDF6Algorithm1，PDF8电池案例；电池基准并非所有指标都胜过对照，部分运行时间不含仿真器成本；理论只涵盖简化设置。',
  'code':['BASQ/_basq.py','BASQ/_parameters.py','BASQ/_rchq.py','main.py','README.md'],
  'hazards':'README说明原GPy比较实现未完整公开。当前_rchq.py接收init_weights，却在重组内部用均匀mu覆盖，重要性权重路径必须先修复并验证矩保存；默认例子是10维高斯混合，不是电池论文复现。',
  'state':'已完成源码审阅和版本归档；没有迁入未核查的BASQ实现。',
  'next':'隔离Torch/GPyTorch/BoTorch环境；规范似然与先验；修复权重，验证高斯积分、多峰后验和模型证据。',
  'tests':'权重/质量/矩保存、似然下溢、已知证据、同观测与噪声模型的比较；后验窄不自动等于本征Ds可辨识。'},
 {'id':'nehvi_2021','title':'Parallel Bayesian Optimization of Multiple Noisy Objectives with Expected Hypervolume Improvement','venue':'NeurIPS2021','repo':'botorch',
  'pages':'PDF4–7§5/6、Eq2–5；实验与附录相关部分',
  'method':'联合抽样已测点和候选的潜在函数，每个样本重新建立前沿并计算超体积改进。',
  'evidence':'NEHVI需要基线–候选后验协方差；固定实测前沿或仅扰动候选不是NEHVI。q版本有专门并行分解/缓存，不等于本地q=1枚举。',
  'code':['botorch/acquisition/multi_objective/monte_carlo.py','botorch/acquisition/multi_objective/logei.py'],
  'hazards':'train_Yvar是方差，不是标准差；条件均值的噪声需按实际重复数确定。约束和参考点需在同一单位体系；后验噪声不应在潜在函数采样时再加一遍。',
  'state':'已接入受限的有限候选q=1 MC-NEHVI，两个独立GP、固定超参数；保留原EHVI。未复现官方并行或连续算法，也未证明石墨优化胜过随机。',
  'next':'独立条件留出校准与公平多种子回放；完整qLogNEHVI可选隔离官方依赖。',
  'tests':'联合条件高斯协方差解析核对；同位置共享同潜在样本，增益严格0；MC标准误、固定种子、pending和未来标签隔离。'},
 {'id':'logei_2023','title':'Unexpected Improvements to Expected Improvement for Bayesian Optimization','venue':'NeurIPS2023','repo':'botorch',
  'pages':'PDF5–7§3/4、Eq8–11及数值实现附录A2–A4',
  'method':'在对数空间及平滑近似中计算EI/批量EHVI，避免数值下溢和梯度消失。',
  'evidence':'先算出下溢的EI再取log不能恢复丢失信息；qLogNEHVI不仅是log(固定前沿EHVI)。有限枚举不具备连续梯度优化的全部收益。',
  'code':['botorch/acquisition/logei.py','botorch/acquisition/multi_objective/logei.py'],
  'hazards':'官方代码要求Torch/GPyTorch/BoTorch与版本固定；数值稳定不修复错误标签、模型失配或噪声未校准。',
  'state':'已完成方法/源码对照；未安装重型依赖或宣称qLogNEHVI已接入。',
  'next':'连续/并行优化需要时建立隔离后端，检查平滑参数、联合后验、pending与参考点变换。',
  'tests':'负尾z=-10/-50/-100、普通EI一致性、σ边界、平滑温度敏感性；不能只检查返回非零数。'},
 {'id':'be_cbo_2024','title':'Boundary Exploration for Bayesian Optimization With Unknown Physical Constraints','venue':'ICML2024','repo':'be_cbo',
  'pages':'PDF3–6§3/4Eq1及分类器/实验附录相关部分',
  'method':'从成功/不可行实验学习可行性边界，目标GP只用可行点；边界不确定性参与采集约束。',
  'evidence':'深度集成通过变分ELBO分类；失败没有有意义的目标值时仍提供可行性信息，但不应填零容量。',
  'code':['algorithms/becbo/becbo.py','model/classifier/de.py','model/predict.py'],
  'hazards':'旧botorch0.6.5/gpytorch1.7，Python3.7/3.8。无可行点会assert；初始化失败可能随机回退；1维输入隐藏层维度需防护。学习边界不保证实验安全。',
  'state':'已完成失败类型、源码、许可证审阅；未迁入旧神经分类器。',
  'next':'先记录真实制备不可行、仪器故障、缺元数据、求解失败和低性能成功的不同标签；已批准硬边界始终保留。',
  'tests':'无可行点/单类、标签噪声、断开可行域、内部最优、失败尝试计入预算；随机回退不得越硬边界。'},
 {'id':'imfbo_2024','title':'Multi-fidelity Bayesian Optimization with Multiple Information Sources of Input-dependent Fidelity','venue':'UAI2024','repo':'imfbo',
  'pages':'PDF3–5Eq13/14、PDF12Alg1、PDF15成本/偏差附录及理论假设',
  'method':'共享潜在目标GP、输入相关信息源噪声δj(x)，选择输入和信息源；成本只作用于探索项。',
  'evidence':'均值+sqrt(βt)σ²/sqrt(σ²+δj²)；系统性偏差需要另加gj(x)，不能把仿真偏差仅当零均值噪声。A/B材料批次不是同一目标的两个保真度。',
  'code':['acquisition_function.py','surrogates.py','requirements.txt'],
  'hazards':'源码beta**step_num与论文sqrt(βt)需核查；依赖旧Torch/Pyro/GPyTorch且requirements有作者本机路径。先验/噪声/成本和同域配对数据不足时不能可靠调度。',
  'state':'已完成完整接入前提与源码审阅；未把不同材料/协议数据混成多保真训练。',
  'next':'同材料、同协议、同目标的SPM/SPMe/DFN与实验配对，以及误差、成本、失败率记录。',
  'tests':'跨输入可信度反转、零噪声UCB极限、标准差/方差、正确成本项、偏差负例和相同预算比较。'},
 {'id':'sc_cp_2024','title':'Self-Calibrating Conformal Prediction','venue':'NeurIPS2024','repo':'sc_cp',
  'pages':'PDF5Alg1/2、PDF7Th4.1/4.2、PDF8限制、PDF19SetupC及实现/实验相关部分',
  'method':'对假定未来y做增广等距回归，在该校准预测的level-set内取残差分位，建立接受集合。',
  'evidence':'保证条件是含真实未来y的未知oracle校准预测，不是展示的点估计。相关性、主动选点、A/B漂移会破坏交换性；实验校准规模远大于当前18条件。',
  'code':['selfcalibratingconformal/regression.py','pyproject.toml','tests'],
  'hazards':'现代仓库1.12.0支持Python3.9–3.12；默认响应网格可能只涵盖校准标签范围，网格/插值和点修正不自动继承连续理论。',
  'state':'已接入独立组冻结预测器的split-conformal轻量适配，明确不是完整SC-CP。95%阶次不足时无界且不报告虚假的100%覆盖。',
  'next':'独立训练/校准/留出条件；适用域和采样方式明确；完整SC-CP作为有足够校准数据的可选后端。',
  'tests':'精确阶次、ties、小n无界、分组泄漏、A/B不混合；完整算法还需网格收敛和范围扩展测试。'}
]


def main():
    root=Path(__file__).resolve().parents[1];out=root/'outputs/paper_study_20261012'
    papers={r['id']:r for r in json.loads((out/'paper_manifest.json').read_text(encoding='utf-8'))}
    sources={r['id']:r for r in json.loads((root/'data/external/algorithm_sources_20261013/source_manifest.json').read_text(encoding='utf-8'))}
    entries=[]
    for study in STUDIES:
        license_name='BSD-3-Clause' if study['repo'] in ['hallemans_2025','basq'] else 'MIT'
        entries.append({**study,'source_license':license_name,'paper':papers[study['id']],'source_snapshot':sources[study['repo']]})
    (out/'study_ledger.json').write_text(json.dumps(entries,ensure_ascii=False,indent=2),encoding='utf-8')
    esc=html.escape
    items=[]
    for entry in entries:
        repo=entry['source_snapshot'];pdf=Path(entry['paper']['archive']).as_uri()
        items.append('<section><h2>'+esc(entry['title'])+'</h2><p>'+esc(entry['venue'])+' · <a href="'+pdf+'">本地原文</a> · <a href="'+esc(repo['url'].removesuffix('.git'))+'">作者源码</a> · '+entry['source_license']+'</p><p class="status">'+esc(entry['state'])+'</p>'+''.join('<h3>'+label+'</h3><p>'+esc(entry[key])+'</p>' for label,key in [('读取范围','pages'),('方法','method'),('证据定位','evidence'),('实现差异/风险','hazards'),('接入前提','next'),('验证要求','tests')])+'<p>核查文件：'+esc(', '.join(entry['code']))+'</p><details><summary>来源与版本</summary><pre>'+esc(json.dumps({'paper_sha256':entry['paper']['sha256'],'source_commit':repo.get('commit'),'source_path':repo.get('path')},ensure_ascii=False,indent=2))+'</pre></details></section>')
    page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>八篇论文与源码学习记录</title><style>body{font:16px/1.7 system-ui,"Microsoft YaHei";background:#f4f5fb;color:#27334a;margin:0}main{max-width:1040px;margin:auto;padding:32px}section{background:white;border:1px solid #dddfee;border-radius:12px;padding:24px;margin:22px 0}h1,h2{color:#5754bd}h2{font-size:21px}h3{font-size:16px;margin-bottom:0}p{margin-top:5px}.status{padding:12px;background:#efeffb}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}a{color:#5754bd}</style><main><h1>八篇论文与作者源码：学习与接入记录</h1><p>8篇原文175页已归档；读取覆盖范围逐篇说明，缺少的补充资料不冒充完整复现。7个源码仓库固定提交/快照，保留许可证；未运行上游研究脚本或降级现有科学环境。</p><p>现有G5/G6、Chen留出失败与公开石墨BO比较结果保留。方法适配、软件测试、论文实验复现与真实材料验证是不同状态。</p>'+''.join(items)+'</main></html>'
    (out/'论文与源码学习报告.html').write_text(page,encoding='utf-8');print('8entries,7source_snapshots,175pages')


if __name__=='__main__':main()

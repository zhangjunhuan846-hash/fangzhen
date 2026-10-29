"""Build a source-backed reading and integration report, not an experiment claim."""
from pathlib import Path
import hashlib
import html
import json

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/descriptor_paper_study_20261013'
EVIDENCE = [
    {'paper': 'TabPFN / Nature 2025', 'pages': 'PDF 1–5、9、12–13',
     'method': '合成任务先验预训练、表格 in-context 推断；回归输出分段预测分布。',
     'evidence': '29分类+28回归数据集，≤10000样本/500特征；领域清洗与特征工程仍重要。',
     'integration': '作为可选本地模型，与GP、岭回归/PLS、树模型共用分组划分和预算。',
     'limits': '几十组石墨不保证收益；当前默认3.5不等于论文v2；权重与源码分别许可；预测分布需要材料数据校准。'},
    {'paper': 'TabArena / NeurIPS 2025 Datasets & Benchmarks', 'pages': 'PDF 2–6、9–10、35–36',
     'method': '统一模型adapter、重复外层评测、预算管理、调参与集成比较。',
     'evidence': '2025 v0.1明确排除<500训练样本与非IID任务；作者报告验证集过拟合问题。',
     'integration': '借用评测架构：共享分组划分、逐折预测缓存、训练折内预处理与筛选、版本/种子/预算。',
     'limits': '不能拿原论文模型榜证明十八组工艺有效；当前BeyondArena扩展不补写进2025论文结论。'},
    {'paper': 'SISSO主动学习 / npj Computational Materials 2025', 'pages': 'PDF 1–5',
     'method': '稀疏符号组合描述符，bootstrap与特征dropout构建模型集成并主动选点。',
     'evidence': '250个初始氧化物、1470个候选，30轮DFT；10模型与20%特征dropout；按正态可行概率选点。',
     'integration': '受控公式搜索、单位和定义域检查、复杂度—误差比较、入选稳定性。',
     'limits': '公式不是因果机制；样本少应严格限复杂度。workflow主估计器只找到bootstrap，未找到论文feature dropout；ensemble不确定性也不自动校准。'},
    {'paper': '重要性排名显著性 / UAI 2025', 'pages': 'PDF 2–7、10–11',
     'method': '对重要性抽样估计进行检验，识别可验证的前K集合与排序。',
     'evidence': '严格保证有独立、正态、无偏估计和oracle方差等前提；实际实现用估计方差/CLT，不是批次迁移保证。',
     'integration': '重采样入选频率、排名区间和必要时显著性检验；相关变量成组解释。',
     'limits': '源码HelperFiles/helper.py第54行将NaN判为reject，需保守处理并单独验证；根目录未找到明确许可证，不直接复制。'},
    {'paper': '高维BO / ICML 2025', 'pages': 'PDF 3–7、14',
     'method': 'MSR：Matérn5/2 ARD，长度尺度初始化sqrt(d)/10，MLE、LogEI与RAASP局部候选采样。',
     'evidence': '分析尺度与梯度失效，局部搜索可改善高维连续优化。',
     'integration': '多变量连续工艺优化时诊断核尺度、搜索梯度，比较局部与全局候选搜索。',
     'limits': '先归一到[0,1]再用尺度规则；不是描述符自动发现；伴随源码异常会随机fallback，应显示记录。旧LeoIV链接404，伴随实现已归档。'},
    {'paper': '多保真BO / Nature Computational Science 2025', 'pages': 'PDF 1–6',
     'method': '比较低/高保真成本、信息性与单/多保真采集策略。',
     'evidence': '论文约0.05成本比与R²>0.80为研究范围内经验起点；二等级基准，非通用保证。',
     'integration': '同条件模拟/短测试与实验建立可验证关联后，比较按总观测预算的单/多保真策略。',
     'limits': 'A/B批次不是保真等级；需联合GP跨保真协方差而非两个独立GP；按成本轴HF regret评测；旧Torch/NumPy依赖需独立环境。'},
]

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sources = json.loads((ROOT / 'data/external/ml_full_sources_20261013/manifest.json').read_text(encoding='utf-8'))
    papers = json.loads((OUT / 'paper_manifest.json').read_text(encoding='utf-8'))
    checks = []
    for source in sources:
        if source['status'] != 'archived':
            checks.append({'repository': source['repository'], 'status': 'unavailable', 'reason': source.get('reason')})
            continue
        archive = ROOT / 'data/external/ml_full_sources_20261013' / (source['repository'].replace('/', '__') + '.zip')
        valid = hashlib.sha256(archive.read_bytes()).hexdigest() == source['archive_sha256']
        if not valid:
            raise ValueError('Archive hash mismatch: ' + source['repository'])
        checks.append({'repository': source['repository'], 'status': 'hash_verified', 'commit': source['commit']})
    result = {'scope': 'paper/source review; no upstream execution or material validation', 'papers': papers,
              'evidence': EVIDENCE, 'sources': sources, 'verification': checks}
    (OUT / 'study_ledger.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    esc = html.escape
    cards = ''.join('<article><h2>' + esc(r['paper']) + '</h2><p class="anchor">' + esc(r['pages']) + '</p>' +
                    ''.join('<p><b>' + title + '：</b>' + esc(r[key]) + '</p>' for key, title in
                            [('method', '方法'), ('evidence', '证据'), ('integration', '怎么借鉴'), ('limits', '接入限制')]) + '</article>' for r in EVIDENCE)
    rows = ''.join('<tr><td><a href="' + esc(r['url']) + '">' + esc(r['repository']) + '</a></td><td>' +
                   ('已下载 · ' + str(r['files']) + '文件' if r['status'] == 'archived' else '未取得：' + esc(r.get('reason', ''))) +
                   '</td><td><code>' + esc((r.get('commit') or '')[:12]) + '</code></td></tr>' for r in sources)
    pdfrows = ''.join('<li><a href="' + Path(r['path']).as_uri() + '">' + esc(r['name']) + '</a> · ' + str(r['pages']) + '页</li>' for r in papers)
    text = '''<!doctype html><html lang="zh"><meta charset="utf-8"><title>描述符与机器学习：论文、源码和接入</title>
<style>body{font:16px/1.75 system-ui,sans-serif;background:#f4f6f9;color:#19263b;max-width:1080px;margin:40px auto;padding:0 24px}article,section{background:white;padding:24px;margin:20px 0;border-radius:12px}h1{font-size:30px}h2{font-size:21px}.anchor{color:#617188}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:10px;border-bottom:1px solid #dde4ee}a{color:#245bb3}code{font-size:12px}</style>
<h1>描述符与机器学习：源码归档与接入评估</h1><p>2026-10-13 · 六篇论文149页 · 18个源码快照 · 1个旧仓库404</p>
<section><h2>完成范围</h2><p>论文已完整提取逐页文本；本轮重点阅读主方法、实验设计和相关附录。源码下载为完整仓库文件快照，保留ZIP、许可证与提交号，并复核18个ZIP的SHA256。没有安装或运行上游依赖，也没有声称全部算法复现。</p><p>源码快照不含Git历史、子模块内容、LFS实际载荷及外链权重/数据。已有目录中的数据文件随源码保留，pickle与notebook均未执行。</p></section>
<section><h2>推荐接入次序</h2><ol><li>统一样品关联与自由选描述符、目标；声明推荐时已知/未知字段。</li><li>借TabArena评测架构，先比较GP、岭回归/PLS、树模型；折内筛选和分组评测。</li><li>借FABO动态选择描述符，并与固定描述符严格多种子回放比较。</li><li>借BayBE混合类别/连续变量、配方约束、待测与部分目标状态。</li><li>追加重要性稳定性与受控符号描述符；谱特征按技术分开提取。</li><li>数据满足时再开TabPFN/xRFM、多保真与按观测成本选实验。LCA/经济分析只对接用户现有模块。</li></ol></section>
''' + cards + '''<section><h2>额外源码发现</h2><p>FABO/code/bayesian_optimization_loop_EI.py先在全部已观测样本选特征，再做内层五折；这不等于泄漏尚未揭示候选标签，但会使内层模型选择评估偏乐观。五折手工切片还忽略余数样本，少于五个观测会出现空折。接入时重写折内筛选、分组划分与小样本退化路径。</p><p>MODNet互信息/RR筛选需要目标数据，不能在全表筛选后再声称独立验证；其Materials Project预计算相关性也不适合作为石墨表征默认。PySR的feature_selection.py说明与实际RandomForest代码不同，应以执行源码为准。</p><p>AFL-agent为NIST许可；SISSO工作流为CC BY4.0，与SISSO++许可证分开。feature-rankings未找到根许可证，不直接复制进发行程序。模型权重另行确认版本、大小和许可。</p></section>
<section><h2>六篇本地论文</h2><ul>''' + pdfrows + '''</ul></section><section><h2>源码清单</h2><table><tr><th>项目</th><th>状态</th><th>提交号</th></tr>''' + rows + '''</table><p>LeoIV旧仓库404；已有lpapenme作者伴随实现。所有下载成功项目均保存FANGZHEN_UPSTREAM.json，可按commit重新获取。验证记录见同目录study_ledger.json。</p></section></html>'''
    (OUT / '论文源码与接入评估.html').write_text(text, encoding='utf-8')
    print(json.dumps({'sources_hash_verified': sum(c['status'] == 'hash_verified' for c in checks), 'papers': len(papers), 'pdf_pages': sum(p['pages'] for p in papers)}))

if __name__ == '__main__':
    main()

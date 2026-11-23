'use strict';

// One project owns the data, jobs, evaluations and actual experimental feedback.
const projectStages = [
 {id:'data', number:'01', title:'数据中心', note:'整理实验数据与模型输入', icon:'▦'},
 {id:'modeling', number:'02', title:'建模与仿真', note:'选择模型，运行计算', icon:'⌁'},
 {id:'validation', number:'03', title:'验证与评价', note:'对照实测，检查适用范围', icon:'◎'},
 {id:'feedback', number:'04', title:'实验反馈', note:'记录实测，更新下一轮', icon:'⟳'}
];
const projectPageGroups = {
 data:['editor','preprocess'],
 modeling:['pipeline','calc','jobs','ml','capacity','multichem','engineering'],
 validation:['papers','compare','analysis','sustainability'],
 feedback:['research','candidate']
};
function projectGroup(page, options={}) {
 if(page==='jobs'&&options.jobMode==='predict')return 'validation';
 if(page==='research'&&options.researchKind==='public')return 'validation';
 if(page==='research'&&options.researchKind==='chain')return 'modeling';
 return projectStages.find(s => s.id === page)?.id ||
  Object.keys(projectPageGroups).find(k => projectPageGroups[k].includes(page)) || page;
}
function projectJobs(workspace, jobs) { return jobs.filter(j => j.workspace === workspace.id); }
function hasEvaluation(job) {
 const r=job.result||{};
 return job.status==='completed' && (typeof r.holdout_pass==='boolean' ||
  (job.mode==='capacity_forecast' && r.metrics!=null) ||
  ['predict','eis_fit','split_conformal','ml_train','research_chain','public_ml_validation'].includes(job.mode) ||
  (job.mode==='engineering' && (r.tests || r.spectra_summary || r.metrics?.test_rmse_complex_ohm!==undefined)));
}
function projectFacts(workspace, jobs, experiments) {
 const scoped=projectJobs(workspace,jobs), tables=workspace.tables||{};
 const records=Object.values(tables).reduce((n,rows)=>n+rows.length,0);
 const sources=scoped.filter(j=>['experimental_curve','preprocess','parquet_preprocess','ocp_table','eis_import','capacity_forecast','multichem'].includes(j.mode));
 const pending=experiments.filter(r=>['pending','partial'].includes(r.status));
 return {jobs:scoped,records,sources,pending,experiments,
  active:scoped.filter(j=>['queued','running'].includes(j.status)),
  completed:scoped.filter(j=>j.status==='completed'),
  failed:scoped.filter(j=>['failed','interrupted'].includes(j.status)),
  evaluations:scoped.filter(hasEvaluation),
  measured:experiments.filter(r=>['completed','partial'].includes(r.status)),
  issues:workspace.issues||[]};
}
function currentProjectFacts() { return projectFacts(state.workspace,state.jobs,state.researchExperiments||[]); }
function jobTitle(job) {
 return job.result?.title || (job.mode==='multichem'?multichemTools[job.result?.kind]?.label:null) ||
  taskNames[job.mode] || modes[job.mode] || job.mode;
}
function jobEvidence(job) {
 if(job.result?.evidence_type)return evidenceLabel(job.result);
 if(job.mode==='capacity_forecast')return '容量曲线 / 统计预测';
 if(job.mode==='multichem')return '实验数据分析 / 来源见记录';
 if(job.mode.startsWith('ml_'))return '数据驱动模型 / 来源见记录';
 return evidenceLabel(job.result||{});
}
function projectNext(facts) {
 if(facts.active.length) return {page:'results',title:'查看正在运行的任务',note:`${facts.active.length} 个任务正在排队或计算，完成后可继续验证。`};
 if(facts.pending.length) return {page:'feedback',title:'回填本轮实验结果',note:`${facts.pending.length} 条实验等待完成或补齐目标，实测结果可用于下一轮建模。`};
 if(facts.issues.length) return {page:'data',title:'核查数据中的待处理项',note:`当前项目有 ${facts.issues.length} 项字段或关联问题，可从数据中心定位。`};
 if(!facts.records && !facts.sources.length && !facts.completed.length) return {page:'data',title:'建立这个项目的数据基础',note:'导入实验记录或测试曲线，也可以先用公开参数熟悉仿真流程。'};
 if(!facts.completed.length) return {page:'modeling',title:'选择适合研究问题的模型',note:'从已录入的数据准备参数，或使用数据驱动模型开展分析。'};
 if(!facts.evaluations.length) return {page:'validation',title:'为计算结果补充验证',note:'选择留出数据、实验对照或校准方法，记录模型的适用范围。'};
 return {page:'feedback',title:'把分析结果带入下一轮实验',note:'查看选点建议、安排实验并记录实际测量，持续更新项目。'};
}
function projectStatusCards(f) {
 return [
  ['数据记录',f.records,`${f.sources.length} 条数据导入与分析记录`],
  ['计算任务',f.jobs.length,`${f.completed.length} 已完成 · ${f.active.length} 进行中`],
  ['验证记录',f.evaluations.length,'已生成评估记录，结论需逐项查看'],
  ['实验反馈',f.measured.length,`${f.pending.length} 条待完成或补测`]
 ];
}
function projectJobRows(jobs, limit=6) {
 return jobs.slice(0,limit).map(j=>`<button class="project-job-row" data-project-job="${esc(j.id)}">
  <span class="task-symbol">${j.status==='completed'?'✓':j.status==='failed'?'!':'◷'}</span>
  <span class="task-description"><strong>${esc(jobTitle(j))}</strong><small>${esc(j.result?.cell_id||j.result?.filename||j.model||'项目数据')} · ${j.id.slice(0,8)}</small></span>
  <span class="tag ${esc(j.status)}">${esc(statuses[j.status]||j.status)}</span><span aria-hidden="true">↗</span></button>`).join('');
}
function bindProjectActions(root=$('main')) {
 root.querySelectorAll('[data-open]').forEach(b=>b.onclick=()=>openProjectModule(b.dataset.open,b.dataset));
 root.querySelectorAll('[data-project-job]').forEach(b=>b.onclick=()=>openProjectResult(b.dataset.projectJob));
}
async function openProjectModule(page, options={}) {
 if(options.sheet) state.sheet=options.sheet;
 if(options.mode) state.jobMode=options.mode;
 state.handoffParent=options.parent||null;
 if(options.action) state.engineeringAction=options.action;
 if(options.kind) state.researchKind=options.kind;
 await goto(page);
}
async function openProjectResult(id) {
 if(!scopedJobs().some(j=>j.id===id)) return;
 state.resultJobId=id;state.resultMode='';state.resultStatus='';state.resultSearch='';
 await goto('results');
}
function projectHome() {
 const f=currentProjectFacts(),next=projectNext(f);
 $('main').innerHTML=`<section class="project-hero"><div><div class="eyebrow">BATTERY RESEARCH WORKSPACE</div>
  <h2>${esc(state.workspace.name)}</h2><p>以同一个项目连接数据、模型、验证与下一轮实验。</p>
  <div class="hero-meta"><span>项目版本 v${state.workspace.revision}</span><span>${f.jobs.length} 个任务</span><span>${f.experiments.length} 条实验计划</span></div></div>
  <button class="secondary" id="rename">重命名项目</button></section>
  <div class="metrics project-metrics">${projectStatusCards(f).map(([label,value,note])=>`<div class="metric"><label>${label}</label><b>${value}</b><small>${note}</small></div>`).join('')}</div>
  <section class="prediction-shortcuts panel"><div><h2>预测分析</h2><p>预测结果保存在当前研究项目中。</p></div><button class="secondary" data-open="capacity">容量衰退预测 →</button><button class="secondary" data-open="ml">材料性能预测 →</button></section>
  <section class="next-action"><div class="next-icon">→</div><div><small>继续这个项目</small><h3>${next.title}</h3><p>${next.note}</p></div><button class="primary" data-open="${next.page}">继续 →</button></section>
  <section class="project-section"><div class="section-head"><h2>研究流程</h2><span class="subtle">每一步都归属于当前项目</span></div><div class="stage-cards">${projectStages.map((s,i)=>`<button class="stage-card" data-open="${s.id}"><span class="stage-number">${s.number}</span><h3>${s.title}</h3><p>${s.note}</p><span class="stage-count">${[`${f.records} 条数据记录`,`${f.completed.length} 个任务已完成`,`${f.evaluations.length} 份评估记录`,`${f.pending.length} 条待实验 / 补测`][i]} <b>→</b></span></button>`).join('')}</div></section>
  <div class="project-columns"><section class="panel"><div class="section-head"><h2>最近任务</h2><button class="quiet" data-open="results">全部任务 →</button></div>${f.jobs.length?projectJobRows(f.jobs,5):'<div class="empty"><strong>从第一个研究任务开始</strong>数据准备好后，在建模与仿真中选择计算方法。</div>'}</section>
  <section class="panel"><div class="section-head"><h2>项目数据</h2><button class="quiet" data-open="data">进入数据中心 →</button></div>${state.schema.tables.map(t=>`<button class="data-summary-row" data-open="editor" data-sheet="${esc(t.sheet)}"><span>${esc(t.sheet)}</span><b>${state.workspace.tables[t.sheet].length}</b><span>→</span></button>`).join('')}<div class="project-note">${f.issues.length?`${f.issues.length} 项数据问题待核查`:'数据、原始文件和计算结果保留各自的来源与版本。'}</div></section></div>`;
 bindProjectActions();
 $('rename').onclick=async()=>{const name=await requestDialog('项目名称',state.workspace.name);if(!name?.trim())return;state.workspace.name=name.trim();dirty();await save();await reloadList();render();};
}
function projectData() {
 const f=currentProjectFacts();
 $('main').innerHTML=`<div class="section-head"><div><h2>项目数据中心</h2><p class="subtle">实验记录、导入曲线和模型输入集中管理，计算任务引用各自的数据版本。</p></div><button class="primary" id="data-import">导入 Excel</button></div>
  <details class="panel project-data-tables" ${f.records?'open':''}><summary>材料、样品与模型输入表 <span>${f.records} 条记录</span></summary><p class="subtle">按研究对象填写需要的数据表，测试曲线与容量数据可在下方独立导入。</p><div class="project-data-grid">${state.schema.tables.map(t=>`<button class="data-table-card" data-open="editor" data-sheet="${esc(t.sheet)}"><span class="task-symbol">▦</span><h3>${esc(t.sheet)}</h3><b>${state.workspace.tables[t.sheet].length}<small> 条记录</small></b><p>${esc(t.note||'编辑项目数据')}</p><span>查看与编辑 →</span></button>`).join('')}</div></details>
  <section class="panel project-section"><div class="section-head"><h2>数据检查与整理</h2><span class="pill">${f.issues.length?f.issues.length+' 项待核查':'字段检查无待处理项'}</span></div>${f.issues.length?`<div class="data-issues">${f.issues.slice(0,8).map(r=>`<button data-open="editor" data-sheet="${esc(r.sheet)}"><b>${esc(r.sheet)} · 第${r.row}行</b><span>${esc(r.message)}</span><span>处理 →</span></button>`).join('')}</div>`:'<p class="subtle">当前已保存的数据没有字段检查问题。数据可用性还需结合实验协议与模型要求检查。</p>'}<div class="form-actions"><button class="secondary" data-open="preprocess">整理 CSV / Parquet 曲线</button><button class="secondary" data-open="pipeline">组装样品仿真参数</button><button class="secondary" data-open="capacity">导入逐循环容量数据</button></div></section>
  <section class="panel project-section"><div class="section-head"><h2>数据导入与分析记录</h2><span class="subtle">${f.sources.length} 条记录</span></div>${f.sources.length?projectJobRows(f.sources,100):'<div class="empty"><strong>还没有导入曲线</strong>可先整理测试 CSV、上传实验曲线，或导入容量数据。</div>'}</section>`;
 const imports=state.workspace.source?.imports||[];
 if(imports.length)$('main').insertAdjacentHTML('beforeend',`<section class="panel project-section"><h2>Excel 来源文件</h2>${imports.map(item=>`<div class="data-summary-row"><span>${esc(item.name)}</span><small>SHA256 ${esc(item.sha256.slice(0,12))}</small></div>`).join('')}<p class="subtle">原始文件与导入前的数据版本保留在项目内。</p></section>`);
 bindProjectActions();$('data-import').onclick=()=>$('file-input').click();
}
const researchModuleCards={
 modeling:[
  ['准备模型输入','把项目里的样品数据转换为可检查的模型参数。',[
   ['pipeline','样品参数组装','连接极片、表征、OCP 与物理参数'],['calc','参数计算与反推','计算质量、面载量、倍率与电流']]],
  ['物理模型与工程仿真','按研究对象选择模型，保留参数与运行记录。',[
   ['jobs','锂电物理仿真','SPM / SPMe / DFN 公开参数前向计算',{mode:'forward'}],['jobs','参数辨识','从公开数据回放与辨识开始',{mode:'identify'}],['jobs','钠电参考仿真','钠离子 DFN 参考模型',{mode:'sodium_dfn'}],['engineering','电芯与电池包','状态估计、充电控制与电池包仿真'],['jobs','仿真诊断与探索','诊断模型响应并探索候选参数',{mode:'battery_agent'}]]],
  ['数据驱动建模','从实验数据训练模型、预测性能或寿命。',[
   ['ml','材料性能预测','描述符建模、独立预测与工艺候选推荐'],['capacity','容量衰退预测','逐循环容量预测、预测区间及留出误差'],['multichem','锂钠实验分析','CV、SOH 与硬碳实验分析']]]
 ],
 validation:[
  ['实验对照与独立验证','对照条件、留出数据和评估结果分别保留。',[
   ['compare','样品性能对比','按同倍率与循环节点比较实测性能'],['jobs','冻结参数验证','引用本项目已完成的参数辨识任务',{mode:'predict'}],['research','公开数据方法验收','固定预算与分组留出对照',{kind:'public'}]]],
  ['诊断、校准与综合评价','检查模型误差、区间和多目标权衡。',[
   ['papers','EIS 与区间校准','阻抗谱诊断、RC 拟合与区间校准'],['analysis','多目标与工艺公差','比较性能权衡与工艺稳定性'],['sustainability','成本与碳足迹','统一清单边界、功能单位与来源']]]
 ]
};
function projectModuleHub(group) {
 $('main').innerHTML=researchModuleCards[group].map(([title,note,cards])=>`<section class="project-section module-section"><div class="section-head"><div><h2>${title}</h2><p class="subtle">${note}</p></div></div><div class="module-cards">${cards.map(([page,label,description,options={}])=>`<button class="module-card" data-open="${page}" ${Object.entries(options).map(([k,v])=>`data-${k}="${esc(v)}"`).join(' ')}><span class="module-mark">${group==='modeling'?'⌁':'◎'}</span><h3>${label}</h3><p>${description}</p><span class="module-enter">进入 →</span></button>`).join('')}</div></section>`).join('');
 if(group==='validation') {
  const jobs=currentProjectFacts().evaluations;
  $('main').insertAdjacentHTML('beforeend',`<section class="panel project-section"><div class="section-head"><h2>已有验证记录</h2><span class="subtle">评估记录的数量不代表验证通过</span></div>${jobs.length?projectJobRows(jobs,8):'<p class="subtle">完成验证任务后，可在这里查看误差、校准和留出结果。</p>'}</section>`);
 }
 bindProjectActions();
}
async function projectFeedback() {
 const parents=scopedJobs().filter(j=>j.mode==='research_multi'&&j.status==='completed');
 $('main').innerHTML=`<section class="feedback-intro"><div><div class="eyebrow">CLOSE THE RESEARCH LOOP</div><h2>让实际实验推进下一轮研究</h2><p>选点建议 → 待实验记录 → 实测反馈 → 更新模型。</p></div><button class="primary" data-open="research" data-kind="multi">创建选点与实验计划 →</button></section>
  <section class="panel project-section"><div class="section-head"><h2>实验计划与实测反馈</h2><button class="secondary" id="feedback-refresh">刷新记录</button></div><div id="research-experiments" aria-live="polite">正在读取实验记录…</div></section>
  <section class="panel project-section"><h2>使用实际反馈更新模型</h2><p class="subtle">引用原任务的候选表、目标和实验记录，生成新的任务，保留此前结果。</p><div class="feedback-controls"><label for="feedback-parent">本轮选点任务</label><select id="feedback-parent">${parents.map(j=>`<option value="${j.id}">${esc(jobTitle(j))} · ${j.id.slice(0,8)}</option>`).join('')||'<option value="">尚无已完成的多目标选点任务</option>'}</select><button class="primary" id="feedback-update" ${parents.length?'':'disabled'}>更新模型与下一轮选点</button></div><p><label><input type="checkbox" id="feedback-explore"> 校准不足时允许生成明确标记的探索建议</label></p><p class="subtle">${parents.length?'先保存上方实际测量，再选择对应的选点任务。':'先在多目标科研闭环中运行选点，并从结果生成待实验记录。'}</p></section>`;
 $('main').insertAdjacentHTML('beforeend','<div class="form-actions"><button class="secondary" data-open="candidate">从有限候选表直接选点 →</button></div>');
 bindProjectActions();$('feedback-refresh').onclick=researchExperiments;
 $('feedback-update').onclick=async()=>{const button=$('feedback-update');try{button.disabled=true;await save();const j=await api('job',{workspace:state.workspace.id,mode:'research_multi',feedback_parent:$('feedback-parent').value,allow_exploration:$('feedback-explore').checked});state.jobs.unshift(j);await openProjectResult(j.id);toast('已读取实际反馈，提交下一轮研究任务');}catch(e){toast(e.message);}finally{if(button.isConnected)button.disabled=false;}};
 await researchExperiments();
}
function jobOwnerPage(j) {
 if(j.mode.startsWith('ml_'))return 'ml';
 if(['research_multi','research_chain','public_ml_validation'].includes(j.mode))return 'research';
 if(['sustainability_inventory','everbatt_reference'].includes(j.mode))return 'sustainability';
 if(['preprocess','parquet_preprocess'].includes(j.mode))return 'preprocess';
 if(['eis_fit','eis_import','eis_forward','split_conformal'].includes(j.mode))return 'papers';
 if(j.mode==='engineering')return 'engineering';
 if(j.mode==='capacity_forecast')return 'capacity';
 if(j.mode==='multichem')return 'multichem';
 if(j.mode==='research_analysis')return 'pipeline';
 return 'jobs';
}
function resultNextActions(j) {
 if(j.status!=='completed')return [];
 if(j.mode==='identify')return [['jobs','用冻结参数做留出验证',{mode:'predict',parent:j.id}]];
 if(j.mode==='ml_train')return [['ml','使用保存模型预测新样品',{parent:j.id}]];
 if(j.mode==='eis_fit')return [['engineering','将 RC 参数带入状态估计',{action:'ecm_bms',parent:j.id}]];
 if(j.mode==='research_multi')return [['feedback','查看实验计划与反馈',{}]];
 if(j.mode==='engineering'&&j.result?.action==='commercial_adaptive')return [];
 return [['validation','开展验证与评价',{}]];
}
function projectResults() {
 const jobs=scopedJobs();
 $('main').innerHTML=`<div class="section-head"><div><h2>项目任务与结果</h2><p class="subtle">所有模块共用任务记录，在这里查看状态、来源与后续操作。</p></div><button class="primary" data-open="modeling">新建研究任务</button></div>
  <div class="result-filters"><label>搜索任务<input id="result-search" placeholder="任务名称 / 电芯 / 编号" value="${esc(state.resultSearch||'')}"></label><label>任务类别<select id="result-mode"><option value="">全部类别</option>${[...new Set(jobs.map(j=>j.mode))].map(mode=>`<option value="${esc(mode)}" ${state.resultMode===mode?'selected':''}>${esc(taskNames[mode]||modes[mode]||mode)}</option>`).join('')}</select></label><label>状态<select id="result-status"><option value="">全部状态</option>${Object.entries(statuses).map(([s,label])=>`<option value="${s}" ${state.resultStatus===s?'selected':''}>${label}</option>`).join('')}</select></label></div>
  <div class="project-results-layout"><section class="panel result-list"><div id="project-result-list"></div></section><section class="panel result-detail" id="project-result-detail" aria-live="polite"></section></div>`;
 bindProjectActions();
 const filter=()=>{state.resultSearch=$('result-search').value;state.resultMode=$('result-mode').value;state.resultStatus=$('result-status').value;refreshProjectResults();};
 $('result-search').oninput=filter;$('result-mode').onchange=filter;$('result-status').onchange=filter;
 refreshProjectResults();
}
function refreshProjectResults() {
 if(!$('project-result-list'))return;
 const query=(state.resultSearch||'').toLowerCase(),jobs=scopedJobs().filter(j=>(!state.resultMode||j.mode===state.resultMode)&&(!state.resultStatus||j.status===state.resultStatus)&&[jobTitle(j),j.id,j.model,j.result?.cell_id].join(' ').toLowerCase().includes(query));
 if(!jobs.some(j=>j.id===state.resultJobId))state.resultJobId=jobs[0]?.id||null;
 $('project-result-list').innerHTML=jobs.length?projectJobRows(jobs,1000):'<div class="empty"><strong>暂无匹配任务</strong>新建任务或调整筛选条件。</div>';
 $('project-result-list').querySelectorAll('[data-project-job]').forEach(b=>{b.classList.toggle('selected',b.dataset.projectJob===state.resultJobId);b.onclick=()=>{state.resultJobId=b.dataset.projectJob;refreshProjectResults();};});
 projectResultDetail(jobs.find(j=>j.id===state.resultJobId));
 rememberProjectLocation();
}
async function projectResultDetail(j) {
 const panel=$('project-result-detail');
 if(!j){panel.innerHTML='<div class="empty"><strong>选择一个任务查看结果</strong>计算结果、数据版本和后续操作会显示在这里。</div>';return;}
 const owner=jobOwnerPage(j);
 panel.innerHTML=`<div class="section-head"><div><small class="eyebrow">${j.id.slice(0,8)}</small><h2>${esc(jobTitle(j))}</h2></div><span class="tag ${esc(j.status)}">${esc(statuses[j.status]||j.status)}</span></div><div class="result-provenance"><span>${esc(state.workspace.name)}</span><span>数据版本 ${j.workspace_revision?'v'+j.workspace_revision:'未记录'}</span><span>${esc(jobEvidence(j))}</span></div>
  <div id="result-lineage" class="result-lineage">正在读取输入与来源…</div><div class="result-body" id="result-body"></div>
  <div class="result-actions"><button class="secondary" id="result-open-module">进入${esc(names[owner])}</button><button class="secondary" id="result-record">下载任务记录</button><button class="secondary" id="result-run-log">运行日志</button>${resultNextActions(j).map(([page,label,options])=>`<button class="primary" data-open="${page}" ${Object.entries(options).map(([k,v])=>`data-${k}="${esc(v)}"`).join(' ')}>${label} →</button>`).join('')}</div>`;
 bindProjectActions(panel);
 $('result-open-module').onclick=()=>{state.jobId=j.id;state.mlJob=j.id;state.researchJob=j.id;state.preprocessJob=j.id;state.sustainabilityJob=j.id;state.capacityJob=j.id;openProjectModule(owner);};
 $('result-record').onclick=()=>download(JSON.stringify(j,null,2),'任务_'+j.id.slice(0,8)+'.json','application/json');
 $('result-run-log').onclick=async()=>{try{const l=await api('joblog?id='+j.id);modal('运行日志',`<pre>${esc(l.text)}</pre>`);}catch(e){toast(e.message);}};
 const body=$('result-body');
 if(j.status!=='completed')body.innerHTML=`<div class="${j.error?'issues':'empty'}">${esc(j.error||'任务正在运行，结果会自动更新。')}</div>`;
 else try {
  if(j.mode.startsWith('ml_')){body.innerHTML='<div id="ml-result"></div>';mlResult(j);}
  else if(['research_multi','research_chain','public_ml_validation'].includes(j.mode)){body.innerHTML='<div id="research-result"></div><div id="research-experiments"></div>';researchResult(j);if(j.mode==='research_multi')researchExperiments();}
  else if(j.mode==='capacity_forecast'){body.innerHTML='<div id="cap-result">正在读取容量预测结果…</div>';const result=await api('download?id='+j.id+'&kind=capacity_json');if(body.isConnected&&state.resultJobId===j.id)capacityResult(j.id,result);}
  else if(['sustainability_inventory','everbatt_reference'].includes(j.mode)){body.innerHTML='<div id="s-result"></div>';sustainabilityDraft();sustainabilityResult(j);}
  else if(['preprocess','parquet_preprocess'].includes(j.mode)){body.innerHTML='<div id="pre-result"></div>';preprocessResult(j);}
  else if(['multichem','ocp_table','eis_import','split_conformal','research_analysis'].includes(j.mode)){body.innerHTML=`${j.curves?.length?lineChart(j.curves[0].points):''}<p>${esc(j.result?.scope||j.scope||'数据处理结果')}</p><details open><summary>结果明细</summary><pre class="result-json">${esc(JSON.stringify(j.result,null,2))}</pre></details>`;}
  else{body.innerHTML='<div id="job-result"></div>';state.jobId=j.id;jobResult();body.querySelector('#job-result>.section-head')?.remove();body.querySelector('#job-result>.source-badge')?.remove();}
 }catch(e){if(body.isConnected)body.innerHTML=`<div class="issues">结果图表暂时无法显示，可下载完整任务记录。${esc(e.message)}</div>`;}
 try{
  const context=await api('jobcontext?id='+j.id);
  if(!panel.isConnected||state.page!=='results'||state.resultJobId!==j.id)return;
  const line=$('result-lineage');
  line.innerHTML=`<span>输入快照 ${context.snapshot_available?'已保存':'未留存'}</span>${context.sources.map(s=>`<span>${esc(s.label)}${s.sha256?' · SHA256 '+esc(s.sha256.slice(0,12)):''}</span>`).join('')}${context.parents.map(p=>`<button data-project-job="${esc(p.id)}">来源任务 ${esc(taskNames[p.title]||modes[p.title]||p.title)} · ${p.id.slice(0,8)} ↗</button>`).join('')}`;
  bindProjectActions(line);
 }catch(e){if(panel.isConnected&&state.resultJobId===j.id)$('result-lineage').textContent='来源详情暂时不可用，已保存的任务记录仍可查看。';}
}
function rememberProjectLocation() {
 if(!state.workspace)return;
 const hash=new URLSearchParams(location.hash.slice(1));
 hash.set('project',state.workspace.id);hash.set('view',state.page);
 if(state.page==='results'&&state.resultJobId)hash.set('job',state.resultJobId);else hash.delete('job');
 window.history.replaceState(null,'','#'+hash.toString());
}
function renderProjectContext() {
 const group=projectGroup(state.page,state),stage=projectStages.find(s=>s.id===group);
 $('project-name').textContent=state.workspace?.name||'选择研究项目';
 $('project-version').textContent=state.workspace?'项目版本 v'+state.workspace.revision:'';
 $('project-context').hidden=!state.workspace;
 $('project-flow').innerHTML=projectStages.map(s=>`<button class="${group===s.id?'active':''}" data-open="${s.id}" ${group===s.id?'aria-current="step"':''}><span>${s.number}</span>${s.title}</button>`).join('<span class="flow-arrow" aria-hidden="true">→</span>');
 bindProjectActions($('project-flow'));
 $('module-context').hidden=!stage||state.page===group;
 if(stage&&state.page!==group){$('module-context').innerHTML=`<button data-open="${group}">← ${stage.title}</button><span>${esc(state.workspace.name)} / ${esc(names[state.page])}</span><button data-open="results">查看项目任务 →</button>`;bindProjectActions($('module-context'));}
 rememberProjectLocation();
}

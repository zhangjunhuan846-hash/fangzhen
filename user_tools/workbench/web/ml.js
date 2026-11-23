function mlConfig(){return {target:$('ml-target').value,purpose:$('ml-purpose').value,selector:$('ml-selector').value,top_k:Number($('ml-k').value),validation:$('ml-validation').value,noise_fraction:Number($('ml-noise').value),c_rate:Number($('ml-rate').value),cycle:Number($('ml-cycle').value),temperature_C:Number($('ml-temp').value),auto_calibrate:$('ml-auto-cal').checked,alpha:Number($('ml-alpha').value)};}
async function mlPage(){
 const workspace=state.workspace.id;state.mlPreview=null;state.mlRaw=null;state.mlConfig=null;
 $('main').innerHTML=`<section class="panel"><div class="section-head"><div><h2>描述符 → 性能 → 下一组实验</h2><p class="subtle">选择已有数据的列，比较模型；重复实验按工艺组验证。未测目标保持为空。</p></div><span class="pill">本地机器学习</span></div><div class="analysis-fields"><div class="field"><label>数据来源</label><select id="ml-source"><option value="workspace">当前项目：关联实验样品</option><option value="csv">自定义描述符CSV</option></select></div><div class="field"><label>建模用途</label><select id="ml-purpose"><option value="material">已制得材料的性能预测</option><option value="process">实验前工艺预测与推荐</option></select></div><div class="field"><label>预测目标</label><select id="ml-target"></select></div><div class="field"><label>验证方式</label><select id="ml-validation"><option value="group">按独立工艺组五折验证</option><option value="batch">留原料批次验证</option></select></div><div class="field"><label>描述符筛选</label><select id="ml-selector"><option value="manual">使用勾选列（去常数）</option><option value="spearman">训练折内相关性筛选</option><option value="mrmr">训练折内相关性＋冗余控制</option></select></div>${analysisInput('ml-k','筛选最多几列',5)}${analysisInput('ml-noise','GP相对噪声标准差',.05)}${analysisInput('ml-alpha','区间alpha（0.1为90%）',.1)}${analysisInput('ml-rate','半电池倍率 (C)',1)}${analysisInput('ml-cycle','循环节点',1)}${analysisInput('ml-temp','测试温度 (°C)',25)}</div><label><input id="ml-auto-cal" type="checkbox" checked> 自动预留独立工艺组校准预测区间（不足时显示无界）</label><div id="ml-upload" hidden><input id="ml-file" type="file" accept=".csv"><p class="subtle">CSV必须含record_id、group_id、batch_id和目标列；其他列可自由选择。group_id为独立工艺条件，不是电芯号。列名不要包含逗号。</p></div><div class="form-actions"><button id="ml-preview" class="secondary">① 读取数据与描述符</button><button id="ml-demo" class="secondary">下载合成建模示例</button></div><div id="ml-fields"></div><div class="form-actions"><button id="ml-train" class="primary" disabled>② 比较模型并保存</button></div><div class="detail-note">固定配置比较均值、岭回归、PLS、随机森林、Extra Trees、GP；中位数填补、编码与筛选仅用训练折。不同测试体系不会直接混合。至少5个独立工艺组；更少数据先做描述性分析。</div></section><section class="panel" style="margin-top:18px"><h3>保存模型 → 新样品预测 / 工艺候选</h3><div class="analysis-fields"><div class="field"><label>模型任务</label><select id="ml-parent"></select></div><div class="field"><label>执行方式</label><select id="ml-infer-mode"><option value="ml_predict">预测新样品</option><option value="ml_recommend">有限候选工艺选点（GP）</option></select></div><div class="field"><label>目标方向</label><select id="ml-direction"><option value="maximize">最大化</option><option value="minimize">最小化</option></select></div></div><input id="ml-predict-file" type="file" accept=".csv"><div class="form-actions"><button id="ml-template" class="secondary">下载当前模型预测表头</button><button id="ml-infer" class="primary">③ 运行预测 / 推荐</button></div><p class="subtle">预测CSV含record_id、batch_id与模型所有输入列，目标留空。表征模型只能预测已制得材料；工艺推荐须选实验前变量模型。未知类别、缺失、外推或已测组合不自动推荐。</p></section><section class="panel" style="margin-top:18px"><h3>建模与预测记录</h3><div id="ml-history"></div><div id="ml-result"></div></section>`;
 const formRoot=$('main').firstElementChild;mlSetupWorkflow(formRoot);
 try{const catalog=await api('mlcatalog');if(!formRoot.isConnected||state.workspace.id!==workspace)return;state.mlCatalog=catalog;$('ml-target').innerHTML=state.mlCatalog.targets.map(t=>`<option value="${esc(t.key)}">${esc(t.label)}</option>`).join('');}catch(e){if(formRoot.isConnected)formRoot.innerHTML=`<div class="issues">${esc(e.message)}</div>`;return;}
 $('ml-source').onchange=()=>{formRoot.mlPreviewRevision++;state.mlPreview=null;state.mlRaw=null;$('ml-fields').innerHTML='';$('ml-train').disabled=true;$('ml-upload').hidden=$('ml-source').value!=='csv';if($('ml-source').value==='workspace')$('ml-target').innerHTML=state.mlCatalog.targets.map(t=>`<option value="${esc(t.key)}">${esc(t.label)}</option>`).join('');};
 $('ml-file').onchange=()=>mlReadFile(formRoot,workspace);
 for(const id of ['ml-target','ml-purpose','ml-rate','ml-cycle','ml-temp'])$(id).onchange=()=>{formRoot.mlPreviewRevision++;state.mlPreview=null;$('ml-fields').innerHTML='';$('ml-train').disabled=true;};
 $('ml-preview').onclick=()=>mlPreviewData(formRoot,workspace);
 $('ml-train').onclick=()=>mlSubmitTask(formRoot,workspace,'train');
 $('ml-demo').onclick=()=>mlDemo();
 $('ml-infer').onclick=()=>mlSubmitTask(formRoot,workspace,'predict');
 $('ml-template').onclick=()=>{try{const parent=state.jobs.find(j=>j.id===$('ml-parent').value);if(!parent)throw Error('先选择完成的模型');mlDownloadText(['record_id','batch_id',...parent.result.features].join(',')+'\n','新样品预测表.csv');}catch(e){toast(e.message);}};
 formRoot.dataset.ready='1';$('ml-parent').onchange=mlModelStatus;mlHistory();
}
function mlSetupWorkflow(formRoot) {
 const panels=[...$('main').children];
 panels[0].id='ml-training-panel';panels[1].id='ml-prediction-panel';panels[2].id='ml-records-panel';
 formRoot.mlPreviewRevision=0;
 for(const panel of panels)for(const input of panel.querySelectorAll('input[id],select[id]')){
  const label=input.closest('.field')?.querySelector('label');if(label)label.htmlFor=input.id;
 }
 $('ml-file').setAttribute('aria-label','描述符训练 CSV');$('ml-predict-file').setAttribute('aria-label','新样品预测 CSV');
 const advanced=document.createElement('details');advanced.className='capacity-details';
 advanced.innerHTML='<summary>高级建模设置与实验协议</summary><div class="analysis-fields"></div>';
 const advancedFields=advanced.querySelector('div');
 for(const id of ['ml-selector','ml-k','ml-noise','ml-alpha','ml-rate','ml-cycle','ml-temp'])advancedFields.append($(id).closest('.field'));
 formRoot.querySelector('.analysis-fields').insertAdjacentElement('afterend',advanced);
 $('ml-preview').textContent='读取数据，选择描述符';$('ml-train').textContent='比较并保存性能模型';
 const inferMode=()=>{$('ml-direction').closest('.field').hidden=$('ml-infer-mode').value==='ml_predict';$('ml-infer').textContent=$('ml-infer-mode').value==='ml_predict'?'运行新样品预测':'运行候选工艺推荐';};
 $('ml-infer-mode').onchange=inferMode;inferMode();
 $('main').insertAdjacentHTML('afterbegin',`<div class="ml-workflow-intro"><div><h2>材料性能预测</h2><p>先保存性能模型，再用同一模型预测新样品或候选工艺。</p></div><div class="ml-workflow-tabs"><button id="ml-view-train">训练性能模型</button><button id="ml-view-predict">使用已有模型预测</button></div></div>`);
 $('ml-prediction-panel').insertAdjacentHTML('afterbegin','<div class="ml-model-readiness" id="ml-model-readiness" role="status"></div>');
 $('ml-upload').insertAdjacentHTML('beforeend','<span class="ml-source-file" id="ml-upload-name"></span>');
 state.mlWorkflowByProject??={};
 const models=state.jobs.filter(j=>j.workspace===state.workspace.id&&j.mode==='ml_train'&&j.status==='completed');
 const mode=state.handoffParent&&models.some(j=>j.id===state.handoffParent)?'predict':
  state.mlWorkflowByProject[state.workspace.id]||(models.length?'predict':'train');
 const select=selected=>{
  state.mlWorkflowByProject[state.workspace.id]=selected;
  $('ml-training-panel').hidden=selected!=='train';$('ml-prediction-panel').hidden=selected!=='predict';
  for(const key of ['train','predict']){$('ml-view-'+key).classList.toggle('active',selected===key);$('ml-view-'+key).setAttribute('aria-pressed',String(selected===key));}
 };
 $('ml-view-train').onclick=()=>select('train');$('ml-view-predict').onclick=()=>select('predict');
 select(mode);mlModelStatus();
}
function mlModelStatus() {
 const info=$('ml-model-readiness'),parent=$('ml-parent');if(!info||!parent)return;
 const model=state.jobs.find(j=>j.id===parent.value&&j.workspace===state.workspace.id&&j.mode==='ml_train'&&j.status==='completed');
 const models=state.jobs.filter(j=>j.workspace===state.workspace.id&&j.mode==='ml_train'&&j.status==='completed');
 const ready=$('ml-training-panel')?.dataset.ready==='1';
 parent.disabled=!models.length;$('ml-infer').disabled=!model||!ready;$('ml-template').disabled=!model||!ready;
 $('ml-view-predict').textContent='使用已有模型预测'+(models.length?' · '+models.length:'');
 info.innerHTML=model?`<strong>已选择 ${esc(model.result.selected_model||'已保存模型')} · ${model.id.slice(0,8)}</strong><br>目标 ${esc(model.result.target)} · ${(model.result.features||[]).length} 个输入描述符 · 训练数据版本 ${model.workspace_revision?'v'+model.workspace_revision:'旧记录未留存'}。预测将引用这个保存模型。`:models.length?
  `<strong>正在读取当前项目的 ${models.length} 个保存模型…</strong><br>模型就绪后可选择预测输入。`:
  '<strong>当前项目还没有可用的性能模型。</strong><br>先读取实验数据、选择描述符并保存模型，或切换到已有模型的研究项目。<br><button class="quiet" data-ml-to-train>读取数据并训练模型 →</button>';
 const trainLink=info.querySelector('[data-ml-to-train]');if(trainLink)trainLink.onclick=()=>$('ml-view-train').click();
}
async function mlReadFile(formRoot,workspace) {
 const file=$('ml-file').files[0];if(!file)return;
 const ticket=++formRoot.mlPreviewRevision;
 try{
  if(file.size>3_000_000)throw Error('CSV 最多 3MB。');
  const [text,raw]=await Promise.all([file.text(),base64File(file)]);
  if(!formRoot.isConnected||state.workspace.id!==workspace||ticket!==formRoot.mlPreviewRevision)return;
  const header=text.replace(/^\uFEFF/,'').split(/\r?\n/)[0].split(',').map(k=>k.trim().replace(/^"|"$/g,''));
  $('ml-target').innerHTML=header.filter(k=>!['record_id','group_id','batch_id'].includes(k)).map(k=>`<option value="${esc(k)}">${esc(k)}</option>`).join('');
  const common=header.find(k=>['target','capacity','ice','y'].includes(k));if(common)$('ml-target').value=common;
  state.mlRaw=raw;state.mlPreview=null;$('ml-fields').replaceChildren();$('ml-train').disabled=true;$('ml-upload-name').textContent='已读取：'+file.name;
 }catch(e){if(formRoot.isConnected)toast(e.message);}
}
async function mlPreviewData(formRoot,workspace) {
 if(!formRoot.isConnected||state.workspace.id!==workspace)return;
 const button=$('ml-preview'),ticket=++formRoot.mlPreviewRevision;
 try{
  const source=$('ml-source').value,raw=source==='csv'?state.mlRaw:undefined,config=mlConfig();
  if(source==='csv'&&!raw)throw Error('先选择描述符 CSV。');
  button.disabled=true;await save();
  if(!formRoot.isConnected||state.workspace.id!==workspace)return;
  const data=await api('mlpreview',{workspace,config,content:raw});
  if(!formRoot.isConnected||state.workspace.id!==workspace||ticket!==formRoot.mlPreviewRevision)return;
  state.mlConfig=config;state.mlPreview=data;mlFields(data);toast('已读取实验数据，选择输入描述符后可训练模型。');
 }catch(e){if(formRoot.isConnected)toast(e.message);}
 finally{if(button.isConnected)button.disabled=false;}
}
async function mlSubmitTask(formRoot,workspace,kind) {
 if(!formRoot.isConnected||state.workspace.id!==workspace)return;
 const button=$(kind==='train'?'ml-train':'ml-infer');if(button.disabled)return;
 const original=button.textContent;let payload;
 try{
  button.disabled=true;button.textContent=kind==='train'?'正在提交训练…':'正在提交预测…';
  if(kind==='train'){
   if(!state.mlPreview)throw Error('先读取数据。');
   const features=[...document.querySelectorAll('[data-ml-feature]:checked')].map(e=>e.dataset.mlFeature);
   if(!features.length)throw Error('至少选择一个输入描述符。');
   const roles=Object.fromEntries([...document.querySelectorAll('[data-ml-role]')].map(e=>[e.dataset.mlRole,e.value]));
   payload={workspace,mode:'ml_train',ml_config:{...mlConfig(),features,roles},content:$('ml-source').value==='csv'?state.mlRaw:undefined};
  }else{
   const parent=state.jobs.find(j=>j.id===$('ml-parent').value&&j.workspace===workspace&&j.mode==='ml_train'&&j.status==='completed');
   if(!parent)throw Error('先选择当前项目已完成的性能模型。');
   const file=$('ml-predict-file').files[0];if(!file)throw Error('请选择新样品预测 CSV。');
   if(file.size>3_000_000)throw Error('预测 CSV 最多 3MB。');
   const mode=$('ml-infer-mode').value,direction=$('ml-direction').value;
   payload={workspace,mode,parent:parent.id,content:await base64File(file),direction};
  }
  await save();if(!formRoot.isConnected||state.workspace.id!==workspace)return;
  const job=await api('job',payload);if(!state.jobs.some(j=>j.id===job.id))state.jobs.unshift(job);
  if(!formRoot.isConnected||state.workspace.id!==workspace)return;
  state.mlJob=job.id;await openProjectResult(job.id);toast(kind==='train'?'已提交模型训练，完成后可用于新样品预测。':'已引用保存模型提交预测，输入与来源保留在任务中。');
 }catch(e){if(formRoot.isConnected)toast(e.message);}
 finally{if(button.isConnected){button.disabled=false;button.textContent=original;mlModelStatus();}}
}

function mlFields(d){
 const groups=new Set(d.rows.map(r=>r.group_id));$('ml-fields').innerHTML=`<div class="metrics"><div class="metric"><small>有目标样品</small><strong>${d.rows.length}</strong></div><div class="metric"><small>独立工艺组</small><strong>${groups.size}</strong></div><div class="metric"><small>未测 / 不符合协议</small><strong>${d.exclusions.length}</strong></div></div><p>${esc(d.group_basis)}</p><div class="grid-wrap" style="max-height:420px"><table class="result-table"><thead><tr><th>选择</th><th>描述符</th><th>类型</th><th>有值样品</th><th>已知阶段</th></tr></thead><tbody>${d.fields.filter(f=>f.key!==d.target).map(f=>{const n=d.rows.filter(r=>r[f.key]!==null&&r[f.key]!==undefined&&r[f.key]!=='').length;const allowed=state.mlConfig.purpose!=='process'||f.stage==='process'||d.source==='user_csv';return `<tr><td><input type="checkbox" aria-label="选择描述符 ${esc(f.label)}" data-ml-feature="${esc(f.key)}" ${allowed&&n?'':'disabled'}></td><td>${esc(f.label)}<small class="subtle"> ${esc(f.key)}</small></td><td>${f.kind==='numeric'?'数值':'类别'}</td><td>${n}/${d.rows.length}</td><td>${d.source==='user_csv'?`<select aria-label="${esc(f.label)} 的已知阶段" data-ml-role="${esc(f.key)}"><option value="measured">制样后测得</option><option value="process">实验前已知</option></select>`:(f.stage==='process'?'实验前已知':'制样后测得')}</td></tr>`;}).join('')}</tbody></table></div><p class="subtle">自定义CSV的字段阶段由你声明；不能把未来BET、容量或XRD结果声明为新工艺推荐前已知。</p>`;$('ml-train').disabled=!d.rows.length||groups.size<5;
}
function mlHistory(){if(!$('ml-history'))return;const jobs=state.jobs.filter(j=>j.workspace===state.workspace.id&&j.mode?.startsWith('ml_'));const parent=$('ml-parent'),old=state.handoffParent||parent.value;parent.innerHTML=jobs.filter(j=>j.mode==='ml_train'&&j.status==='completed').map(j=>`<option value="${j.id}">${j.id.slice(0,8)} · ${esc(j.result.target)} · ${esc(j.result.selected_model)}</option>`).join('');if([...parent.options].some(o=>o.value===old)){parent.value=old;state.handoffParent=null;}$('ml-history').innerHTML=jobs.length?jobs.map(j=>`<button class="secondary" data-ml-job="${j.id}" style="margin:5px">${j.id.slice(0,8)} · ${esc(taskNames[j.mode])} · ${esc(statuses[j.status])}</button>`).join(''):'<p class="subtle">尚无建模记录。</p>';$('ml-history').querySelectorAll('[data-ml-job]').forEach(b=>b.onclick=()=>{state.mlJob=b.dataset.mlJob;mlResult(state.jobs.find(j=>j.id===state.mlJob));});const current=jobs.find(j=>j.id===state.mlJob);if(current)mlResult(current);mlModelStatus();}
function mlResult(job){const r=job.result;if(job.status!=='completed'){$('ml-result').innerHTML=`<p>${esc(statuses[job.status])} ${esc(job.error||'')}</p><button id="ml-log" class="secondary">查看运行日志</button>`;$('ml-log').onclick=async()=>{const log=await api('joblog?id='+job.id);modal('运行日志',`<pre style="white-space:pre-wrap">${esc(log.text)}</pre>`);};return;}
 if(job.mode==='ml_train'){
 const legacyWarning=r.metric_definition?'':'<p class="detail-note">旧任务使用旧误差口径；可重新训练以使用当前误差口径，原任务仍保留。</p>';const freq=r.comparisons.find(c=>c.model===r.selected_model)?.selection_frequency||{};
 const importance=r.features.map(key=>{const vals=r.importance.filter(v=>v.model===r.selected_model&&v.feature===key&&v.informative).map(v=>v.mae_increase);return {key,score:vals.length?vals.reduce((a,b)=>a+b,0)/vals.length:null,n:vals.length};}).sort((a,b)=>(b.score??-Infinity)-(a.score??-Infinity));
 $('ml-result').innerHTML=`${legacyWarning}<h3>模型比较：${esc(r.target)}</h3><p>${r.samples}个样品 · ${r.independent_groups}个工艺组 · ${r.folds}折 · 保存模型 ${esc(r.selected_model)}</p><div class="grid-wrap"><table class="result-table"><thead><tr><th>模型</th><th>状态</th><th>分组MAE</th><th>RMSE</th><th>偏差</th><th>R²</th></tr></thead><tbody>${r.comparisons.map(c=>`<tr><td>${esc(c.model)}${c.model===r.selected_model?' ★':''}</td><td>${c.status==='complete'?'完成':esc(c.failures.map(f=>f.reason).join(';'))}</td><td>${fmt(c.metrics?.mae)}</td><td>${fmt(c.metrics?.rmse)}</td><td>${fmt(c.metrics?.bias)}</td><td>${fmt(c.metrics?.r2)}</td></tr>`).join('')}</tbody></table></div>${mlParity(r.oof)}${r.calibration?`<p class="detail-note">独立组校准：${r.calibration.finite?`名义覆盖${fmt(r.calibration.nominal_coverage,true)}，残差阈值${fmt(r.calibration.residual_threshold)}，校准组${r.calibration.calibration_groups}`:esc(r.calibration.reason||"校准不足，区间无界")}；自适应采样/批次偏移不继承覆盖保证。</p>`:""}<h3>描述符贡献与入选频率</h3><table class="result-table"><thead><tr><th>描述符</th><th>训练折入选频率</th><th>留出置换MAE增加</th><th>有效诊断折</th></tr></thead><tbody>${importance.map(v=>`<tr><td>${esc(v.key)}</td><td>${fmt(freq[v.key]||0,true)}</td><td>${v.score===null?'留出样本不足':fmt(v.score)}</td><td>${v.n}</td></tr>`).join('')}</tbody></table><p class="detail-note">${esc(r.scope)}</p><div class="form-actions"><button data-ml-download="ml_oof" class="secondary">逐折独立预测CSV</button><button data-ml-download="ml_importance" class="secondary">描述符诊断CSV</button><button data-ml-download="ml_result" class="secondary">完整结果JSON</button></div>`;
 }else{$('ml-result').innerHTML=`<h3>${job.mode==='ml_recommend'?'有限候选推荐':'新样品预测'} · ${esc(r.target)}</h3><p>${r.selected?'建议验证：'+esc(r.selected.record_id):job.mode==='ml_recommend'?'没有满足已知范围条件的候选，未强行推荐。':''}</p><table class="result-table"><thead><tr><th>样品</th><th>预测值</th><th>GP潜在标准差</th><th>独立校准区间</th><th>范围检查</th></tr></thead><tbody>${r.predictions.map(p=>`<tr><td>${esc(p.record_id)}</td><td>${fmt(p.prediction)}</td><td>${fmt(p.gp_latent_std)}</td><td>${p.interval_lower!==null&&p.interval_lower!==undefined?`${fmt(p.interval_lower)}–${fmt(p.interval_upper)}`:"无界 / 未校准"}</td><td>${esc(p.alerts.join('；')||'训练范围内')}</td></tr>`).join('')}</tbody></table><p class="detail-note">${esc(r.scope)}</p><button data-ml-download="ml_predictions" class="secondary">下载预测CSV</button>`;}
 $('ml-result').querySelectorAll('[data-ml-download]').forEach(b=>b.onclick=()=>fileDownload('download?id='+job.id+'&kind='+b.dataset.mlDownload,b.dataset.mlDownload+(b.dataset.mlDownload==='ml_result'?'.json':'.csv')).catch(e=>toast(e.message)));
}
function mlParity(rows){if(!rows?.length)return '';const W=560,H=310,L=55,T=25,B=45,R=30,values=rows.flatMap(r=>[r.observed,r.predicted]);const lo=Math.min(...values),hi=Math.max(...values),x=v=>L+(v-lo)/(hi-lo||1)*(W-L-R),y=v=>H-B-(v-lo)/(hi-lo||1)*(H-T-B);return `<h3>逐折预测：实测 vs 预测</h3><svg class="chart" viewBox="0 0 ${W} ${H}" aria-label="逐折实测预测散点图"><line x1="${L}" y1="${H-B}" x2="${W-R}" y2="${T}" stroke="#acb5c5" stroke-dasharray="5 5"/>${rows.map(r=>`<circle cx="${x(r.observed)}" cy="${y(r.predicted)}" r="4" fill="#6862df"><title>${esc(r.record_id)}：实测${fmt(r.observed)} / 预测${fmt(r.predicted)}</title></circle>`).join('')}<text x="${L}" y="${H-15}">${fmt(lo)}</text><text x="${W-R-35}" y="${H-15}">${fmt(hi)}</text><text x="${W/2}" y="${H-2}">实测</text><text x="8" y="${H/2}">预测</text></svg>`;}
function mlDownloadText(text,name){return download('\uFEFF'+text,name,'text/csv;charset=utf-8');}
function mlDemo(){let text='record_id,group_id,batch_id,temperature_C,concentration,true_density_g_cm3,bet_m2_g,capacity\n';for(let i=0;i<24;i++){const t=500+20*i,c=1+(i%4)*.25;const density=2.1+.002*i,bet=10-.2*i;const y=250+.12*(t-500)-3*c+((i%3)-1)*2;text+=`demo${i},condition${i},A,${t},${c},${density},${bet},${y}\n`;}mlDownloadText(text,'合成描述符软件算例.csv');}

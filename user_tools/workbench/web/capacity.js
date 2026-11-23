'use strict';

function capacityChart(result) {
 const points = result.points;
 const width = 780, height = 292, left = 64, bottom = 248, top = 24, right = 750;
 const start = points[0][0], end = points[points.length - 1][0];
 let low = Infinity, high = -Infinity;
 for (const row of points) for (const value of [row[2], row[3], row[5], row[6]]) {
   if (Number.isFinite(value)) { low = Math.min(low, value); high = Math.max(high, value); }
 }
 const pad = Math.max((high - low) * .08, high * .005, .0001);
 low = Math.max(0, low - pad); high += pad;
 const x = cycle => left + (right - left) * (cycle - start) / (end - start || 1);
 const y = capacity => bottom - (bottom - top) * (capacity - low) / (high - low);
 const line = (rows, column, color, dash = '') => {
   if (!rows.length) return '';
   const coordinates = rows.map(p => x(p[0]).toFixed(2) + ',' + y(p[column]).toFixed(2)).join(' ');
   const [cx, cy] = coordinates.split(' ').pop().split(',');
   return '<polyline fill="none" stroke="' + color + '" stroke-width="2.4" stroke-dasharray="' + dash +
     '" points="' + coordinates + '"/><circle cx="' + cx + '" cy="' + cy + '" r="2.6" fill="' + color + '"/>';
 };
 const trained = points.filter(p => p[1] === 'train'), held = points.filter(p => p[1] === 'holdout');
 const predicted = points.filter(p => p[3] !== null);
 const bands = [];
 let segment = [];
 const drawSegment = () => {
   if (!segment.length) return;
   if (segment.length === 1) {
     const p = segment[0];
     bands.push('<line x1="' + x(p[0]) + '" x2="' + x(p[0]) + '" y1="' + y(p[5]) +
       '" y2="' + y(p[6]) + '" stroke="#b9691b" stroke-width="2"/>');
   } else {
     const edge = (rows, column) => rows.map(p => x(p[0]).toFixed(2) + ',' + y(p[column]).toFixed(2)).join(' ');
     const coordinates = edge(segment, 6) + ' ' + edge(segment.slice().reverse(), 5);
     bands.push('<polygon points="' + coordinates + '" fill="#edac63" fill-opacity=".42"/>');
   }
   segment = [];
 };
 for (const p of predicted) {
   const bounded = Number.isFinite(p[5]) && Number.isFinite(p[6]);
   if (!bounded || (segment.length && p[0] !== segment[segment.length - 1][0] + 1)) drawSegment();
   if (bounded) segment.push(p);
 }
 drawSegment();
 const ticks = [];
 for (let i = 0; i <= 4; i++) {
   const val = low + (high - low) * i / 4;
   ticks.push('<path d="M' + left + ' ' + y(val) + 'H' + right + '" stroke="#e3e5ed"/><text x="54" y="' +
      (y(val) + 4) + '" text-anchor="end">' + Number(val.toPrecision(4)) + '</text>');
 }
 for (const c of new Set(Array.from({length: 6}, (_, i) => Math.round(start + (end - start) * i / 5)))) {
   ticks.push('<text x="' + x(c) + '" y="267" text-anchor="middle">' + c + '</text>');
 }
 const boundary = x(result.observed_through ?? result.cutoff);
 const observed=points.filter(p=>p[2]!==null),observedEnd=observed[observed.length-1][0];
 const futureArea=result.future_cycles?`<rect x="${x(observedEnd)}" y="${top}" width="${right-x(observedEnd)}" height="${bottom-top}" fill="#f3f5fa"/><text x="${(x(observedEnd)+right)/2}" y="16" text-anchor="middle">未来外推</text>`:'';
 return '<div class="capacity-chart" tabindex="0" role="group" aria-label="容量预测交互图"><svg role="img" aria-label="' + (bands.length ? '放电容量实测值、预测值与预测区间' : '放电容量实测值和预测值') + '" viewBox="0 0 ' + width + ' ' + height +
   '" style="width:100%;font:12px system-ui;fill:#475569"><text x="8" y="15">容量 (Ah)</text>' +
   futureArea + ticks.join('') + (bands.length ? '<g data-interval-band>' + bands.join('') + '</g>' : '') +
   '<path d="M' + boundary + ' ' + top + 'V' + bottom + '" stroke="#748095" stroke-dasharray="4 4"/>' +
   line(trained, 2, '#5848a8') + line(held.length ? [trained[trained.length - 1], ...held] : [], 2, '#087d74') +
   line(predicted, 3, '#c35614', '6 3') + '<text x="400" y="288" text-anchor="middle">' +
   esc(result.source?.axis_label || '循环次数') + '</text><line data-cap-crosshair hidden x1="64" x2="64" y1="24" y2="248" stroke="#697c9b" stroke-dasharray="3 3"/></svg></div>';
}

function capacityIntervalSummary(r) {
 const v = r.interval;
 if (!v) return '';
 let text = '目标覆盖率 ' + v.level + '%。';
 if (v.holdout_bounded) {
   text += '在有上下限的 ' + v.holdout_bounded + ' 个留出实测点中，' + v.holdout_covered +
     ' 个落入区间，实测覆盖率 <strong>' + (v.empirical_coverage * 100).toFixed(1) +
     '%</strong>，平均区间宽度 ' + fmt(v.mean_width_Ah) + ' Ah。';
 } else if (r.holdout_points) {
   text += '留出实测点均缺少同跨度历史误差，无法评估覆盖率。';
 } else {
   text += '本次使用全部实测点训练，未来覆盖率需待测量后核对。';
 }
 if (r.future_cycles) text += '外推 ' + r.future_cycles + ' 个点中，' + v.future_bounded + ' 个有上下限。';
 const missing = r.holdout_points - v.holdout_bounded + r.future_cycles - v.future_bounded;
 if (missing) text += '有 ' + missing + ' 个预测点的历史样本不足，上下限留空。该水平下，每个预测跨度至少需要 ' +
   v.min_origins_per_lead + ' 个历史起点。';
 if (v.failed_fits) text += '有 ' + v.failed_fits + ' 个历史起点拟合失败。首个错误为 ' + esc(v.first_fit_error) + '。';
 return '<p>' + text + '</p>';
}

function capacitySplit(cell, cutoff, horizon) {
 const cycles=cell?.cycles||[],cut=Number(cutoff),extra=Number(horizon);
 const train=cycles.filter(c=>c<=cut).length,held=cycles.length-train;
 const valid=cycles.length>=3&&Number.isInteger(cut)&&cut>=cell.first&&cut<=cell.last&&
  Number.isInteger(extra)&&extra>=0&&extra<=5000&&train>=2&&(held>0||extra>0);
 return {train,held,future:Number.isInteger(extra)?extra:0,valid};
}
function capacityMetrics(result) {
 const m=result.metrics;
 return {mae:m?.mae_Ah??null,rmse:m?.rmse_Ah??null,baseline:m?.baseline_mae_Ah??null,
  improvement:m&&Number.isFinite(m.mae_Ah)&&Number.isFinite(m.baseline_mae_Ah)&&m.baseline_mae_Ah>0?100*(m.baseline_mae_Ah-m.mae_Ah)/m.baseline_mae_Ah:null};
}
function capacityNearest(points, target) {
 if(!points.length)return -1;
 let lo=0,hi=points.length;
 while(lo<hi){const mid=(lo+hi)>>1;if(points[mid][0]<target)lo=mid+1;else hi=mid;}
 if(!lo)return 0;if(lo===points.length)return points.length-1;
 return target-points[lo-1][0]<=points[lo][0]-target?lo-1:lo;
}
function capacityBindChart(panel, result) {
 const container=panel.querySelector('.capacity-chart'),svg=container?.querySelector('svg');
 if(!svg)return;
 const readout=panel.querySelector('[data-cap-readout]'),line=svg.querySelector('[data-cap-crosshair]');
 const points=result.points,first=points[0][0],last=points[points.length-1][0];let selected=-1;
 const show=index=>{
  if(index===selected)return;selected=index;
  const p=points[index],x=64+(750-64)*(p[0]-first)/Math.max(1,last-first);
  line.removeAttribute('hidden');line.setAttribute('x1',x);line.setAttribute('x2',x);
  const phase={train:'训练实测',holdout:'留出回测',future:'未来外推'}[p[1]];
  readout.textContent=`${result.source?.axis_label||'循环'} ${p[0]} · ${phase} · 实测 ${fmt(p[2])} Ah · 预测 ${fmt(p[3])} Ah`+
   (Number.isFinite(p[5])&&Number.isFinite(p[6])?` · 区间 ${fmt(p[5])}–${fmt(p[6])} Ah`:'');
 };
 svg.onpointermove=event=>{
  const rect=svg.getBoundingClientRect(),viewX=(event.clientX-rect.left)/rect.width*780;
  show(capacityNearest(points,first+(viewX-64)/(750-64)*(last-first)));
 };
 container.onkeydown=event=>{
  if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
  event.preventDefault();const start=selected<0?(event.key==='ArrowRight'?-1:points.length):selected;
  show(event.key==='Home'?0:event.key==='End'?points.length-1:
   Math.max(0,Math.min(points.length-1,start+(event.key==='ArrowRight'?1:-1))));
 };
}
function capacityResult(jobId, result) {
 const panel=$('cap-result');if(!panel)return;
 const r=result,m=capacityMetrics(r),ordinal=r.source?.axis_label==='循环观测序号',unit=ordinal?'个观测':'圈';
 const rows=r.points.filter(p=>p[1]!=='train'),future=rows.filter(p=>p[1]==='future');
 const job=state.jobs.find(j=>j.id===jobId),trainingEnd=r.observed_through??r.cutoff;
 const score=value=>value===null?'—':fmt(value*1000);
 const improvement=m.improvement===null?'—':Math.abs(m.improvement).toFixed(1)+'%';
 const metricCards=[['留出 MAE',score(m.mae),'mAh'],['留出 RMSE',score(m.rmse),'mAh'],
  ['末次容量基线 MAE',score(m.baseline),'mAh'],
  [m.improvement===null?'相对基线':m.improvement>=0?'误差较基线降低':'误差较基线增加',improvement,'同一留出区间']];
 panel.innerHTML=`<section class="panel capacity-result-panel"><div class="section-head"><div><span class="eyebrow">已保存的预测结果 · ${esc(jobId.slice(0,8))}</span><h2>${esc(r.cell_id)} · ${esc(r.algorithm_name)}</h2></div><span class="pill">${esc(job?.created_at?new Date(job.created_at).toLocaleString('zh-CN'):'历史记录')}</span></div>
  <div class="capacity-config-tags"><span>训练 ${r.train_points} 点 / 至 ${trainingEnd}</span><span>留出回测 ${r.holdout_points} 点</span><span>末次实测后外推 ${r.future_cycles} ${unit}</span>${r.interval?`<span>区间目标水平 ${r.interval.level}%</span>`:'<span>仅点预测</span>'}</div>
  <div class="capacity-scorecards">${metricCards.map(([label,value,suffix])=>`<div><small>${label}</small><strong>${value}</strong><span>${suffix}</span></div>`).join('')}</div>
  ${!r.metrics?'<p class="capacity-hint">本次使用全部观测训练，只有未来外推结果；留出误差尚无实测数据可计算。</p>':''}
  <div class="capacity-legend"><span style="color:#5848a8">━ 训练实测</span><span style="color:#087d74">━ 留出实测</span><span style="color:#c35614">┄ 容量预测</span>${r.interval?`<span>▧ ${r.interval.level}% 目标水平的历史误差带</span>`:''}</div>
  ${capacityChart(r)}
  <div class="capacity-readout" data-cap-readout aria-live="polite">移动指针查看逐点数值，也可聚焦图表后按左右方向键。</div>
  <div class="capacity-interpretation"><strong>${future.length?`末个外推点为第 ${future[future.length-1][0]} ${unit}，预测 ${fmt(future[future.length-1][3])} Ah。`:'本次结果用于与已留出的实测容量进行回测对照。'}</strong><p>${r.metrics?(m.improvement===null?'基线误差为零，不计算相对误差降幅。':m.improvement>=0?'当前模型在本段留出数据上的 MAE 小于或等于末次容量基线。':'当前模型在本段留出数据上的 MAE 高于末次容量基线，可调整训练范围或模型后重新回测。'):'后续取得实测数据后，才能核对这次外推的误差。'}</p></div>
  ${r.interval?`<details class="capacity-details"><summary>区间与历史支持</summary>${capacityIntervalSummary(r)}<p class="subtle">误差带只使用训练期的滚动回测误差，按预测跨度分别计算。目标水平不等于未来一定达到的覆盖率。</p></details>`:''}
  <details class="capacity-details"><summary>逐点预测结果（${rows.length} 个点）</summary><div class="grid-wrap"><table class="result-table"><thead><tr><th>${ordinal?'观测序号':'循环'}</th><th>阶段</th><th>实测 Ah</th><th>预测 Ah</th><th>绝对误差 Ah</th><th>区间 Ah</th></tr></thead><tbody>${rows.slice(0,200).map(p=>`<tr><td>${p[0]}</td><td>${p[1]==='future'?'未来外推':'留出回测'}</td><td>${fmt(p[2])}</td><td>${fmt(p[3])}</td><td>${Number.isFinite(p[2])?fmt(Math.abs(p[3]-p[2])):'—'}</td><td>${Number.isFinite(p[5])&&Number.isFinite(p[6])?`${fmt(p[5])}–${fmt(p[6])}`:'未计算 / 历史支持不足'}</td></tr>`).join('')}</tbody></table></div>${rows.length>200?'<p class="subtle">页面展示前 200 个点，完整结果可下载 CSV。</p>':''}</details>
  <details class="capacity-details"><summary>输入来源与运行配置</summary><dl class="capacity-provenance"><dt>数据来源</dt><dd>${esc(r.source?.title||'未记录')}</dd><dt>算法版本</dt><dd>${esc(r.algorithm_version||'未记录')}</dd><dt>截止设置 / 实际末个训练观测</dt><dd>${r.cutoff} / ${trainingEnd}</dd><dt>输入 SHA256</dt><dd>${esc(r.input_sha256||'旧记录未留存')}</dd>${r.source?.parent_job?`<dt>复用的数据来源任务</dt><dd>${esc(r.source.parent_job)}</dd>`:''}</dl></details>
  <div class="form-actions capacity-result-actions"><button class="primary" data-cap-reuse>复用数据与配置，再做预测</button><button class="secondary" data-kind="capacity_csv">下载预测 CSV</button><button class="secondary" data-kind="capacity_input">下载输入 CSV</button><button class="secondary" data-kind="capacity_json">下载运行记录</button><button class="quiet" data-cap-all>查看项目全部结果 →</button></div></section>`;
 panel.querySelectorAll('[data-kind]').forEach(button=>button.onclick=()=>fileDownload('download?id='+jobId+'&kind='+button.dataset.kind,
  button.dataset.kind+'_'+jobId.slice(0,8)+(button.dataset.kind==='capacity_json'?'.json':'.csv')).catch(e=>toast(e.message)));
 panel.querySelector('[data-cap-reuse]').onclick=()=>{
  const view=state.capacityView;
  if(view?.workspace===state.workspace.id&&view.form.isConnected)view.reuse(jobId,r);
  else{state.capacityReuseJob=jobId;state.capacityJob=jobId;goto('capacity');}
 };
 panel.querySelector('[data-cap-all]').onclick=()=>openProjectResult(jobId);
 capacityBindChart(panel,r);
}
const capacityMethods={
 linear:'用训练期容量与循环编号拟合直线。',
 sqrt:'用循环编号的平方根拟合容量变化趋势。',
 last:'保持末个训练观测的容量，用作朴素基线。',
 'numpy-polynomial':'用训练期数据拟合二次曲线；可通过留出回测检查曲率外推的误差。'
};
async function capacityPage() {
 const main=$('main'),workspace=state.workspace.id;
 main.innerHTML='<div class="capacity-intro"><div><h2>容量衰退预测</h2><p>选择数据、划分训练与留出区间，再查看预测及误差。</p></div><button class="secondary" id="cap-material">材料性能预测 →</button></div><div class="capacity-workbench"><div class="capacity-input-column"><section class="panel" id="cap-form">正在读取数据目录…</section><section class="panel capacity-history-panel"><div class="section-head"><h3>项目预测记录</h3><span id="cap-history-count" class="pill"></span></div><div id="cap-history"></div></section></div><div id="cap-result" aria-live="polite"></div></div><details class="panel capacity-directory"><summary>公开数据来源与本机下载状态</summary><div id="cap-source-directory"></div><p id="cap-directory" class="subtle"></p></details>';
 $('cap-material').onclick=()=>goto('ml');
 const form=$('cap-form'),isCurrent=()=>form.isConnected&&state.workspace.id===workspace;
 let busy=false,loadRevision=0,selection=null,sourceInput=null;
 const previousJobs=()=>state.jobs.filter(j=>j.workspace===workspace&&j.mode==='capacity_forecast'&&j.status==='completed');
 const option=(value,label)=>`<option value="${esc(value)}">${esc(label)}</option>`;
 const draftKey='capacityDrafts';state[draftKey]??={};const draft=state[draftKey][workspace]??={};
 try{
  const catalog=await api('capacity_catalog');if(!isCurrent())return;
  const initialJob=previousJobs().find(j=>j.id===(state.capacityReuseJob||state.capacityJob))||previousJobs()[0];
  form.innerHTML=`<div class="section-head"><h3>新建预测任务</h3><span class="pill">配置区</span></div><p class="subtle">右侧结果保留它自己的已保存配置。</p><fieldset id="cap-controls"><div class="field"><label for="cap-kind">1 · 数据来源</label><select id="cap-kind">${option('public','已接入的公开数据')}${option('upload','导入自己的容量 CSV')}${option('saved','复用本项目已保存的数据')}</select></div>
   <div id="cap-public"><label for="cap-dataset">逐循环数据</label><select id="cap-dataset">${catalog.datasets.map(d=>option(d.id,d.title)).join('')}</select></div>
   <div id="cap-upload" hidden><label for="cap-file">容量 CSV 文件</label><input type="file" id="cap-file" accept=".csv"><small id="cap-upload-name" class="subtle"></small><button class="quiet" id="cap-template" type="button">下载空白 CSV 模板</button><p class="subtle">cell_id、cycle、capacity_Ah；容量单位 Ah。</p></div>
   <div id="cap-saved" hidden><label for="cap-source-job">已保存的数据来源任务</label><select id="cap-source-job"></select></div>
   <p id="cap-hint" class="capacity-hint" role="status"></p><div id="cap-data-summary" class="capacity-data-summary"></div>
   <div class="field"><label for="cap-cell">2 · 电芯 / 轨迹</label><select id="cap-cell"></select></div>
   <div class="field"><label for="cap-algo">预测算法</label><select id="cap-algo">${catalog.algorithms.map(a=>option(a.id,a.title)).join('')}</select><p class="subtle" id="cap-method"></p></div>
   <div class="capacity-presets"><button type="button" class="secondary" id="cap-backtest">留出数据做回测</button><button type="button" class="secondary" id="cap-extrapolate">全部训练后外推</button></div>
   <div class="capacity-setting-grid"><div class="field"><label for="cap-cut" id="cap-cut-label">训练截止循环</label><input type="number" id="cap-cut" step="1"></div><div class="field"><label for="cap-horizon" id="cap-horizon-label">末次实测后外推圈数</label><input type="number" id="cap-horizon" min="0" max="5000" step="1" value="10"></div></div>
   <div class="field"><label for="cap-interval">预测误差带</label><select id="cap-interval"><option value="">仅点预测</option><option value="80">80% 目标水平</option><option value="90" selected>90% 目标水平</option><option value="95">95% 目标水平</option></select></div>
   <div id="cap-split" class="capacity-split"></div></fieldset><p id="cap-error" class="issues" role="alert" hidden></p><button id="cap-run" class="primary capacity-run" disabled>运行预测并保存结果</button><details class="capacity-details"><summary>数据来源与提取规则</summary><p id="cap-source-note" class="subtle"></p></details>`;
  const history=$('cap-history');let resultRequest=0;
  const refreshHistory=()=>{
   const jobs=previousJobs();$('cap-history-count').textContent=jobs.length;
   history.innerHTML=jobs.length?jobs.slice(0,40).map(j=>`<button class="capacity-history-item ${state.capacityJob===j.id?'active':''}" data-cap-job="${j.id}"><strong>${esc(j.result.cell_id)}</strong><span>${esc(j.result.algorithm_name)} · 截止 ${j.result.cutoff}</span><small>${j.id.slice(0,8)}${j.created_at?' · '+esc(new Date(j.created_at).toLocaleString('zh-CN')):''}</small></button>`).join(''):'<p class="subtle">本项目尚无容量预测，完成后会在这里保留记录。</p>';
   history.querySelectorAll('[data-cap-job]').forEach(button=>button.onclick=()=>showJob(button.dataset.capJob));
   const old=$('cap-source-job').value;
   $('cap-source-job').innerHTML=jobs.map(j=>option(j.id,`${j.result.cell_id} · ${j.result.algorithm_name} · ${j.id.slice(0,8)}`)).join('');
   if(jobs.some(j=>j.id===old))$('cap-source-job').value=old;
   $('cap-kind').querySelector('[value="saved"]').disabled=!jobs.length;
   $('cap-kind').querySelector('[value="public"]').disabled=!catalog.datasets.length;
  };
  const showJob=async id=>{
   const request=++resultRequest;
   try{const result=await api('download?id='+id+'&kind=capacity_json');if(!isCurrent()||request!==resultRequest)return;
    state.capacityJob=id;capacityResult(id,result);refreshHistory();
   }catch(e){if(isCurrent()&&request===resultRequest){$('cap-result').innerHTML=`<section class="panel"><div class="issues">${esc(e.message)}</div></section>`;}}
  };
  const remember=()=>{
   Object.assign(draft,{kind:$('cap-kind').value,dataset:$('cap-dataset').value,sourceJob:$('cap-source-job').value,
    cell:$('cap-cell').value,algorithm:$('cap-algo').value,cutoff:$('cap-cut').value,horizon:$('cap-horizon').value,interval:$('cap-interval').value});
  };
  const updateSplit=()=>{
   const split=capacitySplit(selection,$('cap-cut').value,$('cap-horizon').value);
   $('cap-split').innerHTML=`<span><b>${split.train}</b> 训练观测</span><span><b>${split.held}</b> 留出回测</span><span><b>${split.future}</b> 额外外推</span>`;
   $('cap-run').disabled=busy||!sourceInput||!split.valid;
   $('cap-error').hidden=split.valid||!selection;
   if(selection&&!split.valid)$('cap-error').textContent='至少需要 3 个观测、2 个训练点，并留出实测点或设置额外外推。截止编号与外推数需为有效整数。';
   remember();
  };
  const applyCell=(values={})=>{
   selection=(form.capacityCells||[]).find(c=>c.id===$('cap-cell').value)||null;
   if(!selection){$('cap-run').disabled=true;return;}
   $('cap-cut').min=selection.cycles[1]??selection.first;$('cap-cut').max=selection.last;
   $('cap-cut').value=values.cutoff??selection.default_cutoff;
   if(values.horizon!==undefined)$('cap-horizon').value=values.horizon;
   const issues=[selection.nonconsecutive_intervals?'观测编号含非连续间隔，保留原始编号。':'',selection.zero_capacity_count?`${selection.zero_capacity_count} 条零容量观测，请核对测量含义。`:''].filter(Boolean);
   $('cap-data-summary').innerHTML=`<span><b>${selection.observations}</b> 个容量观测</span><span>编号 ${selection.first}–${selection.last}</span><span>首 / 末容量 ${fmt(selection.first_capacity_Ah)} / ${fmt(selection.last_capacity_Ah)} Ah</span>${issues.length?`<small>${esc(issues.join(' '))}</small>`:''}`;
   $('cap-hint').textContent='数据已读取；模型只使用训练截止位置及之前的观测。';updateSplit();
  };
  const loadSource=async (values={})=>{
   const request=++loadRevision,kind=$('cap-kind').value;
   sourceInput=null;selection=null;$('cap-run').disabled=true;$('cap-cell').replaceChildren();$('cap-data-summary').replaceChildren();$('cap-error').hidden=true;
   for(const key of ['public','upload','saved'])$('cap-'+key).hidden=kind!==key;
   const dataset=catalog.datasets.find(d=>d.id===$('cap-dataset').value);
   $('cap-source-note').textContent=kind==='public'?(dataset?.method||dataset?.title||'请选择数据集'):kind==='saved'?'复用原任务保留的输入 CSV，并核对原始文件校验值。':'使用原始 CSV，列为 cell_id、cycle、capacity_Ah；每个电芯同一编号只能有一条记录。';
   const ordinal=kind==='public'&&dataset?.axis_label==='循环观测序号';
   $('cap-cut-label').textContent=ordinal?'训练截止观测序号':'训练截止循环';$('cap-horizon-label').textContent=ordinal?'额外外推观测数':'末次实测后外推圈数';
   let input;
   if(kind==='public'&&dataset)input={dataset:dataset.id};
   if(kind==='saved'&&$('cap-source-job').value)input={source_job:$('cap-source-job').value,workspace};
   if(kind==='upload'&&draft.uploadContent)input={content:draft.uploadContent,filename:draft.uploadName};
   $('cap-upload-name').textContent=draft.uploadContent?'已读取文件：'+draft.uploadName:'';
   if(!input){$('cap-hint').textContent=kind==='upload'?'请选择自己的 UTF-8 容量 CSV。':'当前来源还没有可用的数据。';return;}
   $('cap-hint').textContent='正在读取并检查容量数据…';
   try{const cells=await api('capacity_cells',input);if(!isCurrent()||request!==loadRevision)return;
    form.capacityCells=cells;sourceInput=input;$('cap-cell').innerHTML=cells.map(c=>option(c.id,c.id)).join('');
    const isOrdinal=cells[0]?.axis_label==='循环观测序号';$('cap-cut-label').textContent=isOrdinal?'训练截止观测序号':'训练截止循环';$('cap-horizon-label').textContent=isOrdinal?'额外外推观测数':'末次实测后外推圈数';
    if(cells.some(c=>c.id===values.cell))$('cap-cell').value=values.cell;
    applyCell(values);
   }catch(e){if(isCurrent()&&request===loadRevision){$('cap-hint').textContent='数据读取失败';$('cap-error').hidden=false;$('cap-error').textContent=e.message;}}
  };
  const reuse=async (id,result)=>{
   if(!isCurrent())return;
   $('cap-kind').value='saved';$('cap-source-job').value=id;
   $('cap-algo').value=result.algorithm;$('cap-interval').value=result.interval?.level?String(result.interval.level):'';
   await loadSource({cell:result.cell_id,cutoff:result.cutoff,horizon:result.future_cycles});
   if(isCurrent()){form.scrollIntoView({block:'start'});toast('已复用这份原始数据与配置，可修改后生成新任务。');}
  };
  state.capacityView={workspace,form,reuse};
  $('cap-kind').onchange=()=>loadSource();$('cap-dataset').onchange=()=>loadSource();$('cap-source-job').onchange=()=>loadSource();
  $('cap-file').onchange=async event=>{const file=event.target.files[0];if(!file)return;
   const request=++loadRevision;
   try{if(file.size>20_000_000)throw Error('容量 CSV 超过 20MB。');const content=await base64File(file);if(!isCurrent()||request!==loadRevision)return;
    draft.uploadName=file.name;draft.uploadContent=content;await loadSource();
   }catch(e){if(isCurrent()){$('cap-error').hidden=false;$('cap-error').textContent=e.message;}}
  };
  $('cap-cell').onchange=()=>applyCell();$('cap-cut').oninput=updateSplit;$('cap-horizon').oninput=updateSplit;$('cap-interval').onchange=remember;
  $('cap-algo').onchange=()=>{$('cap-method').textContent=capacityMethods[$('cap-algo').value]||'使用本机安装的预测器，算法与版本随任务保存。';remember();};
  $('cap-template').onclick=()=>download('\uFEFFcell_id,cycle,capacity_Ah\n','容量数据模板.csv','text/csv;charset=utf-8');
  $('cap-backtest').onclick=()=>{if(selection){$('cap-cut').value=selection.default_cutoff;$('cap-horizon').value=0;updateSplit();}};
  $('cap-extrapolate').onclick=()=>{if(selection){$('cap-cut').value=selection.last;$('cap-horizon').value=10;updateSplit();}};
  $('cap-run').onclick=async()=>{
   if(busy||!sourceInput)return;
   const payload={...sourceInput,workspace,cell:$('cap-cell').value,algorithm:$('cap-algo').value,
    cutoff:$('cap-cut').value,horizon:$('cap-horizon').value,interval_level:$('cap-interval').value||null};
   const ticket=++resultRequest;
   busy=true;$('cap-controls').disabled=true;$('cap-run').disabled=true;$('cap-run').textContent='正在预测并保存…';$('cap-error').hidden=true;
   try{await save();const {job,result}=await api('capacity_forecast',payload);
    if(!state.jobs.some(j=>j.id===job.id))state.jobs.unshift(job);
    if(!isCurrent())return;
    if(ticket===resultRequest){state.capacityJob=job.id;capacityResult(job.id,result);}refreshHistory();toast('预测结果已保存为新任务，原记录保留。');
   }catch(e){if(isCurrent()){$('cap-error').hidden=false;$('cap-error').textContent=e.message;}}
   finally{busy=false;if(isCurrent()){$('cap-controls').disabled=false;$('cap-run').textContent='运行预测并保存结果';updateSplit();}}
  };
  const status={complete:'已校验',running:'下载中',paused:'已暂停',pending:'待下载',partial:'部分取得',unavailable:'暂不可得'};
  $('cap-source-directory').innerHTML=`<div class="grid-wrap"><table class="result-table"><thead><tr><th>数据来源</th><th>实验类型</th><th>本机状态</th></tr></thead><tbody>${catalog.sources.map(s=>`<tr><td>${/^https?:\/\//.test(s.url)?`<a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title)}</a>`:esc(s.title)}</td><td>${esc(s.kind)}</td><td>${esc(status[s.status]||s.status)}${s.total?' · '+s.files+'/'+s.total:''}</td></tr>`).join('')}</tbody></table></div>`;
  refreshHistory();
  $('cap-kind').value=draft.kind||(initialJob?'saved':catalog.datasets.length?'public':'upload');
  if(catalog.datasets.some(d=>d.id===draft.dataset))$('cap-dataset').value=draft.dataset;
  if(previousJobs().some(j=>j.id===draft.sourceJob))$('cap-source-job').value=draft.sourceJob;
  if(catalog.algorithms.some(a=>a.id===draft.algorithm))$('cap-algo').value=draft.algorithm;
  if(draft.horizon!==undefined)$('cap-horizon').value=draft.horizon;
  if(draft.interval!==undefined)$('cap-interval').value=draft.interval;
  if(initialJob){
   const saved=await api('download?id='+initialJob.id+'&kind=capacity_json');if(!isCurrent())return;
   state.capacityJob=initialJob.id;capacityResult(initialJob.id,saved);refreshHistory();
   if(state.capacityReuseJob===initialJob.id||!draft.kind){$('cap-kind').value='saved';$('cap-source-job').value=initialJob.id;$('cap-algo').value=saved.algorithm;$('cap-interval').value=saved.interval?.level?String(saved.interval.level):'';
    await loadSource({cell:saved.cell_id,cutoff:saved.cutoff,horizon:saved.future_cycles});state.capacityReuseJob=null;
   }else await loadSource({cell:draft.cell,cutoff:draft.cutoff,horizon:draft.horizon});
  }else{
   $('cap-result').innerHTML='<section class="panel capacity-empty"><span>∿</span><h2>预测与回测结果</h2><p>左侧读取数据并运行预测。这里会展示预测曲线、与实测的误差和原始输入来源。</p><p class="subtle">已有任务可从左侧项目预测记录重新打开。</p></section>';
   await loadSource({cell:draft.cell,cutoff:draft.cutoff,horizon:draft.horizon});
  }
  if(isCurrent())$('cap-algo').onchange();
 }catch(e){if(isCurrent())form.innerHTML=`<div class="issues">${esc(e.message)}</div>`;}
}

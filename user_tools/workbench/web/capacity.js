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
 const x = cycle => left + (right - left) * (cycle - start) / (end - start);
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
 const boundary = x(result.cutoff);
 return '<svg role="img" aria-label="' + (bands.length ? '放电容量实测值、预测值与预测区间' : '放电容量实测值和预测值') + '" viewBox="0 0 ' + width + ' ' + height +
   '" style="width:100%;font:12px system-ui;fill:#475569"><text x="8" y="15">容量 (Ah)</text>' +
   ticks.join('') + (bands.length ? '<g data-interval-band>' + bands.join('') + '</g>' : '') +
   '<path d="M' + boundary + ' ' + top + 'V' + bottom + '" stroke="#748095" stroke-dasharray="4 4"/>' +
   line(trained, 2, '#5848a8') + line(held.length ? [trained[trained.length - 1], ...held] : [], 2, '#087d74') +
   line(predicted, 3, '#c35614', '6 3') + '<text x="400" y="288" text-anchor="middle">' +
   esc(result.source?.axis_label || '循环次数') + '</text></svg>';
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

function capacityResult(job, r) {
 const panel = $('cap-result');
 if (!panel) return;
 const m = r.metrics;
 const ordinal = r.source?.axis_label === '循环观测序号';
 const unit = ordinal ? '个观测' : '圈';
 const intervalLegend = r.interval && (r.interval.holdout_bounded || r.interval.future_bounded)
   ? '　<span><i style="display:inline-block;width:1em;height:.7em;background:#f5cc9c"></i> ' + r.interval.level + '% 预测区间</span>' : '';
 panel.innerHTML = '<section class="panel"><h3>' + esc(r.cell_id) + ' · ' + esc(r.algorithm_name) +
   '</h3><p>训练 ' + r.train_points + ' 个观测，截止第 ' + r.cutoff + ' ' + unit + '。留出 ' + r.holdout_points +
   ' 个实测点，末次记录后外推 ' + r.future_cycles + ' ' + unit + '。</p>' +
   '<p><span style="color:#5848a8">━ 训练实测</span>　<span style="color:#087d74">━ 留出实测</span>　<span style="color:#c35614">┄ 容量预测</span>' + intervalLegend + '</p>' +
   capacityChart(r) + capacityIntervalSummary(r) + '<p>' + (m ? '留出 MAE <strong>' + fmt(m.mae_Ah) + ' Ah</strong>　RMSE ' +
    fmt(m.rmse_Ah) + ' Ah　末次容量基线 MAE ' + fmt(m.baseline_mae_Ah) + ' Ah' : '全部观测用于训练，本次只有外推曲线。') +
   '</p><div class="form-actions"><button class="secondary" data-kind="capacity_csv">下载预测 CSV</button>' +
   '<button class="secondary" data-kind="capacity_input">下载输入 CSV</button><button class="secondary" data-kind="capacity_json">下载运行记录</button></div></section>';
 panel.querySelectorAll('[data-kind]').forEach(b => b.onclick = () =>
   fileDownload('download?id=' + job + '&kind=' + b.dataset.kind,
     b.dataset.kind + '_' + job.slice(0, 8) + (b.dataset.kind === 'capacity_json' ? '.json' : '.csv')).catch(e => toast(e.message)));
}

async function capacityPage() {
 const main = $('main'), workspace = state.workspace.id;
 main.innerHTML = '<section id="cap-form" class="panel">正在读取容量数据目录…</section>';
 const form = $('cap-form');
 try {
   const catalog = await api('capacity_catalog');
   if (!form.isConnected) return;
   const option = (value, title) => '<option value="' + esc(value) + '">' + esc(title) + '</option>';
   const status = {complete:'已校验', running:'下载中', paused:'已暂停，可续传', pending:'待下载', partial:'部分取得', unavailable:'暂不可得'};
   const ready = new Set(catalog.datasets.map(d => d.id));
   const sourceRows = catalog.sources.map(s => {
     const title = /^https?:\/\//.test(s.url) ? '<a href="' + esc(s.url) + '" target="_blank" rel="noopener noreferrer">' + esc(s.title) + '</a>' : esc(s.title);
     return '<tr><td>' + title + '</td><td>' + esc(s.kind) + '</td><td>' + esc(status[s.status] || s.status) +
       (s.total ? ' · ' + s.files + '/' + s.total : '') + (s.files ? ' <button class="secondary" data-folder="' + esc(s.id) + '">打开目录</button>' : '') + '</td><td>' +
       (ready.has(s.id) ? '<button class="secondary" data-series="' + esc(s.id) + '">使用容量曲线</button>' : '—') + '</td></tr>';
   }).join('');
   form.innerHTML = '<h2>放电容量随循环的预测</h2><div class="form-actions"><label>逐循环数据 <select id="cap-dataset">' +
     catalog.datasets.map(d => option(d.id, d.title)).join('') + option('', '导入容量 CSV…') + '</select></label>' +
     '<input type="file" id="cap-file" accept=".csv" hidden></div><p id="cap-method" class="detail-note"></p><p id="cap-hint" class="detail-note"></p>' +
     '<div class="form-actions"><label>电芯 / 轨迹 <select id="cap-cell"></select></label><label>算法 <select id="cap-algo">' +
     catalog.algorithms.map(a => option(a.id, a.title)).join('') + '</select></label></div>' +
     '<div class="form-actions"><label><span id="cap-cut-label">训练截止循环</span> <input type="number" id="cap-cut" step="1"></label>' +
     '<label><span id="cap-horizon-label">末次实测后外推圈数</span> <input type="number" id="cap-horizon" min="0" max="5000" step="1" value="0"></label>' +
     '<label>预测区间 <select id="cap-interval"><option value="">仅点预测</option><option value="80">80%</option>' +
     '<option value="90" selected>90%</option><option value="95">95%</option></select></label>' +
     '<button id="cap-run" class="primary" disabled>预测容量</button></div>';
   main.insertAdjacentHTML('beforeend', '<div id="cap-result" aria-live="polite"></div><section class="panel"><h3>本方案预测记录</h3>' +
     '<div id="cap-history"></div></section><details class="panel"><summary>钠电公开数据下载目录（' + catalog.sources.length +
     ' 条来源）</summary><div class="scroll"><table><thead><tr><th>数据来源</th><th>实验类型</th><th>本机文件</th><th>逐循环容量</th></tr></thead><tbody>' + sourceRows +
     '</tbody></table></div><p id="cap-directory" aria-live="polite"></p></details>');
   main.querySelectorAll('[data-folder]').forEach(b => b.onclick = async () => {
     try {
       const {folder} = await api('capacity_source_folder', {source:b.dataset.folder});
       if (form.isConnected) $('cap-directory').textContent = folder;
     } catch (e) { toast(e.message); }
   });
   const history = $('cap-history');
   const addJob = j => {
     const btn = document.createElement('button');
     btn.className = 'secondary';
     btn.textContent = j.result.dataset + ' · ' + j.result.cell_id + ' · ' + j.result.algorithm_name + ' · 截止 ' + j.result.cutoff;
     if (j.result.interval_level) btn.textContent += ' · ' + j.result.interval_level + '% 区间';
     btn.onclick = async () => {
       try { const r = await api('download?id=' + j.id + '&kind=capacity_json'); if (form.isConnected) capacityResult(j.id, r); }
       catch (e) { toast(e.message); }
     };
     history.prepend(btn);
   };
   state.jobs.filter(j => j.mode === 'capacity_forecast' && j.workspace === workspace).slice(0, 30).reverse().forEach(addJob);
   if (!history.children.length) history.textContent = '暂无预测记录。';
   let cells = [], source = {}, revision = 0, ordinal = false;
   const selectCell = () => {
     const c = cells.find(v => v.id === $('cap-cell').value);
     $('cap-run').disabled = !c || c.observations < 3;
     if (!c) return;
     const cut = $('cap-cut');
     cut.min = c.first; cut.max = c.last; cut.value = c.default_cutoff;
     $('cap-hint').textContent = c.observations + ' 个容量观测，' + (ordinal ? '观测序号 ' : '循环 ') +
       c.first + ' 至 ' + c.last + '。截止点后的实测值用于计算预测误差。';
   };
   const loadCells = async () => {
     const current = ++revision, chosen = $('cap-dataset').value, file = $('cap-file');
     file.hidden = Boolean(chosen);
     const dataset = catalog.datasets.find(d => d.id === chosen);
     ordinal = dataset?.axis_label === '循环观测序号';
     $('cap-method').textContent = dataset?.method || '';
     $('cap-cut-label').textContent = ordinal ? '训练截止观测序号' : '训练截止循环';
     $('cap-horizon-label').textContent = ordinal ? '末次实测后外推观测数' : '末次实测后外推圈数';
     $('cap-cell').replaceChildren(); $('cap-run').disabled = true; $('cap-result').replaceChildren();
     if (!chosen && !file.files.length) {
       $('cap-hint').textContent = '选择 UTF-8 CSV，表头为 cell_id,cycle,capacity_Ah，每只电芯每圈一行。';
       return;
     }
     $('cap-hint').textContent = '正在读取逐循环容量…';
     try {
       if (!chosen && file.files[0].size > 20000000) throw Error('逐循环 CSV 超过 20 MB。');
       const input = chosen ? {dataset:chosen} : {filename:file.files[0].name, content:await base64File(file.files[0])};
       const available = await api('capacity_cells', input);
       if (!form.isConnected || revision !== current) return;
       source = input; cells = available;
       $('cap-cell').innerHTML = cells.map(c => option(c.id, c.id)).join('');
       selectCell();
     } catch (e) { if (form.isConnected && revision === current) $('cap-hint').textContent = e.message; }
   };
   $('cap-dataset').onchange = loadCells; $('cap-file').onchange = loadCells; $('cap-cell').onchange = selectCell;
   main.querySelectorAll('[data-series]').forEach(b => b.onclick = () => {
     $('cap-dataset').value = b.dataset.series;
     loadCells(); form.scrollIntoView({block:'start'});
   });
   $('cap-run').onclick = async () => {
     const current = revision, btn = $('cap-run');
     btn.disabled = true;
     try {
       const {job, result} = await api('capacity_forecast', {...source, workspace, cell:$('cap-cell').value,
         algorithm:$('cap-algo').value, cutoff:$('cap-cut').value, horizon:$('cap-horizon').value,
         interval_level:$('cap-interval').value || null});
       if (!state.jobs.some(j => j.id === job.id)) state.jobs.unshift(job);
       if (!form.isConnected) return;
       if (!history.children.length) history.replaceChildren();
       addJob(job);
       if (current === revision) capacityResult(job.id, result);
     } catch (e) { toast(e.message); }
     finally { if (form.isConnected && current === revision) btn.disabled = false; }
   };
   await loadCells();
 } catch (e) { if (form.isConnected) form.textContent = e.message; }
}

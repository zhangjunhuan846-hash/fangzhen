function agentFields(){
 const panel=document.createElement('div');panel.id='agent-fields';panel.hidden=true;
 panel.innerHTML=`<div class="field"><label>诊断案例</label><select id="agent-case"><option value="graphite">SINTEF石墨半电池（positive槽位）</option><option value="chen">Chen2020全电池（正极参数）</option></select></div><div class="field"><label>建议策略</label><select id="agent-strategy"><option value="rules">规则坐标探索（无需密钥）</option><option value="llm">LLM历史反馈建议（需本机配置）</option></select></div><div class="field"><label>仿真预算，含初始回放</label><input id="agent-budget" type="number" min="3" max="20" value="7"></div><div class="field"><label>可调参数</label><select id="agent-parameters"><option value="both">扩散系数＋交换电流密度</option><option value="diffusivity">仅扩散系数</option><option value="kinetics">仅交换电流密度</option></select></div><div class="field"><label>最小倍率 / 最大倍率（相对原函数）</label><div class="form-actions"><input id="agent-lower" type="number" min="0.01" max="1" step="0.01" value="0.1"><input id="agent-upper" type="number" min="1" max="100" step="0.1" value="10"></div></div><label id="agent-consent" hidden><input id="agent-accept" type="checkbox"> 向配置的LLM接口发送公开案例的参数历史及诊断指标</label><p class="detail-note">几何、载量、OCP和初始状态固定。每轮使用相同观测窗口；失败候选不参与排序。LLM连接或建议无效时停止并记录原因。<br>借鉴 <a href="https://github.com/opqrst-chen/Battery-Sim-Agent" target="_blank" rel="noopener">Battery-Sim-Agent</a>。本任务使用公开数据，不读取你的样品记录。</p>`;
 $('forward-fields').after(panel);
 const settings=document.createElement('details');settings.id='agent-api-settings';settings.open=!!state.agentApiOpen;
 settings.innerHTML=`<summary>模型API地址与端口</summary><div class="field"><label>API基础地址（含端口；以 /v1 结尾）</label><input id="agent-api-url" type="url" placeholder="http://localhost:11434/v1" autocomplete="off"></div><div class="field"><label>模型名</label><input id="agent-api-model" type="text" placeholder="例如本机模型名称" autocomplete="off"></div><div class="field"><label>API密钥（留空保留已存密钥）</label><input id="agent-api-key" type="password" autocomplete="new-password" placeholder="本机模型可留空"></div><label><input id="agent-api-clear" type="checkbox"> 清除已存密钥</label><div class="form-actions"><button id="agent-api-save" type="button" class="secondary">保存本机配置</button><button id="agent-api-probe" type="button" class="secondary">检查接口</button></div><p id="agent-api-status" class="detail-note">正在读取本机配置…</p><p class="detail-note">接口检查由Windows工作站读取模型列表；仿真进程在WSL中运行，实际连通性需以LLM任务为准。密钥只保存在本机 data/agent_llm.local.json，不写入任务记录。</p>`;
 panel.append(settings);
 settings.ontoggle=()=>{state.agentApiOpen=settings.open;};
 $('agent-strategy').onchange=()=>{const llm=$('agent-strategy').value==='llm';$('agent-consent').hidden=!llm;if(llm&&!state.agentApi?.configured)settings.open=true;};
 $('agent-api-save').onclick=async()=>{try{const result=await api('agent_llm',{base_url:$('agent-api-url').value,model:$('agent-api-model').value,api_key:$('agent-api-key').value,clear_key:$('agent-api-clear').checked});state.agentApi=result;$('agent-api-key').value='';$('agent-api-clear').checked=false;agentApiStatus(result);toast('模型API配置已保存到本机');}catch(e){toast(e.message);}};
 $('agent-api-probe').onclick=async()=>{try{const result=await api('agent_llm_probe',{});$('agent-api-status').textContent=result.note;toast('接口可达');}catch(e){toast(e.message);}};
 agentApiLoad();
}
function agentApiStatus(result){if($('agent-api-status'))$('agent-api-status').textContent=result.configured?`已配置 ${result.model} · ${result.has_api_key?'已保存密钥':'无密钥'}`:(result.error||'尚未配置模型API，可使用规则探索。');}
async function agentApiLoad(){
 try{const result=state.agentApi||await api('agent_llm');state.agentApi=result;
  if(!$('agent-api-url'))return;
  $('agent-api-url').value=result.base_url||'';$('agent-api-model').value=result.model||'';agentApiStatus(result);
 }catch(e){if($('agent-api-status'))$('agent-api-status').textContent='读取配置失败：'+e.message;}
}
function agentPayload(){
 const lo=Number($('agent-lower').value),hi=Number($('agent-upper').value);
 if(!Number.isFinite(lo)||!Number.isFinite(hi)||lo<.01||lo>1||hi<1||hi>100||lo>=hi)throw Error('倍率需满足0.01≤最小≤1≤最大≤100，且最小小于最大。');
 const selected=$('agent-parameters').value;
 const keys=selected==='both'?['diffusivity','kinetics']:[selected];
 return {case:$('agent-case').value,strategy:$('agent-strategy').value,budget:Number($('agent-budget').value),
         bounds:Object.fromEntries(keys.map(k=>[k,[Math.log10(lo),Math.log10(hi)]])),accept_llm:$('agent-accept').checked};
}
function agentResult(r){
 if(r.evidence_type!=='public_agent_parameter_exploration')return '';
 const stops={budget_exhausted:'达到仿真预算',candidate_exhausted:'可用候选已探索',repeated_proposal:'建议重复，停止',proposal_rejected:'建议或接口无效，停止'};
 return `<h3>参数探索诊断</h3><p>${esc(r.strategy==='llm'?'LLM建议':'规则坐标探索')} · ${r.simulations_used}/${r.simulation_budget}次 · ${esc(stops[r.stop_reason]||r.stop_reason)}</p><p>初始误差 ${fmt(r.initial_rmse_mV)} mV → 最佳 ${fmt(r.rmse_mV)} mV；改善 ${fmt(r.improvement_mV)} mV。</p><p>${esc(r.best?.diagnostic||'没有覆盖比较窗口的有效候选。')}</p>${r.best?`<table class="result-table"><tr><th>可调参数</th><th>最佳倍率</th></tr>${Object.entries(r.best.log_multipliers).map(([k,z])=>`<tr><td>${esc(r.parameter_keys[k])}</td><td>${fmt(10**z)} ×</td></tr>`).join('')}</table>`:''}<ul>${(r.next_steps||[]).map(t=>`<li>${esc(t)}</li>`).join('')}</ul><h3>逐轮记录</h3><table class="result-table"><tr><th>轮次</th><th>结果</th><th>误差 mV</th><th>建议依据</th></tr>${(r.history||[]).map(h=>`<tr><td>${h.round}</td><td>${h.status==='ok'?'已覆盖':'失败'}</td><td>${fmt(h.rmse_mV)}</td><td>${esc(h.reason)}</td></tr>`).join('')}</table><p class="detail-note">独立留出验证：尚未执行。此处最佳倍率属于有效候选，不代表唯一物理参数。</p>`;
}

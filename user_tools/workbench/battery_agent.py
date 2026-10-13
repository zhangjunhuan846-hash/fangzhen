"""Bounded parameter proposals and inspectable memory, inspired by Battery-Sim-Agent.

This module uses only stdlib; simulation and scoring remain in the physics worker.
"""
import json
import math
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlsplit
from user_tools.workbench.agent_api_settings import validate_endpoint

UPSTREAM = 'https://github.com/opqrst-chen/Battery-Sim-Agent'
PARAMETERS = {
    'diffusivity': 'Positive particle diffusivity [m2.s-1]',
    'kinetics': 'Positive electrode exchange-current density [A.m-2]',
}
CASES = {
    'graphite': ('sintef_graphite', '4ccc47', 'pOCV-deli', 'Ecker2015_graphite_halfcell'),
    'chen': ('chen2020', '02', 'C10', 'Chen2020'),
}


def normalize(config):
    case = config.get('case', 'graphite')
    strategy = config.get('strategy', 'rules')
    if case not in CASES or strategy not in ('rules', 'llm'):
        raise ValueError('请选择公开案例和规则/LLM策略。')
    budget = config.get('budget', 7)
    if isinstance(budget, bool) or not isinstance(budget, int) or not 3 <= budget <= 20:
        raise ValueError('仿真预算需为3–20的整数，包含初始回放。')
    bounds = config.get('bounds', {'diffusivity': [-1, 1], 'kinetics': [-1, 1]})
    if not isinstance(bounds, dict) or not bounds or set(bounds) - set(PARAMETERS):
        raise ValueError('仅允许扩散和动力学的log10倍率边界；几何/OCP/初始状态保持固定。')
    parsed = {}
    for key, pair in bounds.items():
        if not isinstance(pair, (list, tuple)) or len(pair) != 2 or any(isinstance(x, bool) for x in pair):
            raise ValueError('每个参数需提供两个边界。')
        lo, hi = map(float, pair)
        if not all(math.isfinite(x) for x in (lo, hi)) or not -2 <= lo <= 0 <= hi <= 2 or lo >= hi:
            raise ValueError('log10倍率边界需在[-2,2]内并包含初始值0。')
        parsed[key] = [lo, hi]
    if strategy == 'llm' and config.get('accept_llm') is not True:
        raise ValueError('LLM策略需明确接受发送公开案例的诊断与参数历史。')
    return {'case': case, 'strategy': strategy, 'budget': budget, 'bounds': parsed,
            'accept_llm': strategy == 'llm'}


def validate_proposal(values, bounds):
    if not isinstance(values, dict) or set(values) != set(bounds):
        raise ValueError('建议必须包含且仅包含所选可调参数。')
    output = {}
    for key, value in values.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError('建议参数需为数值。')
        value = float(value)
        if not math.isfinite(value) or not bounds[key][0] <= value <= bounds[key][1]:
            raise ValueError('建议参数超出声明边界。')
        output[key] = value
    return output


def rule_proposal(history, bounds):
    successful = [r for r in history if r.get('status') == 'ok']
    center = min(successful, key=lambda r: r['rmse_mV'])['log_multipliers'] if successful else dict.fromkeys(bounds, 0.)
    seen = {tuple(round(r['log_multipliers'][k], 8) for k in bounds) for r in history}
    for step in (.5, 1., .25, .125, .0625):
        for key in bounds:
            for sign in (1, -1):
                values = dict(center)
                values[key] = min(bounds[key][1], max(bounds[key][0], values[key] + sign * step))
                if tuple(round(values[k], 8) for k in bounds) not in seen:
                    return values, '围绕当前最低误差候选进行受约束坐标探索。'
    return None, '边界内候选已探索完毕。'


def llm_proposer(path):
    """Read credentials locally, never copy them into job inputs or memory."""
    config = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    base, model = validate_endpoint(config['base_url'], config['model'])
    url = urlsplit(base)
    key = str(config.get('api_key', ''))
    def propose(history, bounds):
        context = {'bounds_log10_multiplier': bounds, 'parameter_keys': {k: PARAMETERS[k] for k in bounds},
                   'history': history, 'comparison': 'fixed measured time window; geometry/OCP/initial state frozen'}
        messages = [{'role': 'system', 'content':
            'You propose battery model parameter candidates. Use only supplied evidence. '
            'Lower fixed-window voltage RMSE is better. Examine stage residuals and failed simulations. '
            'Do not claim parameter identification or material validation. Return JSON only: '
            '{"log_multipliers": {all allowed keys: finite number within bounds}, "reason": "brief evidence-based reason"}. '
            'Avoid already evaluated proposals. Values are log10 multipliers of the original parameter functions.'},
            {'role': 'user', 'content': json.dumps(context, ensure_ascii=False, allow_nan=False)}]
        body = json.dumps({'model': model, 'messages': messages, 'temperature': 0}).encode()
        request = Request(base + '/chat/completions', data=body,
                          headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key})
        try:
            with urlopen(request, timeout=45) as response:
                raw = response.read(200001)
            if len(raw) > 200000:
                raise ValueError('response too large')
            content = json.loads(raw)['choices'][0]['message']['content']
            answer = json.loads(content)
            values = validate_proposal(answer['log_multipliers'], bounds)
            return values, str(answer.get('reason', ''))[:1200]
        except Exception:
            # Remote bodies and exception strings can contain credentials; do not persist them.
            raise ValueError('LLM接口或建议校验失败；请检查本机配置、JSON格式和参数边界。') from None
    return propose, {'model': model, 'endpoint_host': url.hostname, 'endpoint_port': url.port}


def explore(config, evaluate, out, proposer=None):
    config = normalize(config)
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    bounds = config['bounds']; history = []; stopped = 'budget_exhausted'
    values = dict.fromkeys(bounds, 0.); reason = '初始参考参数，所有倍率为1。'
    for index in range(config['budget']):
        entry = {'round': index, 'log_multipliers': dict(values), 'reason': reason}
        try:
            score = evaluate(values, out / f'round_{index:02d}')
            if not math.isfinite(score['rmse_mV']) or score['rmse_mV'] < 0:
                raise ValueError('invalid score')
            entry.update(score, status='ok')
        except Exception:
            entry.update(status='failed', diagnostic='仿真失败或未覆盖固定比较窗口；不参与最佳候选排序。')
        history.append(entry)
        (out / 'memory.json').write_text(json.dumps(history, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
        print(f"Agent round {index}: {entry['status']}, RMSE={entry.get('rmse_mV')}", flush=True)
        if index + 1 == config['budget']:
            break
        try:
            values, reason = (proposer if config['strategy'] == 'llm' else rule_proposal)(history, bounds)
            if values is None:
                stopped = 'candidate_exhausted'; break
            values = validate_proposal(values, bounds)
            if any(all(abs(r['log_multipliers'][k] - values[k]) < 1e-8 for k in bounds) for r in history):
                stopped = 'repeated_proposal'; break
        except Exception:
            stopped = 'proposal_rejected'; break
    good = [r for r in history if r['status'] == 'ok']
    best = min(good, key=lambda r: r['rmse_mV']) if good else None
    initial = history[0].get('rmse_mV') if history[0]['status'] == 'ok' else None
    spread = max(r['rmse_mV'] for r in good) - min(r['rmse_mV'] for r in good) if len(good) > 1 else None
    next_steps = ['使用未参与探索的倍率/协议检查冻结候选，避免用同一曲线宣称独立验证。',
                  '核对OCP、初始状态、几何与测试协议来源；阶段误差不能唯一确定物理原因。']
    if spread is not None and spread < .1:
        next_steps.insert(0, '已探索候选的误差差异小于0.1 mV；建议先补充更强激发的倍率或脉冲数据，再判断这些参数是否可辨识。')
    return {'evidence_type': 'public_agent_parameter_exploration', 'strategy': config['strategy'],
            'source_inspiration': UPSTREAM, 'case': config['case'], 'bounds_log10_multiplier': bounds,
            'simulations_used': len(history), 'simulation_budget': config['budget'], 'stop_reason': stopped,
            'initial_rmse_mV': initial, 'rmse_mV': best['rmse_mV'] if best else None,
            'improvement_mV': initial - best['rmse_mV'] if best and initial is not None else None,
            'best': best, 'history': history, 'parameter_verdict': 'effective_candidate_only',
            'observed_candidate_rmse_spread_mV': spread, 'next_steps': next_steps,
            'independent_validation': 'not_performed',
            'scope': '公开数据固定时间窗口内的参数探索；几何/OCP/初始状态固定。石墨案例使用positive槽位。尚未独立验证参数唯一性、留出预测或你的再生石墨材料。'}

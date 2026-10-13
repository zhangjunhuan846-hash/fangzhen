"""Native schemas for multi-objective campaigns; no executable expressions."""
import csv
import io
import math
from user_tools.workbench.ml_data import number

def parse_campaign(raw, config):
    if len(raw)>3_000_000:raise ValueError('闭环CSV最多3MB。')
    reader=csv.DictReader(io.StringIO(raw.decode('utf-8-sig')));names=reader.fieldnames or []
    if len(names)!=len(set(names)) or not {'record_id','group_id','batch_id','status'}<=set(names):
        raise ValueError('需要不重复表头和record_id/group_id/batch_id/status。')
    objectives=config.get('objectives',[]);features=config.get('features',[])
    if not 1<=len(objectives)<=5 or len({o.get('key') for o in objectives})!=len(objectives):
        raise ValueError('请选择1–5个不同目标。')
    if not 1<=len(features)<=20 or len(set(features))!=len(features):raise ValueError('请选择1–20个不同输入。')
    forbidden={'record_id','group_id','batch_id','status'}|{o['key'] for o in objectives}
    if any(k not in names or k in forbidden or k.startswith('_') for k in features):raise ValueError('输入不能是编号、状态、来源元数据或目标。')
    for o in objectives:
        if o['key'] not in names or o['key'] in {'record_id','group_id','batch_id','status'} or o['key'].startswith('_') or o.get('direction') not in ['maximize','minimize']:raise ValueError('目标列或方向无效。')
        for bound in ['lower','upper']:
            if o.get(bound) not in (None,'') and number(o[bound]) is None:raise ValueError('目标边界必须有限。')
        if o.get('lower') not in (None,'') and o.get('upper') not in (None,'') and float(o['lower'])>float(o['upper']):raise ValueError('目标下限高于上限。')
    rows=[];ids=set();group_batches={}
    for rawrow in reader:
        r={k:(str(v).strip() if v is not None else '') for k,v in rawrow.items()};ident=r['record_id']
        if not ident or ident in ids:raise ValueError('record_id缺失或重复。')
        ids.add(ident)
        if not r['group_id'] or not r['batch_id']:raise ValueError('工艺组和原料批次必须填写。')
        if r['group_id'] in group_batches and group_batches[r['group_id']]!=r['batch_id']:raise ValueError('同一工艺组跨批次。')
        group_batches[r['group_id']]=r['batch_id']
        if r['status'] not in ['completed','candidate','pending','partial','failed_measurement','failed_preparation']:
            raise ValueError('status使用completed/candidate/pending/partial/failed_measurement/failed_preparation。')
        for o in objectives:
            key=o['key'];value=r.get(key)
            if value not in (None,'') and number(value) is None:raise ValueError('目标必须为有限数值：'+key)
            r[key]=number(value)
            if o.get('unit')=='fraction' and r[key] is not None and not 0<=r[key]<=1:raise ValueError('比例目标需0–1：'+key)
            if r['status'] in ['candidate','pending'] and r[key] is not None and not o.get('known'):
                raise ValueError('未完成候选不能带未来性能标签：'+key)
            if r['status']=='completed' and r[key] is None:raise ValueError('completed需填写全部目标；尚未测全请用partial。')
            if o.get('known') and r[key] is None:raise ValueError('已知清单/成本目标必须提供数值：'+key)
        rows.append(r)
        if len(rows)>200:raise ValueError('第一版闭环最多200条记录。')
    fields=[]
    roles=config.get('roles',{})
    for key in features:
        observed=[r[key] for r in rows if r.get(key) not in (None,'')]
        numeric=bool(observed) and all(number(v) is not None for v in observed)
        if roles.get(key)!='process':raise ValueError('工艺候选输入必须明确为实验前已知：'+key)
        fields.append({'key':key,'label':key,'kind':'numeric' if numeric else 'categorical','stage':'process'})
        for r in rows:
            if numeric:r[key]=number(r.get(key))
    if config.get('same_protocol') is not True:raise ValueError('请明确目标口径和测试协议一致；不同材料批次应分别建闭环。')
    batches={r['batch_id'] for r in rows}
    if len(batches)>1:raise ValueError('当前闭环每次一个原料批次，A/B分别运行。')
    return {'rows':rows,'fields':fields,'objectives':objectives,'source':'user_campaign_csv','group_basis':'用户声明独立工艺条件'}

def input_conflicts(row, fields, observed, config):
    errors=[]
    for field in fields:
        key=field['key'];value=row.get(key)
        if value in (None,''):errors.append(key+'缺失');continue
        if field['kind']=='numeric':
            if number(value) is None:errors.append(key+'数值无效');continue
            bounds=config.get('input_bounds',{}).get(key)
            vals=[number(r.get(key)) for r in observed if number(r.get(key)) is not None]
            if bounds is None and vals:bounds=[min(vals),max(vals)]
            if bounds is not None:
                if len(bounds)!=2 or any(number(v) is None for v in bounds) or float(bounds[0])>float(bounds[1]):raise ValueError('输入上下界无效。')
                if not float(bounds[0])<=float(value)<=float(bounds[1]):errors.append(key+'超出允许/已测范围')
        else:
            levels={str(r.get(key)) for r in observed if r.get(key) not in (None,'')}
            if levels and str(value) not in levels:errors.append(key+'未见类别')
    for rule in config.get('sum_constraints',[]):
        keys=rule.get('keys',[]);total=number(rule.get('total'));tol=number(rule.get('tolerance',.001))
        if not keys or total is None or tol is None or tol<0 or any(k not in {f['key'] for f in fields} for k in keys):raise ValueError('配方求和约束无效。')
        vals=[number(row.get(k)) for k in keys]
        if any(v is None for v in vals) or abs(sum(vals)-total)>tol:errors.append('配方求和约束冲突')
    if any(all(number(row.get(f['key']))==number(r.get(f['key'])) if f['kind']=='numeric'
               else str(row.get(f['key']))==str(r.get(f['key'])) for f in fields) for r in observed):
        errors.append('与已测输入组合相同，请使用重复实验任务')
    return errors

def known_objective_conflicts(row, objectives):
    errors=[]
    for o in objectives:
        if not o.get('known'):continue
        v=number(row.get(o['key']))
        if v is None:errors.append(o['key']+'已知目标缺失');continue
        if o.get('lower') not in (None,'') and v<float(o['lower']):errors.append(o['key']+'低于硬下限')
        if o.get('upper') not in (None,'') and v>float(o['upper']):errors.append(o['key']+'高于硬上限')
    return errors

"""Inspectable research calculations; no external numerical runtime required."""
from __future__ import annotations
import math
import random
import statistics as stats


def number(value, name):
    if value is None or value == '' or isinstance(value, bool):
        raise ValueError(name+'需要数值。')
    result=float(value)
    if not math.isfinite(result):raise ValueError(name+'必须是有限数值。')
    return result


def pareto(tables, config):
    rate=number(config.get('c_rate'), '倍率');cycle=number(config.get('cycle'), '循环号')
    keys=config.get('objectives',['capacity','ice'])
    if len(keys)<2 or len(set(keys))!=len(keys) or any(k not in ['capacity','ice','retention'] for k in keys):
        raise ValueError('至少选择两个不同性能目标。')
    minimum={k:number(v,k+'下限') for k,v in config.get('minimum',{}).items() if v not in ('',None)}
    if any(k not in keys for k in minimum):raise ValueError('约束字段需属于所选目标。')
    groups={};excluded=[];seen_cells=set();temperatures=set();duplicate_cells=set()
    for index,row in enumerate(tables.get('半电池',[])):
        try:
            if number(row.get('c_rate'),'倍率')!=rate or number(row.get('cycle'),'循环')!=cycle:continue
            cell=str(row.get('cell_id') or '')
            if not cell:raise ValueError('缺少电芯编号')
            if cell in seen_cells:
                duplicate_cells.add(cell)
                raise ValueError('同倍率/循环节点电芯编号重复，不能重复计数')
            seen_cells.add(cell)
            if row.get('temperature_C') not in ('',None):temperatures.add(number(row['temperature_C'],'温度'))
            sample=str(row.get('sample_id') or '')
            if not sample:raise ValueError('缺少样品编号')
            values={k:number(row.get(k),k) for k in keys}
            if any(v<0 or (k in ['ice','retention'] and v>1) for k,v in values.items()):raise ValueError('性能超出范围')
            groups.setdefault(sample,[]).append(values)
        except ValueError as e:excluded.append({'row':index+1,'reason':str(e)})
    if len(temperatures)>1:raise ValueError('所选倍率/循环节点含不同温度，请在独立方案中分开后比较。')
    if duplicate_cells:raise ValueError('电芯编号重复，请先修正：'+', '.join(sorted(duplicate_cells)))
    if not groups:raise ValueError('所选倍率/循环节点没有完整的可比较记录。')
    candidates=[]
    for sample,values in groups.items():
        means={k:stats.mean(v[k] for v in values) for k in keys}
        failures=[k for k,lo in minimum.items() if means[k]<lo]
        candidates.append({'sample_id':sample,'n':len(values),'means':means,
                           'std':{k:stats.stdev(v[k] for v in values) if len(values)>1 else None for k in keys},
                           'feasible':not failures,'failed_constraints':failures})
    feasible=[c for c in candidates if c['feasible']]
    for c in candidates:
        c['pareto']=c['feasible'] and not any(all(d['means'][k]>=c['means'][k] for k in keys) and
            any(d['means'][k]>c['means'][k] for k in keys) for d in feasible)
    return {'kind':'pareto','objectives':keys,'c_rate':rate,'cycle':cycle,'candidates':candidates,
            'front_count':sum(c['pareto'] for c in candidates),'excluded':excluded,
            'scope':'同倍率、同循环节点，按样品汇总电芯；所有目标最大化。实测均值的非支配筛选，不是预测或新工艺推荐。请确认温度、电极与质量归一口径相同。'}


def percentile(values,p):
    ordered=sorted(values);pos=(len(ordered)-1)*p;i=int(pos);f=pos-i
    return ordered[i]*(1-f)+ordered[min(i+1,len(ordered)-1)]*f


def tolerance(config):
    count=int(config.get('count',5000));seed=int(config.get('seed',42))
    if not 100<=count<=50000:raise ValueError('抽样次数需在100–50000之间。')
    specs=config.get('parameters',{});names=['mass_mg','area_cm2','thickness_um','active_fraction','active_density','other_density','q_ref']
    checked={}
    for key in names:
        s=specs.get(key,{})
        mean=number(s.get('mean'),key);spread=number(s.get('spread',0),key+'波动')
        distribution=s.get('distribution','normal')
        if mean<=0 or spread<0 or distribution not in ['normal','uniform','fixed']:raise ValueError(key+'的分布设置不合法。')
        if key=='active_fraction' and mean>1:raise ValueError('活性比例必须采用0–1。')
        checked[key]=(mean,spread,distribution)
    rho=number(config.get('mass_thickness_correlation',0),'质量与厚度相关系数')
    if not -1<=rho<=1:raise ValueError('相关系数需在−1到1之间。')
    if rho and any(checked[k][2]!='normal' or checked[k][1]==0 for k in ['mass_mg','thickness_um']):
        raise ValueError('非零相关系数要求质量、厚度均为有波动的正态分布。')
    rng=random.Random(seed);outputs={k:[] for k in ['capacity_mAh','areal_capacity_mAh_cm2','bulk_density_g_cm3','porosity','active_volume_fraction']};invalid=0
    for _ in range(count):
        z1=rng.gauss(0,1);z2=rho*z1+math.sqrt(max(0,1-rho*rho))*rng.gauss(0,1)
        draw={}
        for k,(m,s,d) in checked.items():
            z=z1 if k=='mass_mg' else z2 if k=='thickness_um' else rng.gauss(0,1)
            draw[k]=m if d=='fixed' else rng.uniform(m-s,m+s) if d=='uniform' else m+s*z
        if any(v<=0 for v in draw.values()) or draw['active_fraction']>1:invalid+=1;continue
        m,a,t,w,ra,ro,q=[draw[k] for k in names]
        bulk=m/1000/(a*t*1e-4);pore=1-bulk*(w/ra+(1-w)/ro);am=bulk*w/ra
        if not 0<=pore<=1 or not 0<=am<=1:invalid+=1;continue
        vals=[m/1000*w*q,m/1000*w*q/a,bulk,pore,am]
        if not all(math.isfinite(v) for v in vals):invalid+=1;continue
        for k,v in zip(outputs,vals):outputs[k].append(v)
    valid=count-invalid
    if not valid:raise ValueError('全部抽样均不符合物理范围，请检查干涂层质量、厚度、密度和单位。')
    summary={k:{'mean':stats.mean(v),'std':stats.stdev(v) if valid>1 else 0,'p025':percentile(v,.025),'p50':percentile(v,.5),'p975':percentile(v,.975)} for k,v in outputs.items()}
    limits=config.get('limits',{});compliance={}
    for k,bounds in limits.items():
        if k not in outputs or len(bounds)!=2:raise ValueError('未知输出或规格区间。')
        lo=None if bounds[0] in ('',None) else number(bounds[0],k+'下限');hi=None if bounds[1] in ('',None) else number(bounds[1],k+'上限')
        if lo is not None and hi is not None and lo>=hi:raise ValueError('下限必须小于上限。')
        passes=sum((lo is None or v>=lo) and (hi is None or v<=hi) for v in outputs[k])
        compliance[k]={'among_valid':passes/valid,'valid_and_pass_fraction':passes/count}
    return {'kind':'tolerance','seed':seed,'count':count,'valid':valid,'invalid':invalid,'invalid_fraction':invalid/count,
            'summary':summary,'compliance':compliance,
            'scope':'干涂层，两类固体体积可加；其他固体密度为预先确定的等效密度。正态波动填标准差，均匀波动填半宽。质量/厚度以外独立。统计区间基于有效抽样，物理无效抽样单独报告。参考容量未包含倍率极化，预测合格比例不等于实测制程能力。'}


def capability(config):
    values=[number(v,'观测值') for v in config.get('values',[])]
    if not 3<=len(values)<=50000:raise ValueError('需要3–50000个独立重复观测值。')
    lo=None if config.get('lsl') in ('',None) else number(config['lsl'],'规格下限')
    hi=None if config.get('usl') in ('',None) else number(config['usl'],'规格上限')
    if lo is None and hi is None:raise ValueError('至少需要一个规格限。')
    if lo is not None and hi is not None and lo>=hi:raise ValueError('规格下限必须小于上限。')
    mean=stats.mean(values);sd=stats.stdev(values)
    if sd==0:raise ValueError('观测标准差为零，无法估计能力指数；请检查重复值与测量分辨率。')
    cpl=(mean-lo)/(3*sd) if lo is not None else None;cpu=(hi-mean)/(3*sd) if hi is not None else None
    within=None if config.get('within_std') in ('',None) else number(config['within_std'],'组内标准差')
    if within is not None and within<=0:raise ValueError('组内标准差需大于零。')
    if within is not None and not str(config.get('within_source','')).strip():raise ValueError('请填写组内标准差的估计来源。')
    within_indices=None
    if within is not None:
        lower=(mean-lo)/(3*within) if lo is not None else None;upper=(hi-mean)/(3*within) if hi is not None else None
        within_indices={'cp':(hi-lo)/(6*within) if lo is not None and hi is not None else None,
                        'cpk':min(v for v in [lower,upper] if v is not None),'cpl':lower,'cpu':upper,
                        'sigma_within':within,'source':str(config.get('within_source','未提供'))[:500]}
    tails=(stats.NormalDist(mean,sd).cdf(lo) if lo is not None else 0)+(1-stats.NormalDist(mean,sd).cdf(hi) if hi is not None else 0)
    ready=all(config.get(k) is True for k in ['same_process','stable','normal']) and len(values)>=30
    return {'kind':'capability','n':len(values),'mean':mean,'sample_std':sd,'lsl':lo,'usl':hi,
            'cp':(hi-lo)/(6*sd) if lo is not None and hi is not None else None,
            'cpl':cpl,'cpu':cpu,'index_estimate':min(x for x in [cpl,cpu] if x is not None),'within_indices':within_indices,
            'observed_out_of_spec':sum((lo is not None and v<lo) or (hi is not None and v>hi) for v in values),
            'normal_assumption_out_of_spec_fraction':tails,'status':'assumptions_declared' if ready else 'exploratory',
            'scope':'采用所有观测的样本标准差：总体性能指数Pp/Ppk；仅在同一稳定正态制程且总体波动代表组内波动时可近似解释Cp/Cpk。未独立验证稳定性/正态性；30是本工具探索提示门槛，不是能力认证标准。禁止混合不同DOE条件或使用模拟值声称实测能力。'}


def run_analysis(tables,config):
    kind=config.get('kind')
    if kind=='pareto':return pareto(tables,config)
    if kind=='tolerance':return tolerance(config)
    if kind=='capability':return capability(config)
    if kind=='sample':
        from user_tools.workbench.sample import build_sample
        return build_sample(tables,config)
    raise ValueError('未知分析类型。')

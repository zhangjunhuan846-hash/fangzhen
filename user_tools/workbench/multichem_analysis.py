"""Small, explicit-data analyses for lithium and sodium research workflows.

These are independent baselines inspired by published methods, not upstream
package implementations or validated battery diagnostics.
"""
from __future__ import annotations

import csv
import io
import math
import statistics

from user_tools.workbench.preprocess import normalize_csv


def table(raw, required, max_rows=50000):
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = raw.decode('gb18030')
    reader = csv.DictReader(io.StringIO(text))
    names = reader.fieldnames or []
    if len(names) != len(set(names)) or not set(required) <= set(names):
        raise ValueError('CSV需要不重复表头：' + ', '.join(required))
    rows = list(reader)
    if not 2 <= len(rows) <= max_rows or any(None in r or any(v is None for v in r.values()) for r in rows):
        raise ValueError(f'CSV需要2–{max_rows}行且每行列数一致。')
    return rows


def value(x, name):
    if isinstance(x, bool):
        raise ValueError(name + '必须为有限数值。')
    try:
        n = float(x)
    except (ValueError, TypeError):
        raise ValueError(name + '必须为有限数值。') from None
    if not math.isfinite(n):
        raise ValueError(name + '必须为有限数值。')
    return n


def regression(points):
    n = len(points)
    if n < 3:
        raise ValueError('线性拟合需要至少三个点。')
    xm = statistics.mean(p[0] for p in points)
    ym = statistics.mean(p[1] for p in points)
    xx = sum((x-xm)**2 for x, _ in points)
    if xx <= 0:
        raise ValueError('输入变量必须有变化。')
    slope = sum((x-xm)*(y-ym) for x, y in points)/xx
    intercept = ym - slope*xm
    ssr = sum((y-(slope*x+intercept))**2 for x,y in points)
    sst = sum((y-ym)**2 for _,y in points)
    return {'slope':slope, 'intercept':intercept, 'r2':1-ssr/sst if sst > 0 else None,
            'slope_standard_error':math.sqrt(ssr/(n-2)/xx), 'n':n}


def quality(raw, config):
    records, report = normalize_csv(raw, config)
    # Adjacent differences are screened within each monotonic segment. A pulse
    # is not automatically an error; findings are only review candidates.
    findings = []
    for field in ('voltage_V', 'current_A'):
        changes = [(records[i]['source_row'], records[i][field]-records[i-1][field])
                   for i in range(1,len(records)) if records[i]['segment']==records[i-1]['segment']
                   and records[i][field] is not None and records[i-1][field] is not None]
        if len(changes) < 5:
            continue
        center = statistics.median(d for _,d in changes)
        mad = statistics.median(abs(d-center) for _,d in changes)
        if mad <= 1e-12:
            continue
        for row, delta in changes:
            score = abs(delta-center)/(1.4826*mad)
            if score > 8:
                findings.append({'source_row':row, 'field':field, 'change':delta, 'robust_score':score})
    report.update({'method':'相邻差分的中位数绝对偏差（MAD）筛查', 'suspect_count':len(findings),
                   'suspects':findings[:100], 'scope':report['scope']+' 差分突变可能是正常脉冲，仅供人工复核；不构成故障诊断。'})
    return report


def arrhenius(raw, config):
    rows = table(raw, ['temperature_C','value'])
    kind = config.get('quantity', 'conductivity')
    if kind not in ('conductivity','inverse_resistance'):
        raise ValueError('quantity只能为conductivity或inverse_resistance。')
    points=[]
    for row in rows:
        t=value(row['temperature_C'],'temperature_C')+273.15
        v=value(row['value'],'value')
        if t<=0 or v<=0: raise ValueError('绝对温度和测量值必须大于零。')
        y=v if kind=='conductivity' else 1/v
        points.append((1/t, math.log(y)))
    fit=regression(points)
    return {'quantity':kind,'fit':fit,'activation_energy_kJ_mol':-fit['slope']*8.314462618/1000,
            'slope_standard_error_kJ_mol':fit['slope_standard_error']*8.314462618/1000,
            'points':[{'inverse_temperature_K':x,'log_value':y} for x,y in points],
            'scope':'普通最小二乘；拟合温区及量纲由用户确认。R的倒数仅为指定电阻的代理，不能单独证明界面机理。'}


def align(raw, config):
    rows=table(raw,['stream','time_s','value'])
    offset=value(config.get('offset_s',0),'offset_s')
    if abs(offset)>1e9:raise ValueError('时间偏移超出范围。')
    streams={'electrochemistry':[], 'signal':[]}
    for row in rows:
        name=row['stream'].strip()
        if name not in streams:raise ValueError('stream必须为electrochemistry或signal。')
        p=(value(row['time_s'],'time_s')+(offset if name=='signal' else 0),value(row['value'],'value'))
        if streams[name] and p[0]<=streams[name][-1][0]:raise ValueError('每条信号的时间必须严格递增。')
        streams[name].append(p)
    a,b=streams['electrochemistry'],streams['signal']
    if len(a)<2 or len(b)<2:raise ValueError('两条信号各需至少两个点。')
    # Linear interpolation only inside measured signal range; never extrapolate.
    aligned=[];j=0
    for t,v in a:
        while j+1<len(b) and b[j+1][0]<t:j+=1
        if j+1>=len(b) or not b[j][0]<=t<=b[j+1][0]:continue
        t0,v0=b[j];t1,v1=b[j+1]
        aligned.append({'time_s':t,'electrochemistry':v,'signal':v0+(v1-v0)*(t-t0)/(t1-t0)})
    if not aligned:raise ValueError('调整偏移后两条信号没有可插值的重叠区间。')
    return {'offset_s':offset,'points':aligned,'scope':'手动提供时间偏移；仅重叠区间线性插值，不推断设备同步或进行光谱拟合。'}


def hysteresis(raw, config):
    rows=table(raw,['time_s','current_A','temperature_C'])
    cap=value(config.get('capacity_Ah'),'capacity_Ah')
    soc=value(config.get('initial_soc'),'initial_soc')
    gamma=value(config.get('hysteresis_rate'),'hysteresis_rate')
    curve=config.get('ocv_table')
    if cap<=0 or not 0<=soc<=1 or gamma<=0 or not isinstance(curve,list) or len(curve)<2:
        raise ValueError('需要正容量、0–1初始SOC、正滞回速率和至少两个OCV表节点。')
    # Each temperature has its own SOC curve; all grids must be rectangular.
    parsed=[]
    for r in curve:
        s=value(r.get('soc'),'soc');t=value(r.get('temperature_C'),'temperature_C')
        ch=value(r.get('charge_V'),'charge_V');di=value(r.get('discharge_V'),'discharge_V')
        r0=value(r.get('R0_ohm'),'R0_ohm')
        if not 0<=s<=1 or r0<=0:raise ValueError('SOC或电阻不合法。')
        parsed.append((s,t,ch,di,r0))
    ss=sorted({r[0] for r in parsed});ts=sorted({r[1] for r in parsed});grid={(r[0],r[1]):r for r in parsed}
    if len(ss)<2 or len(ts)<2 or len(grid)!=len(parsed) or len(grid)!=len(ss)*len(ts):
        raise ValueError('OCV/R0需要完整无重复的SOC×温度网格，且各轴至少2点。')
    def bracket(axis,x):
        if x<axis[0] or x>axis[-1]:raise ValueError('SOC或温度超出参数表范围，停止外推。')
        for i in range(len(axis)-1):
            if axis[i]<=x<=axis[i+1]:return axis[i],axis[i+1]
        raise ValueError('参数表范围错误。')
    def lookup(s,t,k):
        s0,s1=bracket(ss,s);t0,t1=bracket(ts,t)
        a=(s-s0)/(s1-s0);b=(t-t0)/(t1-t0)
        return (1-b)*((1-a)*grid[s0,t0][k]+a*grid[s1,t0][k])+b*((1-a)*grid[s0,t1][k]+a*grid[s1,t1][k])
    h=value(config.get('initial_hysteresis',0),'initial_hysteresis')
    if not -1<=h<=1:raise ValueError('初始滞回状态需在-1到1。')
    branches=config.get('rc_branches',[])
    if not isinstance(branches,list) or len(branches)>3:raise ValueError('rc_branches必须为不超过3个RC支路的列表。')
    rc=[]
    for branch in branches:
        if not isinstance(branch,dict):raise ValueError('RC支路需要参数对象。')
        resistance=value(branch.get('R_ohm'),'R_ohm');capacitance=value(branch.get('C_F'),'C_F')
        if resistance<=0 or capacitance<=0:raise ValueError('RC支路的电阻、电容必须为正。')
        rc.append((resistance,capacitance))
    polarizations=[0.]*len(rc)
    adaptation=config.get('rls')
    if adaptation is not None:
        if not isinstance(adaptation,dict):raise ValueError('rls必须为对象。')
        lam=value(adaptation.get('forgetting_factor'),'forgetting_factor')
        covariance=value(adaptation.get('initial_covariance'),'initial_covariance')
        limit=value(adaptation.get('max_delta_ohm'),'max_delta_ohm')
        if not .9<=lam<=1 or not 0<covariance<=1e6 or limit<=0 or limit>=min(r[4] for r in parsed):
            raise ValueError('RLS遗忘因子需0.9–1，初始协方差和变化限值需为正，且限值小于参数表最小R0。')
        if any(row.get('voltage_V') in (None,'') for row in rows):raise ValueError('在线RLS需要每行实测voltage_V。')
    delta=0.;output=[];prev=None
    for row in rows:
        t=value(row['time_s'],'time_s');i=value(row['current_A'],'current_A');temp=value(row['temperature_C'],'temperature_C')
        if abs(i)>1000:raise ValueError('电流超过模型数值范围。')
        if prev is not None:
            dt=t-prev[0]
            if dt<=0:raise ValueError('时间必须严格递增。')
            # Piecewise constant previous current; positive is discharge.
            old_i=prev[1];soc-=old_i*dt/(3600*cap)
            target=1 if old_i<0 else -1 if old_i>0 else h
            h=target+(h-target)*math.exp(-gamma*abs(old_i)*dt/(3600*cap))
            polarizations=[old_i*resistance+(v-old_i*resistance)*math.exp(-dt/(resistance*capacitance))
                           for v,(resistance,capacitance) in zip(polarizations,rc)]
        c,d,r=lookup(soc,temp,2),lookup(soc,temp,3),lookup(soc,temp,4)
        v=(c+d)/2+h*(c-d)/2-sum(polarizations)-i*(r+delta)
        item={'time_s':t,'soc':soc,'hysteresis':h,'voltage_V':v,'R0_ohm_used':r+delta}
        if row.get('voltage_V') not in (None,''):item['observed_V']=value(row['voltage_V'],'voltage_V')
        if adaptation is not None:
            # Prediction uses the prior estimate; the observation updates future steps only.
            sensitivity=-i
            gain=covariance*sensitivity/(lam+covariance*sensitivity*sensitivity)
            delta=max(-limit,min(limit,delta+gain*(item['observed_V']-v)))
            covariance=min(1e12,max(0.,(covariance-gain*sensitivity*covariance)/lam))
            item['R0_delta_after_update_ohm']=delta
        output.append(item);prev=(t,i)
    residuals=[r['voltage_V']-r['observed_V'] for r in output if 'observed_V' in r]
    return {'points':output,'voltage_rmse_V':math.sqrt(sum(x*x for x in residuals)/len(residuals)) if residuals else None,
            'scope':'用户参数的温度查表滞回模型；正电流放电，温度为测量输入。RC参数固定；可选R0递推最小二乘按实测逐点更新，不预测温度，不等于论文完整模型；应使用未参与更新的数据验证。'}


def partial_charge(raw, config):
    rows=table(raw,['time_s','current_A','voltage_V'])
    sign=config.get('charge_sign')
    if sign not in ('positive','negative'):raise ValueError('必须声明充电电流符号positive或negative。')
    multiplier=1 if sign=='positive' else -1
    prev=None;charge=0.;start=None;end=None
    for row in rows:
        t=value(row['time_s'],'time_s');i=value(row['current_A'],'current_A')*multiplier;v=value(row['voltage_V'],'voltage_V')
        if i<0:raise ValueError('包含反向电流，请先截取单个充电片段。')
        if prev:
            if t<=prev[0]:raise ValueError('时间必须严格递增。')
            charge+=(i+prev[1])*.5*(t-prev[0])/3600
        else:start=(t,v)
        prev=(t,i);end=(t,v)
    result={'duration_s':end[0]-start[0], 'voltage_start_V':start[1], 'voltage_end_V':end[1], 'charge_Ah':charge}
    if config.get('initial_soc') not in (None,'') or config.get('capacity_Ah') not in (None,''):
        soc=value(config.get('initial_soc'),'initial_soc');cap=value(config.get('capacity_Ah'),'capacity_Ah')
        if not 0<=soc<=1 or cap<=0:raise ValueError('初始SOC及容量无效。')
        result['soc_coulomb_count']=soc+charge/cap
        if result['soc_coulomb_count']>1:raise ValueError('积分SOC超过1，请核查初始SOC、容量和电流符号。')
    result['scope']='部分充电特征与可选安时积分基线；需要已知初始SOC和容量；未训练SOH或神经网络。'
    return result


def cv_compare(raw, config):
    rows=table(raw,['curve','potential_V','current_A'])
    grouped={}
    for r in rows:
        name=r['curve'].strip()
        if not name:raise ValueError('curve不能为空。')
        grouped.setdefault(name,[]).append((value(r['potential_V'],'potential_V'),value(r['current_A'],'current_A')))
    result=[]
    for name,points in grouped.items():
        if len(points)<2:raise ValueError('每条CV曲线至少2点。')
        anodic=max(points,key=lambda x:x[1]);cathodic=min(points,key=lambda x:x[1])
        result.append({'curve':name,'points':len(points),'max_current_A':anodic[1],'max_potential_V':anodic[0],
                       'min_current_A':cathodic[1],'min_potential_V':cathodic[0]})
    return {'curves':result,'scope':'直接比较原始CV曲线极值；不拟合反应机理，极值可能是端点或背景电流。'}


def hardcarbon(raw, config):
    rows=table(raw,['record_id','group_id','batch_id'])
    if len({r['record_id'] for r in rows})!=len(rows) or any(not r['record_id'] or not r['group_id'] or not r['batch_id'] for r in rows):
        raise ValueError('记录编号需非空唯一，每行需要来源组和批次。')
    fields=['carbonization_temperature_C','d002_nm','id_ig','ssa_m2_g','electrolyte_type','current_density_mA_g']
    missing={f:sum(not r.get(f) for r in rows) for f in fields}
    return {'rows':len(rows),'groups':len({r['group_id'] for r in rows}),'missing':missing,
            'scope':'数据结构与缺失检查。group_id须由用户按文献或批次建立；预测需在描述符建模页面使用该CSV并按组验证。'}


def prepare_hardcarbon(raw):
    import hashlib
    import unicodedata
    rows=table(raw,['doi','mapping_found','ice','carbonization_temperature_C','d002_nm','id_ig',
                    'ssa_m2_g','electrolyte_type','current_density_mA_g'])
    fields=['carbonization_temperature_C','d002_nm','id_ig','ssa_m2_g','electrolyte_type','current_density_mA_g']
    converted=[];excluded=[]
    for idx,row in enumerate(rows,2):
        source=unicodedata.normalize('NFKC',row['doi']).strip()
        target=row['ice'].strip()
        if row['mapping_found'].strip().lower()!='true' or not source:
            excluded.append({'source_row':idx,'reason':'来源映射缺失'});continue
        try:y=value(target,'ice')
        except ValueError:excluded.append({'source_row':idx,'reason':'ICE缺失或无效'});continue
        if not 0<=y<=1:excluded.append({'source_row':idx,'reason':'ICE超出0–1'});continue
        group='paper_'+hashlib.sha256(source.casefold().encode('utf8')).hexdigest()[:16]
        converted.append({'record_id':'source_row_'+str(idx),'group_id':group,'batch_id':group,
                          **{f:row.get(f,'') for f in fields},'ice':y})
    if not converted:raise ValueError('没有来源明确且目标有效的样本。')
    return converted,excluded


def electrolyte(raw, config):
    rows=table(raw,['record_id','salt','salt_mol_L','solvent_fraction'])
    seen=set();issues=[]
    for r in rows:
        ident=r['record_id'].strip()
        if not ident or ident in seen:raise ValueError('record_id不能为空或重复。')
        seen.add(ident)
        c=value(r['salt_mol_L'],'salt_mol_L');fraction=value(r['solvent_fraction'],'solvent_fraction')
        if not r['salt'].strip() or c<=0 or not 0<=fraction<=1:issues.append(ident)
    return {'rows':len(rows),'invalid_records':issues,'scope':'配方字段预检；solvent_fraction为用户指定单组分比例，并非自动验证多组分总和或化学兼容性。选点需使用多目标科研闭环页面和实测标签。'}


FUNCTIONS={'quality':quality,'arrhenius':arrhenius,'align':align,'hysteresis':hysteresis,
           'partial_charge':partial_charge,'cv':cv_compare,'hardcarbon':hardcarbon,'electrolyte':electrolyte}


def run(kind,raw,config):
    if kind not in FUNCTIONS:raise ValueError('未知分析类型。')
    if not raw or len(raw)>20_000_000:raise ValueError('CSV文件需非空且不超过20MB。')
    if not isinstance(config,dict):raise ValueError('配置必须是JSON对象。')
    return FUNCTIONS[kind](raw,config)

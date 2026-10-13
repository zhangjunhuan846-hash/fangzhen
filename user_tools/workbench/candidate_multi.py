"""Finite two-objective, independent-GP Monte Carlo EHVI; no hidden feedback."""
import hashlib
import json
import numpy as np
from user_tools.rg_loop.optimization import GaussianProcess


def hypervolume(points,reference):
    best=float(reference[1]);area=0.
    for x,y in sorted(points,reverse=True):
        if x<=reference[0] or y<=best:continue
        area+=(x-reference[0])*(y-best);best=y
    return float(area)


def finite_nehvi(models,train,xs,reference,minimum,count,seed):
    """q=1 finite-candidate MC-NEHVI with jointly sampled latent baselines."""
    n=len(train);allx=np.concatenate([train,xs])
    draws=np.stack([gp.joint_samples(allx,count,seed+i*1009) for i,gp in enumerate(models)],axis=-1)
    gains=np.zeros((count,len(xs)));passing=np.zeros(len(xs))
    valid=lambda y:y[0]>=max(0,minimum[0]) and max(0,minimum[1])<=y[1]<=1
    for k,sample in enumerate(draws):
        front=[y.tolist() for y in sample[:n] if valid(y)];base=hypervolume(front,reference)
        for i,y in enumerate(sample[n:]):
            if valid(y):
                passing[i]+=1;gains[k,i]=max(0,hypervolume(front+[y.tolist()],reference)-base)
    return gains.mean(axis=0),gains.std(axis=0,ddof=1)/np.sqrt(count),passing/count


def recommend_multi(config):
    records=config['records'];observed=[];available=[];ids=set();coordinates=set()
    if not 4<=len(records)<=500:raise ValueError('候选表需有4–500个独立条件。')
    for row in records:
        ident=str(row.get('candidate_id') or '').strip()
        if not ident or ident in ids:raise ValueError('候选编号缺失或重复；重复实验请先按条件汇总。')
        ids.add(ident)
        x=[float(row['x1']),float(row['x2'])]
        if not np.isfinite(x).all():raise ValueError('工艺输入需要有限数字。')
        if tuple(x) in coordinates:raise ValueError('相同工艺输入重复，请先汇总重复实验并核对编号。')
        coordinates.add(tuple(x))
        status=str(row.get('status','')).strip()
        if status=='completed':
            y=[float(row['capacity']),float(row['ice'])]
            if not np.isfinite(y).all() or y[0]<0 or not 0<=y[1]<=1:raise ValueError('容量需≥0；ICE需为0–1。')
            observed.append({'candidate_id':ident,'x':x,'y':y})
        elif status in ['candidate','pending']:
            if any(row.get(k) not in ('',None) for k in ['capacity','ice']):raise ValueError('未完成条件不得带性能标签，避免信息泄漏。')
            if status=='candidate':available.append({'candidate_id':ident,'x':x})
        else:raise ValueError('status只能是completed、candidate或pending。')
    if len(observed)<3 or not available:raise ValueError('至少需要3个已完成条件和1个未测试候选。')
    allx=np.array([r['x'] for r in observed+available]);lo=allx.min(axis=0);span=allx.max(axis=0)-lo
    if np.any(span<=0):raise ValueError('两个输入变量都需有变化；固定变量请从候选表中移除后重新设计。')
    train=(np.array([r['x'] for r in observed])-lo)/span;xs=(np.array([r['x'] for r in available])-lo)/span
    y=np.array([r['y'] for r in observed]);noise=np.array(config.get('noise',[5,.005]),float)
    if noise.shape!=(2,) or not np.isfinite(noise).all() or np.any(noise<=0):raise ValueError('需明确两个指标的正观测噪声标准差。')
    reference=np.array(config.get('reference',[0,0]),float);minimum=np.array(config.get('minimum',[0,0]),float)
    if reference.shape!=(2,) or minimum.shape!=(2,) or not np.isfinite(reference).all() or not np.isfinite(minimum).all():raise ValueError('参考点/下限需要两个有限数字。')
    if reference[0]<0 or not 0<=reference[1]<1 or minimum[0]<0 or not 0<=minimum[1]<=1:raise ValueError('参考点与性能下限超出物理范围。')
    feasible=y[np.all(y>=minimum,axis=1)]
    if len(feasible) and np.any(reference>=feasible.min(axis=0)):raise ValueError('超体积参考点需严格低于当前可行观测的两个指标。')
    baseline=hypervolume(feasible.tolist(),reference)
    models=[GaussianProcess().fit(train,y[:,i],float(noise[i])) for i in range(2)]
    predictions=[gp.predict(xs) for gp in models];mu=np.array([r[0] for r in predictions]).T;sigma=np.array([r[1] for r in predictions]).T
    count=int(config.get('mc_samples',256))
    if not 64<=count<=2048:raise ValueError('MC样本数需64–2048。')
    engine=config.get('engine','ehvi')
    if engine not in ['ehvi','nehvi']:raise ValueError('未知采集函数。')
    if engine=='nehvi' and len(observed)+len(available)>200:raise ValueError('轻量NEHVI一次最多200个已测+候选条件。')
    seed=int(config.get('seed',42));z=np.random.default_rng(seed).normal(size=(count,2));rank=[]
    joint=finite_nehvi(models,train,xs,reference,minimum,count,seed) if engine=='nehvi' else None
    for index,(row,m,s) in enumerate(zip(available,mu,sigma)):
        outcomes=m+z*s;scores=[];passing=0
        for draw in outcomes:
            valid=draw[0]>=minimum[0] and max(0,minimum[1])<=draw[1]<=1
            passing+=valid
            scores.append(max(0,hypervolume(feasible.tolist()+[draw.tolist()],reference)-baseline) if valid else 0)
        rank.append({**row,'mean_capacity':float(m[0]),'std_capacity':float(s[0]),'mean_ice':float(m[1]),'std_ice':float(s[1]),
                     'expected_hypervolume_improvement':float(joint[0][index]) if joint else float(np.mean(scores)),
                     'mc_standard_error':float(joint[1][index]) if joint else float(np.std(scores,ddof=1)/np.sqrt(count)),
                     'mc_feasible_fraction':float(joint[2][index]) if joint else float(passing/count)})
    rank.sort(key=lambda r:(-r['expected_hypervolume_improvement'],r['candidate_id']))
    positive=rank[0]['expected_hypervolume_improvement']>0
    return {'evidence_type':'unvalidated_candidate_recommendation','selected':rank[0] if positive else None,
            'engine':'finite_q1_mc_nehvi' if engine=='nehvi' else 'fixed_front_mc_ehvi',
            'recommendation_status':'candidate_to_validate' if positive else 'no_estimated_improvement',
            'decision_reason':('按正的有限候选MC-NEHVI排名选择' if engine=='nehvi' else '按正的MC-EHVI排名选择') if positive else '所有候选的MC预期改进为零；未强行选点，请核查目标/候选或补充观测。',
            'ranking':rank,'observations':len(observed),
            'reference':reference.tolist(),'minimum':minimum.tolist(),'noise_std':noise.tolist(),'mc_samples':count,'seed':int(config.get('seed',42)),
            'snapshot_sha256':hashlib.sha256(json.dumps(observed,sort_keys=True).encode()).hexdigest(),
            'scope':('有限候选q=1 MC-NEHVI：联合抽样已测点与候选的潜在函数，每次重新计算可行前沿；两个目标独立，固定GP超参数，报告MC标准误。不是官方qLogNEHVI或并行/连续优化复现。' if engine=='nehvi' else '固定实测前沿MC-EHVI，不传播前沿噪声。')+'同一材料批次/协议，仅用completed标签，pending不推荐；ICE范围约束不等于已校准的有界输出模型。推荐待真实实验验证，不保证优于随机。'}

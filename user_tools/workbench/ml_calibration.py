"""Independent-group split conformal helpers; never reuse training residuals."""
import hashlib
import math

def split_groups(rows, alpha=.1, minimum_training_groups=5):
    alpha=float(alpha)
    if not .0001 <= alpha <= .5:raise ValueError('alpha需0.0001–0.5；很小的alpha需要更多独立校准组。')
    groups=sorted({str(r['group_id']) for r in rows}, key=lambda g:hashlib.sha256(('calibration42:'+g).encode()).hexdigest())
    required=math.ceil(1/alpha-1e-12)-1
    count=max(required,math.ceil(.2*len(groups)))
    if len(groups)-count<minimum_training_groups:
        return list(rows),[],{'finite':False,'reason':'独立工艺组不足，不能同时保留训练组与有限校准区间',
                             'alpha':alpha,'required_calibration_groups':required,'available_groups':len(groups)}
    held=set(groups[:count]);train=[r for r in rows if str(r['group_id']) not in held];cal=[r for r in rows if str(r['group_id']) in held]
    return train,cal,{'finite':True,'alpha':alpha,'required_calibration_groups':required,
                      'training_groups':len(groups)-count,'calibration_groups':count,
                      'training_group_ids':groups[count:],'calibration_group_ids':groups[:count]}

def calibrate(rows, predictions, alpha=.1):
    grouped={}
    for row,pred in zip(rows,predictions):
        error=abs(float(row['target'])-float(pred))
        if not math.isfinite(error):raise ValueError('校准残差非有限。')
        grouped[row['group_id']]=max(grouped.get(row['group_id'],0),error)
    errors=sorted(grouped.values());rank=math.ceil((len(errors)+1)*(1-float(alpha))-1e-12)
    q=errors[rank-1] if 1<=rank<=len(errors) else None
    return {'alpha':float(alpha),'nominal_coverage':1-float(alpha),'calibration_groups':len(errors),
            'rank':rank,'residual_threshold':q,'finite':q is not None,
            'score':'每个独立工艺组的最大绝对残差',
            'scope':'校准组不参与模型/描述符选择；覆盖解释依赖校准组与未来组可交换。自适应选点、批次偏移或极端外推不继承覆盖保证。'}

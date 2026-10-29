"""Research-only, non-mutating diagnosis; explicit A/Ah schema, charge-positive output.

Not a universal importer. Never reconstruct missing current or unwrap a broken clock.
"""
import math
import statistics
from datetime import datetime

TIME_FACTORS=(1.0,0.001,60.0,3600.0)
MIN_INTERVALS=10

def _quantile(values,p):
    a=sorted(values)
    if not a:return None
    pos=(len(a)-1)*p;lo=int(pos);hi=min(lo+1,len(a)-1)
    return a[lo]+(a[hi]-a[lo])*(pos-lo)

def _stamp(value):
    if value is None or value=='':return None
    if isinstance(value,(int,float)):return float(value)
    for fmt in (None,'%m/%d/%Y %H:%M:%S'):
        try:
            # Use naive datetime differences as UTC, independent of host timezone.
            from datetime import timezone
            d=datetime.fromisoformat(value) if fmt is None else datetime.strptime(value,fmt)
            if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
            return d.timestamp()
        except ValueError:pass
    return None

def diagnose(records,evidence='joint'):
    """Records: t, i, optional qc/qd, stamp, step, direction (+1 charge/-1 discharge).

    qc/qd must be independent charge/discharge counters in Ah. Caller owns semantics.
    Evidence options joint/clock/charge are identical-interface ablations.
    """
    if evidence not in ('joint','clock','charge'):raise ValueError(evidence)
    clock=[];charge=[];directions=[];resets=[];anomalies=[];rollbacks=[]
    for k,r in enumerate(records):
        for name in ('t','i'):
            if not math.isfinite(r[name]):raise ValueError('nonfinite '+name)
        if r.get('direction') in (-1,1) and abs(r['i'])>1e-9:
            directions.append((k,r['i'],r['direction']))
        if k==0:continue
        a=records[k-1];dt=r['t']-a['t'];same=r.get('step')==a.get('step')
        if dt<=0:rollbacks.append(k)
        sa,sb=_stamp(a.get('stamp')),_stamp(r.get('stamp'))
        if sa is not None and sb is not None and sb>sa and dt>0:
            clock.append((k,dt/(sb-sa)))
        deltas=[];counter_ok=True
        for name in ('qc','qd'):
            x,y=a.get(name),r.get(name)
            if x is None or y is None:counter_ok=False;break
            if not math.isfinite(x) or not math.isfinite(y):counter_ok=False;break
            dq=y-x;deltas.append(dq)
            if dq < -1e-8:
                event={'row':k,'counter':name,'drop_Ah':dq}
                (resets if not same else anomalies).append(event);counter_ok=False
        if not counter_ok or not same or dt<=0:continue
        ia,ib=a['i'],r['i']
        if ia*ib<=0 or abs(ia-ib)>0.05*max(abs(ia),abs(ib)):continue
        dq=deltas[0]-deltas[1]
        if abs(dq)<=1e-8 or min(deltas)<-1e-8:continue
        # Reject simultaneous charge and discharge counters in a stable-sign interval.
        if min(deltas)>1e-8:anomalies.append({'row':k,'reason':'both_counters_increase'});continue
        predicted=(ia+ib)*0.5*dt/3600.0
        charge.append((k,predicted/dq))
    candidates=[]
    for factor in TIME_FACTORS:
        for sign in (1,-1):
            ce=[abs(math.log(ratio*factor)) for _,ratio in clock]
            qe=[abs(math.log(abs(ratio*factor))) for _,ratio in charge]
            agreement=sum(ratio*sign>0 for _,ratio in charge)/len(charge) if charge else None
            de=sum(i*sign*d>0 for _,i,d in directions)/len(directions) if directions else None
            clock_ok=len(ce)>=MIN_INTERVALS and statistics.median(ce)<=math.log(1.02) and _quantile(ce,.9)<=math.log(1.25)
            charge_ok=len(qe)>=MIN_INTERVALS and statistics.median(qe)<=math.log(1.05) and _quantile(qe,.9)<=math.log(1.25) and agreement>=.98
            direction_ok=de is None or de>=.98
            # Present but insufficient evidence does not silently become a veto;
            # present sufficient contradictory evidence does.
            if evidence=='clock':passed=clock_ok
            elif evidence=='charge':passed=charge_ok and direction_ok
            else:
                passed=(clock_ok or charge_ok) and direction_ok
                if len(ce)>=MIN_INTERVALS and not clock_ok:passed=False
                if len(qe)>=MIN_INTERVALS and not charge_ok:passed=False
            candidates.append(dict(time_factor=factor,current_sign=sign,passed=passed,
                clock_intervals=len(ce),charge_intervals=len(qe),
                clock_median_log_error=statistics.median(ce) if ce else None,
                charge_median_log_error=statistics.median(qe) if qe else None,
                charge_p90_log_error=_quantile(qe,.9),charge_sign_agreement=agreement,
                direction_agreement=de))
    passing=[c for c in candidates if c['passed']]
    scales=sorted(set(c['time_factor'] for c in passing))
    signs=sorted(set(c['current_sign'] for c in passing))
    # Clock-only never identifies current sign, even if incidental status is available.
    if evidence=='clock':signs=[-1,1] if passing else []
    unique=len(scales)==len(signs)==1
    accepted=unique and not rollbacks and not anomalies
    return dict(status='accepted' if accepted else 'ambiguous' if passing else 'conflict_or_insufficient',
        auto_applicable=accepted,proposed_time_factor=scales[0] if len(scales)==1 else None,
        proposed_current_sign=signs[0] if len(signs)==1 else None,
        current_convention='charge_positive_not_pybamm',time_rollbacks=rollbacks,
        counter_reset_events=resets,counter_anomalies=anomalies,
        counter_interpretation='boundary_resets_observed' if resets else 'reset_not_observed',
        candidates=candidates,interval_evidence=dict(clock=clock,charge=charge),
        scope='diagnosis_only_no_source_mutation_no_clock_unwrap_no_global_capacity_reconstruction')

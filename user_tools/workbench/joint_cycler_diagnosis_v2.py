"""Quantization-aware research diagnosis. Explicit error budgets, no source mutation.

Bounds are conditional on caller assumptions; export decimals are not calibration.
The integration bound assumes stable current between samples, not arbitrary CV data.
"""
import math
import statistics
from dataclasses import asdict, dataclass
from .joint_cycler_diagnosis import TIME_FACTORS, _stamp, _quantile

@dataclass(frozen=True)
class PrecisionBudget:
    current_abs_A: float
    charge_abs_Ah: float
    discharge_abs_Ah: float
    time_abs_raw: float
    current_relative: float
    basis: str

    def validate(self):
        for k,v in asdict(self).items():
            if k!='basis' and (not math.isfinite(v) or v<0):raise ValueError('invalid budget '+k)
        if not self.basis:raise ValueError('budget provenance required')

def _same_record(a,b):
    # If available, compare ALL original columns, not the reduced electrical schema.
    if 'source_signature' in a or 'source_signature' in b:
        return a.get('source_signature') is not None and a.get('source_signature')==b.get('source_signature')
    return a==b

def diagnose_v2(records,budget=None):
    if budget is None:
        return dict(status='precision_budget_required',auto_applicable=False,candidates=[],
                    proposed_time_factor=None,proposed_current_sign=None)
    budget.validate()
    clean=[];duplicates=[];rollbacks=[];anomalies=[];resets=[]
    for index,r in enumerate(records):
        if not all(math.isfinite(r[k]) for k in ('t','i')):raise ValueError('nonfinite time/current')
        if clean and _same_record(clean[-1][1],r):
            duplicates.append(index);continue
        if clean and r['t']<=clean[-1][1]['t']:rollbacks.append(index)
        clean.append((index,r))
    windows=[];clock=[];directions=[];run=[]
    qbound=2*(budget.charge_abs_Ah+budget.discharge_abs_Ah)

    def flush():
        nonlocal run
        if len(run)>=5:
            first,last=run[0][1],run[-1][1]
            pred=err=0.
            for (_,a),(_,b) in zip(run,run[1:]):
                dt=b['t']-a['t'];ia,ib=a['i'],b['i']
                ea=budget.current_abs_A+budget.current_relative*abs(ia)
                eb=budget.current_abs_A+budget.current_relative*abs(ib)
                pred+=(ia+ib)*.5*dt/3600
                err+=((ea+eb)*.5*dt+(abs(ia)+abs(ib)+ea+eb)*budget.time_abs_raw)/3600
            dq=(last['qc']-first['qc'])-(last['qd']-first['qd'])
            windows.append(dict(start_row=run[0][0],end_row=run[-1][0],intervals=len(run)-1,
                raw_integral_Ah=pred,raw_integral_error_Ah=err,counter_delta_Ah=dq,counter_error_Ah=qbound))
        run=[]

    for k,(idx,r) in enumerate(clean):
        unc=budget.current_abs_A+budget.current_relative*abs(r['i'])
        if r.get('direction') in (-1,1) and abs(r['i'])>unc:
            directions.append((r['i'],r['direction']))
        if k==0:continue
        ai,a=clean[k-1];dt=r['t']-a['t'];same=r.get('step')==a.get('step')
        sa,sb=_stamp(a.get('stamp')),_stamp(r.get('stamp'))
        if sa is not None and sb is not None and sb>sa and dt>0:clock.append(dt/(sb-sa))
        valid=True;deltas=[]
        for key,tol in (('qc',budget.charge_abs_Ah),('qd',budget.discharge_abs_Ah)):
            x,y=a.get(key),r.get(key)
            if x is None or y is None:valid=False;break
            if not math.isfinite(x) or not math.isfinite(y):
                anomalies.append(dict(row=idx,reason='nonfinite_counter',counter=key));valid=False;break
            d=y-x;deltas.append(d)
            if d < -2*tol-1e-12:
                (anomalies if same else resets).append(dict(row=idx,counter=key,drop_Ah=d));valid=False
        if valid and deltas[0]>2*budget.charge_abs_Ah+1e-12 and deltas[1]>2*budget.discharge_abs_Ah+1e-12:
            anomalies.append(dict(row=idx,reason='both_counters_increase'));valid=False
        stable=a['i']*r['i']>0 and abs(a['i']-r['i'])<=.05*max(abs(a['i']),abs(r['i']))
        if not(valid and same and dt>0 and stable):flush();continue
        if not run:run=[(ai,a)]
        run.append((idx,r))
        dq=(r['qc']-run[0][1]['qc'])-(r['qd']-run[0][1]['qd'])
        if len(run)-1>=2048 or (len(run)-1>=16 and abs(dq)>=8*qbound):
            flush()
    flush()
    candidates=[]
    for factor in TIME_FACTORS:
        clock_errors=[abs(math.log(r*factor)) for r in clock]
        clock_present=len(clock)>=10
        clock_ok=clock_present and statistics.median(clock_errors)<=math.log(1.02) and _quantile(clock_errors,.9)<=math.log(1.25)
        for sign in (1,-1):
            support=[];conflicts=[];uninformative=[]
            for j,w in enumerate(windows):
                p=sign*factor*w['raw_integral_Ah'];ep=factor*w['raw_integral_error_Ah']
                q=w['counter_delta_Ah'];eq=w['counter_error_Ah']
                overlap=abs(p-q)<=ep+eq+1e-12
                informative=abs(q)>2*eq+1e-12 or abs(p)>2*(eq+ep)+1e-12
                if informative:(support if overlap else conflicts).append(j)
                else:uninformative.append(j)
            charge_ok=len(support)>=3 and not conflicts
            agree=sum(i*sign*d>0 for i,d in directions)/len(directions) if directions else None
            direction_ok=len(directions)>=10 and agree>=.98
            direction_conflict=len(directions)>=10 and not direction_ok
            # Clock+known direction can identify standardization while charge remains
            # precision-limited; do not label that independent charge verification.
            passed=(charge_ok or (clock_ok and direction_ok)) and not conflicts and not direction_conflict
            if clock_present and not clock_ok:passed=False
            candidates.append(dict(time_factor=factor,current_sign=sign,passed=passed,
                clock_ok=clock_ok,clock_intervals=len(clock),clock_median_log_error=statistics.median(clock_errors) if clock_errors else None,
                charge_verified=charge_ok,support_windows=support,conflict_windows=conflicts,
                uninformative_windows=uninformative,direction_agreement=agree))
    passing=[x for x in candidates if x['passed']]
    factors=sorted({x['time_factor'] for x in passing});signs=sorted({x['current_sign'] for x in passing})
    accepted=len(factors)==len(signs)==1 and not rollbacks and not anomalies
    verified=accepted and passing[0]['charge_verified']
    return dict(status='accepted' if accepted else 'blocked' if rollbacks or anomalies else 'ambiguous' if passing else 'conflict_or_insufficient',
        auto_applicable=accepted,proposed_time_factor=factors[0] if len(factors)==1 else None,
        proposed_current_sign=signs[0] if len(signs)==1 else None,
        charge_status='verified_within_declared_bounds' if verified else 'precision_limited_or_unresolved',
        precision_budget=asdict(budget),removed_exact_duplicate_rows=duplicates,time_rollbacks=rollbacks,
        counter_reset_events=resets,counter_anomalies=anomalies,windows=windows,candidates=candidates,
        source_rows=len(records),analysis_rows=len(clean),current_convention='charge_positive_not_pybamm',
        scope='conditional_diagnosis_only_no_raw_mutation_no_time_unwrap_no_counter_unroll')

"""Decision guard. A small residual never suffices for material claims."""
from __future__ import annotations


def physical_decision(evidence, policy="credible"):
    if policy not in ('ordinary','credible'):
        raise ValueError('unknown policy')
    if policy=='ordinary':
        return {'action':'model_exploration','reasons':['comparison baseline: accepts a fitted value'],
                'material_claim_allowed':False}
    reasons=[]
    if evidence.get('evidence_type')!='public_identification': reasons.append('not a real experimental identification')
    if evidence.get('parameter_verdict')!='identifiable': reasons.append('parameter does not have an identifiable point estimate')
    if evidence.get('scale_aligned') is not True: reasons.append('capacity/geometry scale is not established')
    if evidence.get('geometry_measured') is not True: reasons.append('independent geometry measurement unavailable')
    if evidence.get('holdout_pass') is not True: reasons.append('frozen-parameter holdout has not passed')
    if evidence.get('model_consistency_pass') is not True: reasons.append('model mismatch not excluded by available protocol checks')
    if reasons:
        needs=[]
        if not evidence.get('geometry_measured'): needs.append('measure particle-size / electrode geometry independently')
        if not evidence.get('holdout_pass'): needs.append('evaluate a frozen model on an unused protocol')
        if evidence.get('parameter_verdict')!='identifiable': needs.append('select an informative GITT / rate protocol')
        return {'action':'supplement_experiment','reasons':reasons,'experiments':needs,'material_claim_allowed':False}
    return {'action':'validated_model_exploration','reasons':[],
            'material_claim_allowed':False,'note':'A numerical gate allows this model use in this declared scope, not intrinsic Ds or cross-material generalization.'}


def gate_ablation():
    cases=[
        {'case':'unidentifiable','evidence_type':'public_identification','parameter_verdict':'not identifiable','scale_aligned':True,'geometry_measured':True,'holdout_pass':True,'model_consistency_pass':True},
        {'case':'radius_unknown','evidence_type':'public_identification','parameter_verdict':'identifiable','scale_aligned':True,'geometry_measured':False,'holdout_pass':True,'model_consistency_pass':True},
        {'case':'mismatch_holdout','evidence_type':'public_identification','parameter_verdict':'identifiable','scale_aligned':True,'geometry_measured':True,'holdout_pass':False,'model_consistency_pass':False},
        {'case':'synthetic_recovery','evidence_type':'synthetic_recovery','parameter_verdict':'identifiable','scale_aligned':True,'geometry_measured':True,'holdout_pass':True,'model_consistency_pass':True},
    ]
    return {'evidence_type':'constructed_policy_cases','scope':'guard behavior, not optimization benefit',
            'rows':[{'case':c['case'],'ordinary':physical_decision(c,'ordinary')['action'],'credible':physical_decision(c)['action']} for c in cases]}

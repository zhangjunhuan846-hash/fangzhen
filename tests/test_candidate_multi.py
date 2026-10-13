import pytest
pytest.importorskip('numpy')
from user_tools.workbench.candidate_multi import hypervolume,recommend_multi


def records():
    return [{'candidate_id':'A','x1':0,'x2':0,'capacity':300,'ice':.90,'status':'completed'},
            {'candidate_id':'B','x1':1,'x2':0,'capacity':320,'ice':.89,'status':'completed'},
            {'candidate_id':'C','x1':0,'x2':1,'capacity':310,'ice':.93,'status':'completed'},
            {'candidate_id':'D','x1':.5,'x2':.5,'capacity':'','ice':'','status':'candidate'},
            {'candidate_id':'E','x1':1,'x2':1,'capacity':'','ice':'','status':'pending'}]


def test_exact_2d_hypervolume_union():
    assert hypervolume([[1,2],[2,1]],[0,0])==3
    assert hypervolume([[1,2],[2,1],[.5,.5]],[0,0])==3
    assert hypervolume([],[0,0])==0


def test_recommend_reproducible_excludes_pending_and_preserves_uncertainty():
    config={'records':records(),'noise':[5,.005],'reference':[0,0],'minimum':[0,.88],'mc_samples':64}
    r=recommend_multi(config)
    assert r['selected']['candidate_id']=='D' and len(r['ranking'])==1
    assert r['selected']['std_capacity']>0 and r['selected']['std_ice']>0
    assert r==recommend_multi(config)


def test_hidden_labels_and_duplicate_conditions_blocked():
    rows=records();rows[-1]['capacity']=350
    with pytest.raises(ValueError):recommend_multi({'records':rows})
    rows=records();rows[-1]['x1']=.5;rows[-1]['x2']=.5
    with pytest.raises(ValueError):recommend_multi({'records':rows})


def test_zero_estimated_improvement_does_not_force_recommendation():
    r=recommend_multi({'records':records(),'minimum':[1e6,.9],'mc_samples':64})
    assert r['selected'] is None and r['recommendation_status']=='no_estimated_improvement'

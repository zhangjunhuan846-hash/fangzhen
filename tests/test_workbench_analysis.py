import math
import pytest
from user_tools.workbench.analysis import pareto,tolerance,capability
from user_tools.workbench.server import Application


def test_pareto_tradeoffs_replicates_and_missing():
    rows=[{'sample_id':s,'cell_id':str(i),'c_rate':1,'cycle':5,'capacity':q,'ice':ice} for i,(s,q,ice) in enumerate([
        ('A',300,.95),('A',320,.95),('B',330,.9),('C',300,.9),('D',330,.9),('E',350,None)])]
    r=pareto({'半电池':rows},{'c_rate':1,'cycle':5})
    assert {c['sample_id'] for c in r['candidates'] if c['pareto']}=={'A','B','D'}
    assert r['candidates'][0]['n']==2
    assert r['candidates'][0]['means']['capacity']==310
    assert len(r['excluded'])==1
    filtered=pareto({'半电池':rows},{'c_rate':1,'cycle':5,'minimum':{'ice':.93}})
    assert filtered['front_count']==1


def fixed_config():
    return {'parameters':{k:{'mean':v,'distribution':'fixed'} for k,v in zip(
        ['mass_mg','area_cm2','thickness_um','active_fraction','active_density','other_density','q_ref'],[10,2,50,.9,2.2,1.8,330])},'count':100}


def test_density_capacity_and_invalid_samples():
    c=fixed_config();c['limits']={'capacity_mAh':[2.9,3]}
    r=tolerance(c)
    assert r['summary']['capacity_mAh']['mean']==pytest.approx(2.97)
    assert r['summary']['bulk_density_g_cm3']['mean']==1
    assert r['summary']['porosity']['mean']==pytest.approx(1-(.9/2.2+.1/1.8))
    assert r['compliance']['capacity_mAh']['among_valid']==1
    c['parameters']['mass_mg']={'mean':10,'spread':20,'distribution':'normal'}
    r=tolerance(c);assert r['invalid']>0 and r['valid']>0
    assert r==tolerance(c)


def test_covariance_changes_capacity_variability():
    c=fixed_config();c['count']=10000
    for k in ['mass_mg','thickness_um']:c['parameters'][k].update(distribution='normal',spread=c['parameters'][k]['mean']*.02)
    c['mass_thickness_correlation']=1
    correlated=tolerance(c)
    assert correlated['summary']['bulk_density_g_cm3']['std']<1e-12
    c['mass_thickness_correlation']=0
    assert tolerance(c)['summary']['bulk_density_g_cm3']['std']>.02


def test_capability_one_sided_overall_vs_within():
    r=capability({'values':[98,100,102],'lsl':90,'within_std':1,'within_source':'测试用独立子组估计'})
    assert r['cp'] is None and r['cpu'] is None
    assert r['index_estimate']==pytest.approx(10/6)
    assert r['within_indices']['cpk']==pytest.approx(10/3)
    assert r['status']=='exploratory'
    assert r['observed_out_of_spec']==0
    assert math.isfinite(r['normal_assumption_out_of_spec_fraction'])


def test_capability_rejects_degenerate_or_reversed_limits():
    with pytest.raises(ValueError):capability({'values':[1,1,1],'lsl':0})
    with pytest.raises(ValueError):capability({'values':[1,2,3],'lsl':4,'usl':3})


def test_pareto_blocks_mixed_temperature_and_duplicate_cells():
    base={'sample_id':'A','cell_id':'1','c_rate':1,'cycle':5,'capacity':310,'ice':.9,'temperature_C':25}
    with pytest.raises(ValueError):pareto({'半电池':[base,dict(base,cell_id='2',temperature_C=30)]},{'c_rate':1,'cycle':5})
    with pytest.raises(ValueError):pareto({'半电池':[base,base]},{'c_rate':1,'cycle':5})


def test_tolerance_blocks_all_invalid_and_unsupported_correlation():
    c=fixed_config();c['parameters']['thickness_um']['mean']=.1
    with pytest.raises(ValueError):tolerance(c)
    c=fixed_config();c['mass_thickness_correlation']=.5
    with pytest.raises(ValueError):tolerance(c)


def test_analysis_saved_with_revision_and_inputs(tmp_path):
    app=Application(tmp_path)
    workspace=app.store.list()[0]
    job=app.analyze({'workspace':workspace['id'],'config':{'kind':'capability','values':[1,2,3],'lsl':0}})
    assert app.store.job(job['id'])['result']['n']==3
    assert (tmp_path/'jobs'/job['id']/'analysis.json').is_file()
    assert app.store.get(workspace['id'])['revision']==job['workspace_revision']

import pytest
from user_tools.scalar_migration import to_scalar_tables
from user_tools.workbench.store import blank_tables,normalize_tables,Store


def test_legacy_observations_keep_independent_rows_and_units():
    t=blank_tables();t['表征']=[{'sample_id':'S1','metric':'碳含量','value':95,'unit':'%'},
                              {'sample_id':'S1','metric':'D50','value':12000,'unit':'nm'},
                              {'sample_id':'S1','metric':'特殊峰','value':3.2,'unit':'a.u.'}]
    r=to_scalar_tables(t)['表征']
    assert len(r)==3 and r[0]['carbon_fraction']==pytest.approx(.95) and r[1]['d50_um']==12
    assert '特殊峰' in r[2]['notes'] and '3.2' in r[2]['notes']
    assert 'd50_um' not in r[0]  # No invented measurement pairing.


def test_concentration_splits_numeric_value_and_unit():
    t=blank_tables();t['处理工艺']=[{'sample_id':'S1','concentration':'1.5 mol/L'}]
    r=to_scalar_tables(t)['处理工艺'][0]
    assert r['concentration']==1.5 and r['concentration_unit']=='mol/L'


def test_wide_scalar_store_does_not_drop_columns(tmp_path):
    s=Store(tmp_path/'db.sqlite');t=blank_tables();t['表征']=[{'sample_id':'S1','carbon_fraction':.95,'ni_mg_kg':40,'id_ig':.4,'d002_nm':.336,'notes':'real'}]
    w=s.create('wide',t)
    saved=s.get(w['id'])['tables']['表征'][0]
    assert saved['carbon_fraction']==.95 and saved['ni_mg_kg']==40 and saved['d002_nm']==.336


def test_legacy_restore_preserves_original_measurement_in_new_view(tmp_path):
    s=Store(tmp_path/'db.sqlite');t=blank_tables();t['表征']=[{'sample_id':'S1','metric':'Ni','value':.01,'unit':'%'}]
    w=s.create('legacy',t)
    assert s.get(w['id'])['tables']['表征'][0]['ni_mg_kg']==100


def test_true_density_has_independent_field_and_optional_model_inputs():
    t=blank_tables();t['表征']=[{'sample_id':'S','true_density_g_cm3':2.18,'tap_density_g_cm3':.9}]
    r,issues=normalize_tables(t)
    assert r['表征'][0]['true_density_g_cm3']==2.18
    assert r['表征'][0]['tap_density_g_cm3']==.9
    assert r['仿真输入']==[]

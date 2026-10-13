import base64
import copy
import json
import os
from pathlib import Path
import time
import pytest
from user_tools.workbench.sustainability import normalize_config, inventory_totals
from user_tools.workbench.server import Application


def config():
    return {'kind':'inventory','case_name':'synthetic','sample_id':'','output_kg':1,'currency':'CNY',
        'region':'synthetic','price_basis':'synthetic','boundary':'two synthetic consumptions',
        'data_kind':'synthetic_demo','batch_overhead':3,'overhead_source':'synthetic',
        'inventory':[{'name':'power','unit':'kWh','quantity':4,'unit_price':.8,'gwp_factor':.5,'source':'synthetic'},
                     {'name':'reagent','unit':'kg','quantity':.2,'unit_price':10,'gwp_factor':2,'source':'synthetic'}]}


def test_product_mass_normalization_and_overhead():
    c=config();r=inventory_totals(c)
    assert r['cost_per_kg_product']==pytest.approx(8.2)
    assert r['gwp_kg_co2e_per_kg_product']==pytest.approx(2.4)
    c['output_kg']=2;r=inventory_totals(c)
    assert r['cost_per_kg_product']==pytest.approx(4.1)
    assert r['gwp_kg_co2e_per_kg_product']==pytest.approx(1.2)


@pytest.mark.parametrize('key,value',[('output_kg',0),('output_kg',-1),('output_kg',True),
    ('output_kg',float('nan')),('currency','mixed'),('boundary',''),('price_basis',''),('data_kind','measured_validated')])
def test_missing_or_ambiguous_basis_rejected(key,value):
    c=config();c[key]=value
    with pytest.raises(ValueError):normalize_config(c)


@pytest.mark.parametrize('key,value',[('gwp_factor',None),('gwp_factor',-1),('quantity',float('inf')),
    ('unit','kJ'),('source',''),('unit_price',True)])
def test_inventory_units_sources_and_finite_numbers(key,value):
    c=config();c['inventory'][0][key]=value
    with pytest.raises(ValueError):normalize_config(c)


def test_explicit_zero_and_duplicate_names():
    c=config();c['inventory'][0]['gwp_factor']=0
    assert inventory_totals(c)['batch_gwp_kg_co2e']==pytest.approx(.4)
    c['inventory'].append(copy.deepcopy(c['inventory'][0]))
    with pytest.raises(ValueError,match='重复'):normalize_config(c)


def test_reference_requires_explicit_acceptance():
    with pytest.raises(ValueError):normalize_config({'kind':'everbatt','preset':'default'})
    with pytest.raises(ValueError):normalize_config({'kind':'everbatt','preset':'graphite','accept_reference':True})


def test_csv_preserves_quoted_sources_and_rejects_extra_columns(tmp_path):
    app=Application(tmp_path)
    raw=b'name,unit,quantity,unit_price,gwp_factor,source\npower,kWh,4,.8,.5,"quantity, price, factor"\n'
    p={'content':base64.b64encode(raw).decode()}
    assert app.inventory_preview(p)['inventory'][0]['source']=='quantity, price, factor'
    p['content']=base64.b64encode(raw.replace(b'power,kWh',b'extra,power,kWh')).decode()
    with pytest.raises(ValueError):app.inventory_preview(p)


def completed(app,job):
    deadline=time.monotonic()+45
    while time.monotonic()<deadline:
        result=app.store.job(job['id'])
        if result['status'] not in ['queued','running']:
            assert result['status']=='completed',result
            return result
        time.sleep(.1)
    raise AssertionError('Worker timed out')


def test_actual_workers_archive_snapshots_and_report(tmp_path):
    if os.name != 'nt':
        pytest.skip('This integration test launches the Windows sustainability runtime')
    project=Path(__file__).resolve().parents[1]
    if not (project/'data/runtime/sustainability/Scripts/python.exe').exists():
        pytest.skip('Independent local sustainability runtime not installed')
    app=Application(tmp_path,project);w=app.store.list()[0]
    c=config();c['case_name']='<script>synthetic</script>'
    job=completed(app,app.start_sustainability({'workspace':w['id'],'config':c}))
    assert job['result']['brightway_score']==pytest.approx(2.4,rel=1e-6)
    assert job['result']['cost_per_kg_product']==pytest.approx(8.2)
    assert job['workspace_revision']==w['revision']
    assert (tmp_path/'jobs'/job['id']/'workspace_snapshot.json').exists()
    assert (tmp_path/'jobs'/job['id']/'assessment/contributions.csv').exists()
    report=app.report(w['id']).decode()
    assert '&lt;script&gt;synthetic&lt;/script&gt;' in report and '<script>synthetic</script>' not in report
    reference=completed(app,app.start_sustainability({'workspace':w['id'],
        'config':{'kind':'everbatt','preset':'default','accept_reference':True}}))
    assert reference['result']['cost_per_kg_feedstock']==pytest.approx(5.08192735237198)
    assert reference['result']['functional_unit'].startswith('1 kg of reference feedstock')
    assert reference['result']['evidence_type']=='everbatt_reference_scenario'


def test_unknown_sample_and_missing_sources_do_not_create_jobs(tmp_path):
    app=Application(tmp_path);w=app.store.list()[0]
    c=config();c['sample_id']='unknown'
    with pytest.raises(ValueError,match='关联样品'):app.start_sustainability({'workspace':w['id'],'config':c})
    assert not app.store.jobs()

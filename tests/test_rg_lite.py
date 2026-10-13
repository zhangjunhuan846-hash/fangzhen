import json
from user_tools.rg_lite import SCHEMA,check_lite
from user_tools.rg_workstation import column


def grids():
    return {t['sheet']:{f'{column(i)}4':f[1] for i,f in enumerate(t['fields'],1)} for t in SCHEMA['tables']}


def test_lite_rejects_broken_sample_electrode_link(tmp_path):
    cells=grids();cells['原料'].update(A5='A')
    cells['处理工艺'].update(A5='A1',B5='A',A6='A2',B6='A')
    cells['极片'].update(A5='E1',B5='A1')
    cells['半电池'].update(A5='C1',B5='A2',C5='E1',D5=350,E5=315)
    source=tmp_path/'input.xlsx';source.write_bytes(b'preserved-source')
    assert check_lite(source,cells,tmp_path/'archive')==1
    manifest=json.loads(next((tmp_path/'archive').glob('*/manifest.json')).read_text(encoding='utf-8'))
    assert any('不一致' in i['message'] for i in manifest['issues'])


def test_lite_preserves_zero_capacity_and_derives_ice(tmp_path):
    cells=grids();cells['原料'].update(A5='A');cells['处理工艺'].update(A5='A1',B5='A')
    cells['极片'].update(A5='E1',B5='A1')
    cells['半电池'].update(A5='C1',B5='A1',C5='E1',D5=350,E5=0,H5=0)
    source=tmp_path/'input.xlsx';source.write_bytes(b'preserved-source')
    assert check_lite(source,cells,tmp_path/'archive')==0
    r=json.loads(next((tmp_path/'archive').glob('*/records.json')).read_text(encoding='utf-8'))['半电池'][0]
    assert r['ice']==0 and r['capacity']==0


def test_lite_has_no_review_or_time_fields():
    for t in SCHEMA['tables']:
        assert not any(any(w in f[1] for w in ['复核','日期','时间','记录人','审核']) for f in t['fields'])

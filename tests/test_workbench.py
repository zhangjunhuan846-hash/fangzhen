import base64
import json
from pathlib import Path
import threading
from http.server import ThreadingHTTPServer
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import pytest
from user_tools.workbench.store import Store,blank_tables,normalize_tables
from user_tools.workbench.server import Application,Handler,read_import


def test_revision_conflict_and_restore_are_non_destructive(tmp_path):
    s=Store(tmp_path/'db.sqlite');w=s.create('A');t=blank_tables();t['原料']=[{'batch_id':'A','mass_g':10}]
    saved=s.save(w['id'],1,t)
    with pytest.raises(ValueError,match='另一个窗口'):s.save(w['id'],1,blank_tables())
    restored=s.restore(w['id'],1,2)
    assert restored['revision']==3 and not restored['tables']['原料']
    assert s.revisions(w['id'])==[3,2,1]
    assert Store(tmp_path/'db.sqlite').get(w['id'])['revision']==3


def test_normalization_zero_percent_and_cross_sample_guard():
    t=blank_tables();t['原料']=[{'batch_id':'A'}]
    t['处理工艺']=[{'sample_id':'A1','batch_id':'A'},{'sample_id':'A2','batch_id':'A'}]
    t['极片']=[{'electrode_id':'E1','sample_id':'A1','graphite_fraction':'90%'}]
    t['半电池']=[{'cell_id':'C1','sample_id':'A2','electrode_id':'E1','first_lithiation':'350','first_delithiation':'0','capacity':'0'}]
    r,issues=normalize_tables(t)
    assert r['极片'][0]['graphite_fraction']==.9
    assert r['半电池'][0]['ice']==0 and r['半电池'][0]['capacity']==0
    assert any('不一致' in i['message'] for i in issues)


def test_import_reads_existing_lite_workbook_without_changes():
    p=Path(__file__).resolve().parents[1]/'outputs/rg_workstation_lite/回收石墨关键数据_简版.xlsx'
    if not p.exists():pytest.skip('local artifact not included')
    before=p.read_bytes();assert read_import(p)==blank_tables();assert p.read_bytes()==before


def test_curve_time_error_is_rejected_and_raw_curve_is_saved(tmp_path):
    a=Application(tmp_path);w=a.store.list()[0]
    bad=base64.b64encode(b'time_s,voltage_V\n1,1\n0,2\n').decode()
    with pytest.raises(ValueError,match='严格递增'):a.import_curve({'workspace':w['id'],'content':bad})
    raw=b'time_s,voltage_V\n0,1\n1,2\n'
    j=a.import_curve({'workspace':w['id'],'content':base64.b64encode(raw).decode()})
    assert (tmp_path/'jobs'/j['id']/'source.csv').read_bytes()==raw
    assert j['result']['evidence_type']=='user_uploaded_curve'


def test_api_requires_session_token_and_reports_real_conflict(tmp_path):
    app=Application(tmp_path);server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.app=app
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    url=f'http://127.0.0.1:{server.server_port}'
    try:
        with pytest.raises(HTTPError) as e:urlopen(url+'/api/bootstrap')
        assert e.value.code==403
        req=Request(url+'/api/solve',data=json.dumps({'known':{'area_cm2':1,'active_fraction':.9,'q_ref_mAh_g':330,'capacity_mAh':2},'bounds':{'total_loading_mg_cm2':[None,5]}}).encode(),headers={'X-Workbench-Token':app.token,'Content-Type':'application/json'})
        r=json.loads(urlopen(req).read())
        assert r['status']=='conflict' and r['values']['total_loading_mg_cm2']>6.7
    finally:server.shutdown();server.server_close()


def test_restart_marks_unfinished_jobs_interrupted(tmp_path):
    s=Store(tmp_path/'db.sqlite');s.put_job({'id':'unfinished','workspace':'x','status':'running'})
    assert Store(tmp_path/'db.sqlite').job('unfinished')['status']=='interrupted'

import json
import base64
import html
import io
import zipfile

import pytest

from user_tools.workbench.server import Application, SCHEMA, column
from user_tools.workbench.store import blank_tables


def test_context_recovers_saved_parent_without_crossing_projects(tmp_path):
    app = Application(tmp_path)
    first = app.store.list()[0]
    second = app.store.create('Independent project')
    app.store.put_job({'id': 'fit-a', 'workspace': first['id'], 'mode': 'identify', 'status': 'completed'})
    app.store.put_job({'id': 'fit-b', 'workspace': second['id'], 'mode': 'identify', 'status': 'completed'})
    job = {'id': 'prediction', 'workspace': first['id'], 'mode': 'predict',
           'workspace_revision': 1, 'status': 'completed'}
    app.store.put_job(job)
    folder = tmp_path / 'jobs' / job['id']
    folder.mkdir(parents=True)
    (folder / 'config.json').write_text(json.dumps({
        'fit_path': r'C:\archive\jobs\fit-a\physics\result.json',
        'feedback_parent': 'fit-b',
        'api_key': 'must-never-be-returned',
    }))
    (folder / 'workspace_snapshot.json').write_text('{}')
    context = app.job_context(job['id'])
    assert context['workspace'] == first['id']
    assert context['workspace_revision'] == 1
    assert context['snapshot_available']
    assert context['parents'] == [{'id': 'fit-a', 'title': 'identify'}]
    assert 'must-never-be-returned' not in json.dumps(context)


def test_legacy_context_reports_missing_snapshot_and_preserves_source_hash(tmp_path):
    app = Application(tmp_path)
    workspace = app.store.list()[0]
    app.store.put_job({'id': 'curve', 'workspace': workspace['id'], 'mode': 'preprocess',
                       'status': 'completed', 'result': {'filename': 'measurements.csv', 'source_sha256': 'a' * 64}})
    context = app.job_context('curve')
    assert not context['snapshot_available']
    assert context['workspace_revision'] is None
    assert context['parents'] == []
    assert {'label': '原始数据', 'sha256': 'a' * 64} in context['sources']
    assert {'label': 'measurements.csv'} in context['sources']


def input_workbook(tables):
    """A real, minimal spreadsheet fixture with the published import column names."""
    out = io.BytesIO()
    namespace = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    relations = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    sheets, links = [], []

    def cell(address, value):
        if value is None:
            return ''
        if isinstance(value, (int, float)):
            return f'<c r="{address}"><v>{value}</v></c>'
        return f'<c r="{address}" t="inlineStr"><is><t>{html.escape(str(value))}</t></is></c>'

    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as archive:
        for index, spec in enumerate(SCHEMA['tables'], 1):
            sheets.append(f'<sheet name="{spec["sheet"]}" sheetId="{index}" r:id="r{index}"/>')
            links.append(f'<Relationship Id="r{index}" Type="{relations}/worksheet" Target="worksheets/sheet{index}.xml"/>')
            rows = ['<row r="4">' + ''.join(cell(column(i)+'4', label) for i, (_, label, _) in enumerate(spec['fields'], 1)) + '</row>']
            for row_number, row in enumerate(tables[spec['sheet']], 5):
                rows.append(f'<row r="{row_number}">' + ''.join(cell(column(i)+str(row_number), row.get(key))
                            for i, (key, _, _) in enumerate(spec['fields'], 1)) + '</row>')
            archive.writestr(f'xl/worksheets/sheet{index}.xml', f'<worksheet xmlns="{namespace}"><sheetData>{"".join(rows)}</sheetData></worksheet>')
        archive.writestr('xl/workbook.xml', f'<workbook xmlns="{namespace}" xmlns:r="{relations}"><sheets>{"".join(sheets)}</sheets></workbook>')
        archive.writestr('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'+''.join(links)+'</Relationships>')
    return out.getvalue()


def test_excel_merge_keeps_project_identity_sources_and_restore_history(tmp_path):
    app = Application(tmp_path)
    workspace = app.store.list()[0]
    tables = blank_tables()
    tables['原料'] = [{'batch_id': 'A', 'mass_g': 10}]
    app.store.save(workspace['id'], 1, tables)
    tables['处理工艺'] = [{'sample_id': 'A1', 'batch_id': 'A'}]
    raw = input_workbook(tables)
    payload = {'workspace': workspace['id'], 'revision': 2, 'filename': 'experiment.xlsx',
               'content': base64.b64encode(raw).decode()}
    imported = app.import_into_workspace(payload)
    assert imported['id'] == workspace['id']
    assert imported['revision'] == 3
    assert imported['import_summary'] == {'added': 1, 'skipped': 1}
    assert len(app.store.list()) == 1
    assert not imported['issues']
    source = imported['source']['imports'][0]
    assert (tmp_path / source['file']).read_bytes() == raw
    assert source['name'] == 'experiment.xlsx'
    duplicate = app.import_into_workspace({**payload, 'revision': 3})
    assert duplicate['import_summary'] == {'added': 0, 'skipped': 2}
    assert len(duplicate['source']['imports']) == 1
    restored = app.store.restore(workspace['id'], 2, 4)
    assert restored['revision'] == 5
    assert restored['source'] is None
    assert restored['tables']['处理工艺'] == []
    assert app.store.get(workspace['id'])['tables']['原料'][0]['mass_g'] == 10


def test_excel_conflict_or_stale_revision_does_not_modify_existing_data(tmp_path):
    app = Application(tmp_path)
    workspace = app.store.list()[0]
    tables = blank_tables()
    tables['原料'] = [{'batch_id': 'A', 'mass_g': 10}]
    saved = app.store.save(workspace['id'], 1, tables)
    tables['原料'][0]['mass_g'] = 15
    payload = {'workspace': workspace['id'], 'revision': 2, 'filename': 'conflicting.xlsx',
               'content': base64.b64encode(input_workbook(tables)).decode()}
    with pytest.raises(ValueError, match='已存在且内容不同'):
        app.import_into_workspace(payload)
    assert app.store.get(workspace['id']) == saved
    with pytest.raises(ValueError, match='另一个窗口更新'):
        app.import_into_workspace({**payload, 'revision': 1})
    assert app.store.revisions(workspace['id']) == [2, 1]

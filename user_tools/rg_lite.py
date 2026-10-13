"""Essential data only: no review workflow, date fields or simulation controls."""
import csv
from datetime import datetime
import hashlib
import html
import json
import math
from pathlib import Path
from user_tools.excel_columns import column

SCHEMA=json.loads(Path(__file__).with_name('rg_lite_schema.json').read_text(encoding='utf-8'))


def is_lite(cells):
    return cells.get('原料',{}).get('A4')=='原料编号'


def finite(v):
    return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)


def check_lite(path,cells,out,open_report=False):
    from .scalar_migration import schema_for_cells,to_scalar_tables
    schema=schema_for_cells(cells,SCHEMA)
    records={};issues=[];indexes={}
    def issue(sheet,row,message):issues.append({'sheet':sheet,'row':row,'severity':'error','message':message})
    for spec in schema['tables']:
        name=spec['sheet'];grid=cells.get(name,{});records[name]=[];indexes[name]={}
        if name not in cells:issue(name,None,'缺少工作表');continue
        for i,(_,label,_) in enumerate(spec['fields'],1):
            if grid.get(f'{column(i)}4')!=label:issue(name,4,'列名不匹配：'+label)
        rows=sorted({int(a.lstrip('ABCDEFGHIJKLMNOPQRSTUVWXYZ')) for a in grid if int(a.lstrip('ABCDEFGHIJKLMNOPQRSTUVWXYZ'))>=5})
        for row in rows:
            r={'_row':row}
            for i,(key,label,typ) in enumerate(spec['fields'],1):
                if typ=='derived':continue
                v=grid.get(f'{column(i)}{row}')
                if v=='':v=None
                if isinstance(v,dict):issue(name,row,label+'请填写数据，不要填写公式');v=None
                r[key]=v
            if not any(v is not None for k,v in r.items() if k!='_row'):continue
            records[name].append(r)
            for key,label,typ in spec['fields']:
                v=r.get(key)
                if typ=='id':
                    if not isinstance(v,str) or not v.strip():issue(name,row,'缺少文本编号：'+label)
                    elif v in indexes[name]:issue(name,row,'编号重复：'+v)
                    else:indexes[name][v]=r
                elif v is not None and typ in ['number','positive','fraction','temperature','integer','signed']:
                    if not finite(v):issue(name,row,label+'必须是数值')
                    elif typ=='fraction' and not 0<=v<=1:issue(name,row,label+'请按百分数填写，如90%')
                    elif typ=='positive' and v<=0:issue(name,row,label+'必须大于零')
                    elif typ in ['number','integer'] and v<0:issue(name,row,label+'不能为负数')
                    elif typ=='integer' and v!=int(v):issue(name,row,label+'必须为整数')
    for spec in schema['tables']:
        name=spec['sheet']
        for r in records[name]:
            for key,label,typ in spec['fields']:
                if typ.startswith('ref:'):
                    v=r.get(key);target=typ[4:]
                    if v is None:issue(name,r['_row'],'缺少'+label)
                    elif not isinstance(v,str) or v not in indexes[target]:issue(name,r['_row'],label+'找不到对应记录')
            if name=='表征' and schema['version']=='lite-1' and not r.get('metric'):issue(name,r['_row'],'缺少表征指标')
            if name=='半电池':
                a,b=r.get('first_lithiation'),r.get('first_delithiation')
                r['ice']=b/a if finite(a) and a>0 and finite(b) else None
                if a==0:issue(name,r['_row'],'首次嵌锂为零，不能计算ICE')
                e=indexes['极片'].get(r.get('electrode_id'),{})
                if e and e.get('sample_id')!=r.get('sample_id'):issue(name,r['_row'],'极片与电芯的样品编号不一致')
    total=sum(map(len,records.values()));status='需修正' if issues else ('已归档' if total else '待录入')
    dest=Path(out)/datetime.now().strftime('%Y%m%d_%H%M%S_%f');dest.mkdir(parents=True,exist_ok=False)
    path=Path(path).resolve();raw=path.read_bytes();(dest/'source.xlsx').write_bytes(raw)
    records=to_scalar_tables(records)
    manifest={'schema_version':SCHEMA['version'],'status':status,'input_sha256':hashlib.sha256(raw).hexdigest(),
              'counts':{k:len(v) for k,v in records.items()},'issues':issues,'scope':'key data entry and basic validation; no physics executed'}
    (dest/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    (dest/'records.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    for spec in SCHEMA['tables']:
        with (dest/(spec['sheet']+'.csv')).open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=[x[0] for x in spec['fields']]+['_row']);writer.writeheader();writer.writerows(records[spec['sheet']])
    rows=''.join(f"<tr><td>{html.escape(i['sheet'])}</td><td>{i['row'] or ''}</td><td>{html.escape(i['message'])}</td></tr>" for i in issues)
    (dest/'report.html').write_text(f'<!doctype html><meta charset="utf-8"><title>数据归档</title><style>body{{font:16px/1.7 Arial;max-width:1000px;margin:40px auto}}td{{padding:8px;border-bottom:1px solid #ddd}}</style><h1>简版数据归档</h1><p>{status}；{total}条记录；{len(issues)}项问题。</p><table>{rows}</table><p>原始Excel未改写。未运行物理仿真。</p>',encoding='utf-8')
    report=str((dest/'report.html').resolve())
    if open_report:
        import webbrowser
        webbrowser.open(Path(report).as_uri())
    print(json.dumps({'status':status,'records':total,'errors':len(issues),'constraint_status':'简版录入','report':report},ensure_ascii=False))
    return int(bool(issues))

from __future__ import annotations
import copy
import json
import math
from pathlib import Path
import sqlite3
import uuid
from user_tools.rg_lite import SCHEMA
from user_tools.scalar_migration import to_scalar_tables


def blank_tables():return {t['sheet']:[] for t in SCHEMA['tables']}


def normalize_tables(tables):
    tables=to_scalar_tables(tables)
    if not isinstance(tables,dict) or set(tables)!=set(blank_tables()):raise ValueError('需要完整的关键数据及可选仿真输入表。')
    normalized=blank_tables();issues=[];indices={}
    for spec in SCHEMA['tables']:
        name=spec['sheet'];indices[name]={}
        if not isinstance(tables[name],list) or len(tables[name])>5000:raise ValueError('每张表最多5000行。')
        for n,raw in enumerate(tables[name],1):
            if not isinstance(raw,dict):raise ValueError('数据行必须为对象。')
            r={}
            for key,label,typ in spec['fields']:
                if typ=='derived':continue
                v=raw.get(key)
                if isinstance(v,str):v=v.strip() or None
                if v is not None and (isinstance(v,(dict,list,bool)) or not isinstance(v,(str,int,float))):raise ValueError('不支持的单元格类型。')
                if isinstance(v,float) and not math.isfinite(v):raise ValueError('不能保存非有限数字。')
                if v is not None and typ in ['number','positive','integer','fraction','temperature','signed']:
                    try:
                        if isinstance(v,str) and v.endswith('%') and typ=='fraction':v=float(v[:-1])/100
                        else:v=float(v)
                        if not math.isfinite(v):raise ValueError()
                    except (TypeError,ValueError):issues.append({'sheet':name,'row':n,'field':key,'message':label+'需要数值'})
                    else:
                        if typ=='fraction' and not 0<=v<=1:issues.append({'sheet':name,'row':n,'field':key,'message':label+'请填90%或0.9这样的比例'})
                        if typ=='positive' and v<=0:issues.append({'sheet':name,'row':n,'field':key,'message':label+'必须大于零'})
                        if typ in ['number','integer'] and v<0:issues.append({'sheet':name,'row':n,'field':key,'message':label+'不能为负数'})
                        if typ=='integer' and v!=int(v):issues.append({'sheet':name,'row':n,'field':key,'message':label+'必须是整数'})
                r[key]=v
            if not any(v is not None for v in r.values()):continue
            normalized[name].append(r)
            for key,label,typ in spec['fields']:
                if typ=='id':
                    v=r.get(key)
                    if not isinstance(v,str) or not v:issues.append({'sheet':name,'row':n,'field':key,'message':'请填写文本'+label})
                    elif v in indices[name]:issues.append({'sheet':name,'row':n,'field':key,'message':label+'重复'})
                    else:indices[name][v]=r
    for spec in SCHEMA['tables']:
        name=spec['sheet']
        for n,r in enumerate(normalized[name],1):
            for key,label,typ in spec['fields']:
                if typ.startswith('ref:') and r.get(key) is not None and (not isinstance(r[key],str) or r[key] not in indices[typ[4:]]):
                    issues.append({'sheet':name,'row':n,'field':key,'message':label+'尚无对应记录'})
            if name=='半电池':
                a,b=r.get('first_lithiation'),r.get('first_delithiation')
                r['ice']=b/a if isinstance(a,(int,float)) and a>0 and isinstance(b,(int,float)) else None
                if a==0:issues.append({'sheet':name,'row':n,'field':'first_lithiation','message':'首次嵌锂为零，ICE无法计算'})
                e=indices['极片'].get(r.get('electrode_id'),{})
                if e and e.get('sample_id')!=r.get('sample_id'):issues.append({'sheet':name,'row':n,'field':'electrode_id','message':'电芯和极片的样品编号不一致'})
    return normalized,issues


class Store:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS workspaces(id TEXT PRIMARY KEY,name TEXT NOT NULL,revision INTEGER NOT NULL,body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS versions(workspace TEXT,revision INTEGER,body TEXT,PRIMARY KEY(workspace,revision));
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,workspace TEXT,body TEXT NOT NULL);''')
            c.execute("UPDATE jobs SET body=json_set(body,'$.status','interrupted','$.error','程序已重启，请重新运行任务') WHERE json_extract(body,'$.status') IN ('running','queued')")

    def connect(self):return sqlite3.connect(self.path,timeout=15)

    def list(self):
        with self.connect() as c:return [{'id':i,'name':n,'revision':r} for i,n,r in c.execute('SELECT id,name,revision FROM workspaces ORDER BY rowid DESC')]

    def get(self,ident):
        with self.connect() as c:row=c.execute('SELECT body FROM workspaces WHERE id=?',(ident,)).fetchone()
        if not row:raise KeyError('方案不存在。')
        body=json.loads(row[0]);body['tables']=to_scalar_tables(body['tables']);return body

    def create(self,name,tables=None,source=None):
        name=str(name).strip()[:80]
        if not name:raise ValueError('请输入方案名称。')
        normalized,issues=normalize_tables(tables or blank_tables())
        body={'id':uuid.uuid4().hex,'name':name,'revision':1,'tables':normalized,'issues':issues,'source':source}
        text=json.dumps(body,ensure_ascii=False,allow_nan=False)
        with self.connect() as c:
            c.execute('INSERT INTO workspaces VALUES(?,?,?,?)',(body['id'],name,1,text))
            c.execute('INSERT INTO versions VALUES(?,?,?)',(body['id'],1,text))
        return body

    def save(self,ident,revision,tables,name=None):
        normalized,issues=normalize_tables(tables)
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT body FROM workspaces WHERE id=?',(ident,)).fetchone()
            if not row:raise KeyError('方案不存在。')
            body=json.loads(row[0])
            if body['revision']!=revision:raise ValueError('另一个窗口已修改此方案，请先重新加载。当前输入仍在浏览器中。')
            body.update(tables=normalized,issues=issues,revision=revision+1)
            if name:body['name']=str(name).strip()[:80]
            text=json.dumps(body,ensure_ascii=False,allow_nan=False)
            c.execute('UPDATE workspaces SET name=?,revision=?,body=? WHERE id=?',(body['name'],body['revision'],text,ident))
            c.execute('INSERT INTO versions VALUES(?,?,?)',(ident,body['revision'],text))
        return body

    def revisions(self,ident):
        with self.connect() as c:return [r[0] for r in c.execute('SELECT revision FROM versions WHERE workspace=? ORDER BY revision DESC LIMIT 50',(ident,))]

    def restore(self,ident,revision,current):
        with self.connect() as c:r=c.execute('SELECT body FROM versions WHERE workspace=? AND revision=?',(ident,revision)).fetchone()
        if not r:raise KeyError('版本不存在。')
        old=json.loads(r[0]);return self.save(ident,current,old['tables'],old['name'])

    def put_job(self,job):
        with self.connect() as c:c.execute('INSERT OR REPLACE INTO jobs VALUES(?,?,?)',(job['id'],job.get('workspace'),json.dumps(job,ensure_ascii=False,allow_nan=False)))

    def jobs(self):
        with self.connect() as c:return [json.loads(r[0]) for r in c.execute('SELECT body FROM jobs ORDER BY rowid DESC')]

    def job(self,ident):
        with self.connect() as c:r=c.execute('SELECT body FROM jobs WHERE id=?',(ident,)).fetchone()
        if not r:raise KeyError('任务不存在。')
        return json.loads(r[0])

"""Versioned planned experiments and actual feedback; predictions never become labels."""
import copy
import json
import sqlite3
import uuid
from user_tools.workbench.ml_data import number

class ExperimentLedger:
    def __init__(self,path):
        self.path=path
        with self.connect() as c:
            c.executescript('CREATE TABLE IF NOT EXISTS experiments(id TEXT PRIMARY KEY,workspace TEXT,campaign TEXT,record_id TEXT,revision INTEGER,body TEXT,UNIQUE(workspace,campaign,record_id));'
                           'CREATE TABLE IF NOT EXISTS experiment_events(experiment TEXT,revision INTEGER,body TEXT,PRIMARY KEY(experiment,revision));')
    def connect(self):return sqlite3.connect(self.path,timeout=20)
    def list(self,workspace,campaign=None):
        with self.connect() as c:
            query='SELECT body FROM experiments WHERE workspace=?';args=[workspace]
            if campaign:query+=' AND campaign=?';args.append(campaign)
            return [json.loads(r[0]) for r in c.execute(query,args)]
    def get(self,ident):
        with self.connect() as c:r=c.execute('SELECT body FROM experiments WHERE id=?',(ident,)).fetchone()
        if not r:raise KeyError('实验记录不存在。')
        return json.loads(r[0])
    def plan(self,workspace,campaign,parent,record,objectives,repeat=False):
        record=copy.deepcopy(record)
        origin=record['record_id']
        if repeat:record['record_id']=origin+'__rep_'+uuid.uuid4().hex[:6];record['replicate_of']=origin
        for o in objectives:
            if not o.get('known') and (repeat or record.get('status')=='candidate'):record[o['key']]=None
        record['status']='pending'
        record['_sampling']='adaptive_feedback'
        body={'id':uuid.uuid4().hex,'workspace':workspace,'campaign':campaign,'parent_job':parent,
              'record_id':record['record_id'],'revision':1,'status':'pending','record':record,
              'objectives':objectives,'notes':'','scope':'待实验记录，目标来自实际反馈；不复制预测值作为测量'}
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            existing=c.execute('SELECT body FROM experiments WHERE workspace=? AND campaign=? AND record_id=?',(workspace,campaign,record['record_id'])).fetchone()
            if existing:return json.loads(existing[0])
            text=json.dumps(body,ensure_ascii=False,allow_nan=False)
            c.execute('INSERT INTO experiments VALUES(?,?,?,?,?,?)',(body['id'],workspace,campaign,record['record_id'],1,text))
            c.execute('INSERT INTO experiment_events VALUES(?,?,?)',(body['id'],1,text))
        return body
    def feedback(self,ident,revision,values,status='measured',notes='',provenance=None):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE');raw=c.execute('SELECT body FROM experiments WHERE id=?',(ident,)).fetchone()
            if not raw:raise KeyError('实验不存在。')
            body=json.loads(raw[0])
            if body['revision']!=revision:raise ValueError('实验记录已更新，请重新读取后提交。')
            allowed={o['key']:o for o in body['objectives']}
            if any(k not in allowed for k in values):raise ValueError('反馈只能填写已定义目标。')
            if status not in ['measured','failed_measurement','failed_preparation']:raise ValueError('未知反馈状态。')
            for key,value in values.items():
                if value in (None,''):continue
                v=number(value)
                if v is None:raise ValueError('实验反馈必须为有限数值。')
                if allowed[key].get('unit')=='fraction' and not 0<=v<=1:raise ValueError('比例反馈需0–1。')
                body['record'][key]=v
            if status!='measured':
                for o in body['objectives']:
                    if not o.get('known'):body['record'][o['key']]=None
                body['status']=status
            else:body['status']='completed' if all(number(body['record'].get(k)) is not None for k in allowed) else 'partial'
            body['record']['status']=body['status'];body['notes']=str(notes)[:1000];body['revision']+=1
            if provenance:
                body['inventory_provenance']=provenance
                body['record']['_inventory_job']=provenance['job']
                body['record']['_inventory_sha256']=provenance['inventory_sha256']
                for key,value in provenance['context'].items():body['record']['_inventory_'+key]=value
            text=json.dumps(body,ensure_ascii=False,allow_nan=False)
            c.execute('UPDATE experiments SET revision=?,body=? WHERE id=?',(body['revision'],text,ident))
            c.execute('INSERT INTO experiment_events VALUES(?,?,?)',(ident,body['revision'],text))
        return body
    def merge(self,workspace,campaign,rows):
        indexed={r['record_id']:copy.deepcopy(r) for r in rows}
        for body in self.list(workspace,campaign):indexed[body['record_id']]=copy.deepcopy(body['record'])
        return list(indexed.values())

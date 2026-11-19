from __future__ import annotations
import argparse
import base64
import csv
import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import io
import json
import math
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
from urllib.parse import urlsplit,parse_qs
import uuid
import webbrowser
import zipfile
import html
from user_tools.rg_lite import SCHEMA,is_lite
from user_tools.rg_workstation import read_xlsx,column,solve_constraints
from user_tools.workbench.store import Store,blank_tables
from user_tools.scalar_migration import schema_for_cells,to_scalar_tables
from user_tools.workbench.analysis import run_analysis
from user_tools.workbench.preprocess import normalize_csv,save_normalized
from user_tools.workbench.paper_methods import read_eis,split_conformal
from user_tools.workbench.sustainability import normalize_config
from user_tools.workbench.ml_data import workspace_dataset,csv_dataset,validate_selection,catalog as ml_catalog,targets as ml_targets
from user_tools.workbench.research_data import parse_campaign
from user_tools.workbench.experiment_ledger import ExperimentLedger
from user_tools.workbench.agent_api_settings import public_settings, save_settings, probe_settings

APP_VERSION='0.3.25'


def resource_dir():
    return Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[2]))/'user_tools'/'workbench'


def project_dir():
    start=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[2]
    for p in [start,*start.parents]:
        if (p/'user_tools/rg_loop/physics.py').exists():return p
    return None


def wsl_path(p):
    s=str(Path(p).resolve()).replace('\\','/')
    if len(s)<3 or s[1:3]!=':/':raise ValueError('本机仿真需Windows盘符路径。')
    return '/mnt/'+s[0].lower()+'/'+s[3:]


def read_import(path):
    with zipfile.ZipFile(path) as z:
        if sum(e.file_size for e in z.infolist())>150_000_000:raise ValueError('工作簿解压后超过150MB。')
    cells=read_xlsx(path)
    if not is_lite(cells):raise ValueError('本版支持关键数据模板（含旧版5张表）；其他Excel需要字段映射，原文件未修改。')
    tables=blank_tables()
    schema=schema_for_cells(cells,SCHEMA)
    for spec in schema['tables']:
        grid=cells.get(spec['sheet'])
        if grid is None:raise ValueError('缺少工作表：'+spec['sheet'])
        for i,f in enumerate(spec['fields'],1):
            if grid.get(f'{column(i)}4')!=f[1]:raise ValueError('列名不匹配：'+f[1])
        for n in sorted({int(a.lstrip('ABCDEFGHIJKLMNOPQRSTUVWXYZ')) for a in grid if int(a.lstrip('ABCDEFGHIJKLMNOPQRSTUVWXYZ'))>=5}):
            row={}
            for i,(key,label,typ) in enumerate(spec['fields'],1):
                if typ=='derived':continue
                v=grid.get(f'{column(i)}{n}')
                if isinstance(v,dict):raise ValueError(f'{spec["sheet"]}第{n}行的输入包含公式；请使用数据值。')
                row[key]=v
            if any(v not in (None,'') for v in row.values()):tables[spec['sheet']].append(row)
    return to_scalar_tables(tables)


class Application:
    def __init__(self,data,project=None):
        self.data=Path(data).resolve();self.data.mkdir(parents=True,exist_ok=True)
        self.store=Store(self.data/'workbench.sqlite');self.project=Path(project).resolve() if project else project_dir()
        self.token=secrets.token_urlsafe(32);self.physics_lock=threading.Lock();self.sustainability_lock=threading.Lock()
        self.experiments=ExperimentLedger(self.store.path)
        if not self.store.list():self.store.create('我的回收石墨研究')

    def node_runtime(self):
        runtime=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node'
        node=runtime/'bin/node.exe';module=runtime/'node_modules/@oai/artifact-tool/dist/artifact_tool.mjs'
        if not node.is_file() or not module.is_file():raise ValueError('未找到Excel导出运行时。可先导出JSON备份，数据仍在本地。')
        return node,module

    def export(self,ident):
        body=self.store.get(ident);folder=self.data/'exports'/uuid.uuid4().hex;folder.mkdir(parents=True)
        (folder/'data.json').write_text(json.dumps({'schema':SCHEMA,'workspace':body},ensure_ascii=False),encoding='utf-8')
        node,module=self.node_runtime();dest=folder/'关键数据.xlsx'
        p=subprocess.run([str(node),str(resource_dir()/'export.mjs'),str(module),str(folder/'data.json'),str(dest)],
                         capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=90)
        if p.returncode or not dest.exists():raise RuntimeError('Excel导出失败：'+p.stderr.decode('utf-8',errors='replace')[-500:])
        return dest

    def start_job(self,payload):
        modes={'sodium_dfn','engineering','battery_agent','forward','chen_baseline','graphite_baseline','identify','predict','public_replay','sample_forward','candidate_multi','eis_forward','eis_fit','parquet_preprocess','ml_train','ml_predict','ml_recommend','research_multi','research_chain','public_ml_validation'}
        mode=payload.get('mode');model=payload.get('model','SPM')
        if mode not in modes or model not in ['SPM','SPMe','DFN']:raise ValueError('未支持的仿真类型或模型。')
        if not self.project or not (self.project/'user_tools/workbench/physics_worker.py').exists():raise ValueError('未找到原项目，物理仿真需本机项目与WSL环境。')
        workspace=self.store.get(payload['workspace'])
        config={'mode':mode,'model':model}
        engineering_raw=None
        if mode=='engineering':
            from user_tools.workbench.engineering_contracts import normalize as normalize_engineering
            from user_tools.workbench.engineering_service import runtime_for, bridge_eis, bridge_eis_grid, bridge_can
            engineering_raw=base64.b64decode(payload['content'],validate=True) if payload.get('content') else None
            request=payload.get('engineering_config',{})
            if request.get('filter_rc_mode') in ('estimated_grid','estimated_grid_jacobian') and not payload.get('eis_grid_parent'):
                raise ValueError('estimated_grid滤波器需要选择本方案已通过筛查的EIS网格任务。')
            if request.get('eis_grid_source') and not payload.get('eis_grid_parent'):raise ValueError('参数表来源必须由已完成的EIS任务建立。')
            if request.get('adaptive_parameter_source') and not payload.get('adaptive_parent'):raise ValueError('请从本方案已完成的更新任务创建参数来源，不接受手填验证标记。')
            if payload.get('adaptive_parent'):
                if engineering_raw is not None or payload.get('eis_parent'):raise ValueError('更新参数MPC不能同时选择CSV或EIS单谱桥接。')
                from user_tools.workbench.engineering_service import bridge_adaptive_control
                parent=self.store.job(payload['adaptive_parent'])
                if parent['workspace']!=workspace['id'] or parent['status']!='completed' or parent['mode']!='engineering' or parent.get('result',{}).get('action')!='commercial_adaptive':
                    raise ValueError('更新参数来源必须是本方案已完成的工程任务。')
                folder=self.data/'jobs'/parent['id']/'physics'
                artifact=(folder/'adaptive_frozen_model.json').read_bytes()
                control_bytes=(folder/'adaptive_control_config.json').read_bytes()
                if hashlib.sha256(control_bytes).hexdigest()!=parent['result'].get('control_config_sha256'):raise ValueError('更新参数MPC配置文件校验不符。')
                exported=json.loads(control_bytes.decode('utf-8'))
                request=bridge_adaptive_control(request,parent['result'],parent['id'],artifact,exported)
            if payload.get('eis_parent'):
                if payload.get('eis_grid_parent'):raise ValueError('单谱和多工况参数表只能选择一项。')
                parent=self.store.job(payload['eis_parent'])
                if parent['workspace']!=workspace['id'] or parent['status']!='completed' or parent['mode']!='eis_fit':
                    raise ValueError('EIS参数来源必须是本方案已完成的RC拟合。')
                artifact=(self.data/'jobs'/parent['id']/'physics/result.json').read_bytes()
                request=bridge_eis(request,parent['result'],parent['id'],artifact)
            if payload.get('eis_grid_parent'):
                if payload.get('adaptive_parent'):raise ValueError('EIS表不能与更新参数来源同时使用。')
                parent=self.store.job(payload['eis_grid_parent'])
                if parent['workspace']!=workspace['id'] or parent['status']!='completed' or parent['mode']!='engineering' or parent.get('result',{}).get('action')!='eis_grid':
                    raise ValueError('参数表来源必须为本方案已完成的多工况EIS任务。')
                artifact=(self.data/'jobs'/parent['id']/'physics/rc_grid.json').read_bytes()
                request=bridge_eis_grid(request,parent['result'],parent['id'],artifact)
            if payload.get('telemetry_parent'):
                if engineering_raw is not None:raise ValueError('CSV日志和遥测父任务只能选择一项。')
                parent=self.store.job(payload['telemetry_parent'])
                if parent['workspace']!=workspace['id'] or parent['status']!='completed' or parent['mode']!='engineering':
                    raise ValueError('CAN遥测来源必须是本方案已完成的工程任务。')
                artifact=(self.data/'jobs'/parent['id']/'physics/result.json').read_bytes()
                with (self.data/'jobs'/parent['id']/'physics/engineering.csv').open(encoding='utf-8-sig',newline='') as stream:
                    samples=list(csv.DictReader(stream))
                request=bridge_can(request,parent['result'],parent['id'],artifact,samples)
            request=normalize_engineering(request,engineering_raw)
            runtime_for(self.project,request['action'])
            config['engineering_config']=request
        if mode=='eis_fit':
            from user_tools.workbench.eis_fit import prepare_eis_fit
            raw=base64.b64decode(payload['content'],validate=True)
            if len(raw)>4_000_000:raise ValueError('EIS CSV最多4MB。')
            eis_config=payload.get('eis_config',{})
            packet=prepare_eis_fit(raw,eis_config)
            config.update(eis_config=eis_config,source_sha256=packet['source_sha256'])
        if mode=='battery_agent':
            from user_tools.workbench.battery_agent import normalize as normalize_agent
            config['agent_config']=normalize_agent(payload.get('agent_config',{}))
            if config['agent_config']['strategy']=='llm' and not public_settings(self.project)['configured']:
                raise ValueError('请先在仿真页面保存模型API地址、端口和模型名。')
        if mode=='research_multi':
            if payload.get('feedback_parent'):
                parent=self.store.job(payload['feedback_parent'])
                if parent['mode']!='research_multi' or parent['status']!='completed' or parent['workspace']!=workspace['id']:raise ValueError('请选择本方案已完成的多目标任务。')
                prior=json.loads((self.data/'jobs'/parent['id']/'config.json').read_text(encoding='utf-8'))
                research_config=prior['research_config'];campaign=prior['campaign_id']
                if 'allow_exploration' in payload:
                    if not isinstance(payload['allow_exploration'],bool):raise ValueError('探索开关需要布尔值。')
                    research_config={**research_config,'allow_exploration':payload['allow_exploration']}
                records=self.experiments.merge(workspace['id'],campaign,prior['dataset']['rows'])
                text=io.StringIO();writer=csv.DictWriter(text,fieldnames=list(dict.fromkeys(k for r in records for k in r)))
                writer.writeheader();writer.writerows(records);raw=text.getvalue().encode('utf-8')
                config.update(campaign_id=campaign,feedback_parent=parent['id'])
            else:
                raw=base64.b64decode(payload['content'],validate=True);research_config=payload.get('research_config',{})
            config.update(dataset=parse_campaign(raw,research_config),research_config=research_config)
        if mode=='research_chain':
            raw=base64.b64decode(payload['content'],validate=True);chain_config=payload.get('chain_config',{})
            dataset=csv_dataset(raw,chain_config)
            original=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
            predictions=[r for r in original if r.get(chain_config.get('target')) in (None,'')]
            if len(predictions)>200:raise ValueError('级联最多200个未测候选。')
            config.update(dataset=dataset,chain_config=chain_config,prediction_rows=predictions)
        if mode=='public_ml_validation':config.update(seeds=int(payload.get('seeds',20)),budget=int(payload.get('budget',12)))
        if mode=='ml_train':
            mlconfig=payload.get('ml_config',{})
            if payload.get('content'):
                raw=base64.b64decode(payload['content'],validate=True)
                dataset=csv_dataset(raw,mlconfig)
            else:dataset=workspace_dataset(workspace['tables'],mlconfig)
            validate_selection(dataset,mlconfig)
            config.update(dataset=dataset,ml_config=mlconfig)
        if mode in ['ml_predict','ml_recommend']:
            parent=self.store.job(payload.get('parent',''))
            if parent['mode']!='ml_train' or parent['status']!='completed' or parent['workspace']!=workspace['id']:
                raise ValueError('请选择同方案已完成的描述符建模任务。')
            raw=base64.b64decode(payload['content'],validate=True)
            if len(raw)>1_000_000:raise ValueError('预测CSV最多1MB。')
            rows=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
            config.update(prediction_rows=rows,model_path=wsl_path(self.data/'jobs'/parent['id']/'physics/model.joblib'),
                          direction=payload.get('direction','maximize'),parent=parent['id'],expected_model_sha256=parent['result'].get('model_sha256'))
            if config['direction'] not in ['maximize','minimize']:raise ValueError('未知优化方向。')
        if mode=='eis_forward':
            config.update(parameter_set=payload.get('parameter_set','Chen2020'),socs=payload.get('socs',[.2,.5,.8]),
                          frequency_min_Hz=payload.get('frequency_min_Hz',.01),frequency_max_Hz=payload.get('frequency_max_Hz',10000),
                          frequency_points=payload.get('frequency_points',25),negative_double_layer_F_m2=payload.get('negative_double_layer_F_m2',.2),
                          positive_double_layer_F_m2=payload.get('positive_double_layer_F_m2',.2))
        if mode=='parquet_preprocess':
            raw=base64.b64decode(payload['content'],validate=True)
            if len(raw)>20_000_000 or not raw.startswith(b'PAR1'):raise ValueError('只接受≤20MB的Parquet文件。')
            overrides=payload.get('config',{})
            if any(overrides.get(k+'_column') or overrides.get(k+'_unit','auto') not in ['auto',''] for k in ['time','voltage','current']):
                raise ValueError('Parquet当前只接受已明示s/V/A的标准列，不应用CSV手动列名/单位覆盖。')
        if mode=='candidate_multi':
            raw=base64.b64decode(payload['content'],validate=True)
            if len(raw)>1_000_000:raise ValueError('候选表超过1MB。')
            records=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
            if not 4<=len(records)<=500:raise ValueError('候选表需要4–500行。')
            if not {'candidate_id','x1','x2','capacity','ice','status'}<=set(records[0]):raise ValueError('候选CSV缺少规定列名。')
            if payload.get('same_batch') is not True:raise ValueError('请确认候选来自同一材料批次、同一测试协议。')
            config.update(records=records,noise=payload.get('noise'),reference=payload.get('reference'),minimum=payload.get('minimum'),seed=42,engine=payload.get('engine','ehvi'))
        if mode=='sample_forward':
            from user_tools.workbench.sample import build_sample
            if model!='SPM':raise ValueError('自有参数半电池目前仅支持SPM。')
            if payload.get('accept_reference') is not True:raise ValueError('请明确接受参考辅助参数和Ds/i0常数近似。')
            packet=build_sample(workspace['tables'],payload.get('sample_config',{}))
            if not packet['candidate_complete']:raise ValueError('缺失参数或存在冲突：'+', '.join(packet['missing']+packet['conflicts']))
            ocp=self.store.job(packet['ocp_job_id'])
            if ocp['workspace']!=workspace['id'] or ocp['mode']!='ocp_table':raise ValueError('OCP表必须来自本方案。')
            if not ocp['result']['x_min']<packet['parameters']['initial_x0']['value']<ocp['result']['x_max']:raise ValueError('初始锂化度不在OCP表内部。')
            config.update(sample_packet=packet,ocp_path=wsl_path(self.data/'jobs'/ocp['id']/'ocp.csv'),duration_s=float(payload.get('duration_s',3600)))
            if not 1<=config['duration_s']<=20000:raise ValueError('仿真时长需为1–20000秒。')
        if mode=='forward':
            for key,default,lo,hi in [('c_rate',1,.01,5),('initial_soc',.9,.01,.99),('temperature_C',25,0,50)]:
                v=float(payload.get(key,default))
                if not math.isfinite(v) or not lo<=v<=hi:raise ValueError(key+'超出允许范围。')
                config[key]=v
        if mode=='sodium_dfn':
            for key,default,lo,hi in [('c_rate',1,.05,3),('duration_s',60,1,3600),('temperature_C',25,10,40)]:
                v=float(payload.get(key,default))
                if not math.isfinite(v) or not lo<=v<=hi:raise ValueError(key+'超出钠电参考模型范围。')
                config[key]=v
            policy=payload.get('extrapolation_policy','stop_before_bound')
            if policy not in ('stop_before_bound','error'):raise ValueError('未知参数外推处理策略。')
            config['extrapolation_policy']=policy
            config['model']='DFN';model='DFN'
        if mode=='predict':
            parent=self.store.job(payload.get('parent',''))
            if parent['mode']!='identify' or parent['status']!='completed' or parent['workspace']!=workspace['id']:raise ValueError('需选择同一方案已完成的参数辨识任务。')
            model=parent['model'];config['model']=model
            config['fit_path']=wsl_path(self.data/'jobs'/parent['id']/'physics/result.json')
        ident=uuid.uuid4().hex;folder=self.data/'jobs'/ident;folder.mkdir(parents=True)
        if mode=='research_multi':config.setdefault('campaign_id',ident)
        if mode=='candidate_multi':(folder/'source_candidates.csv').write_bytes(raw)
        if mode=='eis_fit':
            (folder/'source.csv').write_bytes(raw);config['source_path']=wsl_path(folder/'source.csv')
        if mode=='engineering' and engineering_raw is not None:
            (folder/'source.csv').write_bytes(engineering_raw)
            config.update(source_path=wsl_path(folder/'source.csv'),source_sha256=hashlib.sha256(engineering_raw).hexdigest())
        if mode.startswith('ml_') and payload.get('content'):(folder/'source_ml.csv').write_bytes(raw)
        if mode in ['research_multi','research_chain']:(folder/'source_campaign.csv').write_bytes(raw)
        if mode=='parquet_preprocess':
            (folder/'source.parquet').write_bytes(raw);config['source_path']=wsl_path(folder/'source.parquet')
            config['source_sha256']=hashlib.sha256(raw).hexdigest();config['filename']=str(payload.get('filename','Parquet记录'))[:200]
        (folder/'config.json').write_text(json.dumps(config),encoding='utf-8')
        (folder/'workspace_snapshot.json').write_text(json.dumps(workspace,ensure_ascii=False),encoding='utf-8')
        job={'id':ident,'workspace':workspace['id'],'workspace_name':workspace['name'],'workspace_revision':workspace['revision'],
             'mode':mode,'model':'impedance.py / RC' if mode=='eis_fit' else '科研闭环 / 代理模型' if mode in ['research_multi','research_chain','public_ml_validation'] else '描述符 / 分组机器学习' if mode.startswith('ml_') else 'GP / MC-HVI' if mode=='candidate_multi' else '数据转换' if mode=='parquet_preprocess' else model,'status':'queued','scope':'模型探索/方法处理；没有自动校准你的回收石墨材料'}
        if mode=='engineering':
            from user_tools.workbench.engineering_contracts import ACTIONS
            job['model']=ACTIONS[request['action']]
        self.store.put_job(job)
        threading.Thread(target=self.run_job,args=(job,folder),daemon=True).start()
        return job

    def run_job(self,job,folder):
        with self.physics_lock:
            job['status']='running';self.store.put_job(job)
            try:
                runtime='/home/zjh/miniforge3/envs/pybamm/bin/python';worker='user_tools.workbench.physics_worker'
                if job['mode']=='engineering':
                    from user_tools.workbench.engineering_service import runtime_for
                    saved=json.loads((folder/'config.json').read_text(encoding='utf-8'))
                    runtime=runtime_for(self.project,saved['engineering_config']['action']);worker='user_tools.workbench.engineering_worker'
                args=['wsl.exe','-d','Ubuntu','--cd',wsl_path(self.project),'--',runtime,
                      '-m',worker,'--config',wsl_path(folder/'config.json'),'--out',wsl_path(folder/'physics')]
                with (folder/'log.txt').open('wb') as log:
                    p=subprocess.run(args,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=1800)
                target=folder/'physics/ui_result.json'
                if p.returncode or not target.exists():raise RuntimeError('任务失败，见运行日志；可能是环境缺失或模型不能覆盖数据。')
                data=json.loads(target.read_text(encoding='utf-8'))
                if job['mode']=='parquet_preprocess':
                    import shutil
                    shutil.copyfile(folder/'physics/normalized.csv',folder/'normalized.csv')
                    (folder/'qc.json').write_text(json.dumps(data['result'],ensure_ascii=False,indent=2),encoding='utf-8')
                job.update(status='completed',**data)
            except Exception as exc:job.update(status='failed',error=str(exc))
            self.store.put_job(job)

    def import_curve(self,payload):
        workspace=self.store.get(payload['workspace']);raw=base64.b64decode(payload['content'],validate=True)
        if len(raw)>20_000_000:raise ValueError('CSV超过20MB。')
        rows=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))));points=[];previous=None
        for r in rows:
            try:t=float(r['time_s']);v=float(r['voltage_V'])
            except (KeyError,TypeError,ValueError):raise ValueError('CSV需含time_s和voltage_V两列，数值不可为空。')
            if not math.isfinite(t) or not math.isfinite(v) or (previous is not None and t<=previous):raise ValueError('时间需严格递增且数据为有限数字。')
            points.append([t,v,None]);previous=t
        if len(points)<2:raise ValueError('曲线至少需两个数据点。')
        ident=uuid.uuid4().hex;folder=self.data/'jobs'/ident;folder.mkdir(parents=True)
        (folder/'source.csv').write_bytes(raw)
        job={'id':ident,'workspace':workspace['id'],'workspace_name':workspace['name'],'mode':'experimental_curve','status':'completed',
             'result':{'evidence_type':'user_uploaded_curve','points':len(points),'source_sha256':hashlib.sha256(raw).hexdigest(),
                       'scope':'用户原始曲线，未进行参数辨识或独立预测验证'},
             'curves':[{'name':str(payload.get('name','实验曲线'))[:100],'points':points[::max(1,len(points)//500)]}]}
        self.store.put_job(job);return job

    def analyze(self,payload):
        workspace=self.store.get(payload['workspace'])
        config=payload.get('config',{})
        result=run_analysis(workspace['tables'],config)
        ident=uuid.uuid4().hex;folder=self.data/'jobs'/ident;folder.mkdir(parents=True)
        snapshot={'config':config,'workspace':workspace,'result':result}
        (folder/'analysis.json').write_text(json.dumps(snapshot,ensure_ascii=False,allow_nan=False),encoding='utf-8')
        job={'id':ident,'workspace':workspace['id'],'workspace_name':workspace['name'],'mode':'research_analysis',
             'workspace_revision':workspace['revision'],'status':'completed','config':config,'result':result,'scope':result['scope']}
        self.store.put_job(job);return job

    def preprocess(self,payload):
        workspace=self.store.get(payload['workspace']);raw=base64.b64decode(payload['content'],validate=True)
        if len(raw)>20_000_000:raise ValueError('CSV超过20MB，请按实验拆分。')
        records,result=normalize_csv(raw,payload.get('config',{}))
        ident=uuid.uuid4().hex;folder=self.data/'jobs'/ident;folder.mkdir(parents=True)
        (folder/'source.csv').write_bytes(raw);save_normalized(folder/'normalized.csv',records)
        result.update(evidence_type='user_preprocessed_curve',source_sha256=hashlib.sha256(raw).hexdigest(),filename=str(payload.get('filename',''))[:200])
        (folder/'qc.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        job={'id':ident,'workspace':workspace['id'],'workspace_name':workspace['name'],'workspace_revision':workspace['revision'],
             'mode':'preprocess','status':'completed','result':result,'config':payload.get('config',{}),
             'curves':[{'name':'标准化电压','points':[[r['time_s'],r['voltage_V'],None] for r in records[::max(1,len(records)//500)]]}]}
        self.store.put_job(job);return job

    def capacity_forecast(self, payload):
        from user_tools.workbench.capacity_forecast import csv_bytes, run
        workspace = self.store.get(payload['workspace'])
        raw, result = run(self.project, payload)
        ident = uuid.uuid4().hex
        folder = self.data / 'jobs' / ident
        folder.mkdir(parents=True)
        (folder / 'capacity_input.csv').write_bytes(raw)
        (folder / 'capacity.csv').write_bytes(csv_bytes(result['columns'], result['points']))
        (folder / 'capacity.json').write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        summary = {k: result[k] for k in ('cell_id', 'algorithm_name', 'cutoff', 'metrics', 'input_sha256')}
        summary['dataset'] = result['source']['title']
        if 'interval' in result:
            summary['interval_level'] = result['interval']['level']
        job = dict(id=ident, workspace=workspace['id'], workspace_name=workspace['name'],
                   workspace_revision=workspace['revision'], mode='capacity_forecast', status='completed', result=summary)
        self.store.put_job(job)
        return {'job': job, 'result': result}

    def multichem(self,payload):
        from user_tools.workbench.multichem_analysis import run
        workspace=self.store.get(payload['workspace'])
        raw=base64.b64decode(payload.get('content',''),validate=True)
        config=payload.get('config',{})
        ident=uuid.uuid4().hex;folder=self.data/'jobs'/ident;folder.mkdir(parents=True)
        if payload.get('kind') in ('cv_sim','ixdat','osbad','hardcarbon_train','hardcarbon_predict','hardcarbon_shap','hardcarbon_joint_train','hardcarbon_joint_recommend','hardcarbon_ax_mobo','sodium_identify','soh_train','soh_predict','uncertainty_audit','ax_recommend','helao_plan'):
            if not self.project:raise ValueError('上游工具需要项目目录和独立WSL环境。')
            if payload.get('kind')!='cv_sim' and (not raw or len(raw)>20_000_000):raise ValueError('CSV文件需非空且不超过20MB。')
            if payload.get('kind') in ('soh_predict','hardcarbon_predict','hardcarbon_shap','hardcarbon_joint_recommend'):
                parent=self.store.job(payload.get('parent',''))
                expected='soh_train' if payload['kind']=='soh_predict' else 'hardcarbon_joint_train' if payload['kind']=='hardcarbon_joint_recommend' else 'hardcarbon_train'
                if parent['workspace']!=workspace['id'] or parent['mode']!='multichem' or parent['result'].get('kind')!=expected or parent['status']!='completed':
                    raise ValueError('请选择同一方案已完成的对应模型训练任务。')
                config={**config,'_model_path':wsl_path(self.data/'jobs'/parent['id']/'trained_model.joblib'),
                        '_model_sha256':parent['result']['model_sha256'],'parent_job':parent['id']}
                if payload['kind']=='hardcarbon_shap':
                    config.update(_training_source_path=wsl_path(self.data/'jobs'/parent['id']/'source.csv'),
                                  _training_source_sha256=parent['result']['source_sha256'])
            if payload.get('kind')=='sodium_identify' and payload.get('parent'):
                parent=self.store.job(payload['parent'])
                if parent['workspace']!=workspace['id'] or parent['mode']!='multichem' or parent['result'].get('kind')!='hardcarbon_joint_recommend' or parent['status']!='completed':
                    raise ValueError('关联候选必须来自同方案已完成的硬碳候选任务。')
                previous=json.loads((self.data/'jobs'/parent['id']/'multichem.json').read_text(encoding='utf-8'))['result']
                candidate_id=str(config.get('candidate_id','')).strip()
                matches=[r for r in previous['predictions'] if r['record_id']==candidate_id]
                if len(matches)!=1:raise ValueError('candidate_id必须存在于关联的候选任务中。')
                config={**config,'_candidate_link':{'job_id':parent['id'],'candidate':matches[0]}}
            (folder/'upstream_config.json').write_text(json.dumps(config,ensure_ascii=False),encoding='utf-8')
            (folder/'source.csv').write_bytes(raw)
            args=['wsl.exe','-d','Ubuntu','--cd',wsl_path(self.project),'--',
                  '/home/zjh/.local/share/fangzhen/multichem-20261029/bin/python','-m',
                  'user_tools.workbench.multichem_upstream',payload['kind'],wsl_path(folder/'upstream_config.json'),wsl_path(folder/'source.csv'),wsl_path(folder/'upstream_result.json')]
            try:
                process=subprocess.run(args,capture_output=True,timeout=900 if payload['kind'] in ('hardcarbon_train','hardcarbon_joint_train','hardcarbon_ax_mobo','sodium_identify','soh_train','hardcarbon_shap','ax_recommend') else 90,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            except subprocess.TimeoutExpired:raise ValueError('上游工具运行超时。') from None
            if process.returncode or not (folder/'upstream_result.json').exists():
                raise ValueError('上游工具运行失败；请检查独立WSL环境及参数：'+process.stderr.decode('utf-8',errors='replace')[-1000:])
            result=json.loads((folder/'upstream_result.json').read_text(encoding='utf-8'))
        else:
            result=run(payload.get('kind'),raw,config)
        (folder/'source.csv').write_bytes(raw)
        result.update(source_sha256=hashlib.sha256(raw).hexdigest(),filename=str(payload.get('filename',''))[:200])
        (folder/'multichem.json').write_text(json.dumps({'kind':payload['kind'],'config':config,'result':result},ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        job={'id':ident,'workspace':workspace['id'],'workspace_name':workspace['name'],
             'workspace_revision':workspace['revision'],'mode':'multichem','status':'completed',
             'result':{'kind':payload['kind'],'source_sha256':result['source_sha256'],'scope':result['scope']}}
        if result.get('model_sha256'):job['result']['model_sha256']=result['model_sha256']
        self.store.put_job(job)
        return {'job':job,'result':result}

    def import_ocp(self,payload):
        workspace=self.store.get(payload['workspace']);raw=base64.b64decode(payload['content'],validate=True)
        if len(raw)>1_000_000:raise ValueError('OCP表超过1MB。')
        rows=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))));points=[]
        for row in rows:
            x=float(row['stoichiometry']);v=float(row['voltage_V'])
            if not math.isfinite(x) or not math.isfinite(v) or not 0<=x<=1 or (points and x<=points[-1][0]):raise ValueError('OCP锂化度需在0–1内严格递增，电位需为有限数。')
            points.append([x,v])
        if not 3<=len(points)<=5000:raise ValueError('OCP需要3–5000个点。')
        ident=uuid.uuid4().hex;folder=self.data/'jobs'/ident;folder.mkdir(parents=True)
        (folder/'ocp.csv').write_bytes(raw)
        job={'id':ident,'workspace':workspace['id'],'workspace_name':workspace['name'],'mode':'ocp_table','status':'completed',
             'result':{'filename':str(payload.get('filename','OCP'))[:200],'x_min':points[0][0],'x_max':points[-1][0],
                       'points':len(points),'source_sha256':hashlib.sha256(raw).hexdigest(),'scope':'用户OCP表，必须对应同一样品、方向与温度；未自动证明其有效性。'}}
        self.store.put_job(job);return job

    def paper_analysis(self,payload):
        workspace=self.store.get(payload['workspace']);raw=base64.b64decode(payload['content'],validate=True)
        if len(raw)>4_000_000:raise ValueError('论文方法CSV一次最多4MB。')
        kind=payload.get('kind');config=payload.get('config',{})
        result=read_eis(raw,config) if kind=='eis' else split_conformal(raw,config) if kind=='calibration' else None
        if result is None:raise ValueError('未知论文方法分析。')
        ident=uuid.uuid4().hex;folder=self.data/'jobs'/ident;folder.mkdir(parents=True)
        (folder/'source.csv').write_bytes(raw)
        (folder/'analysis.json').write_text(json.dumps({'config':config,'result':result},ensure_ascii=False,indent=2),encoding='utf-8')
        job={'id':ident,'workspace':workspace['id'],'workspace_name':workspace['name'],'workspace_revision':workspace['revision'],
             'mode':'eis_import' if kind=='eis' else 'split_conformal','status':'completed','result':result,'config':config}
        self.store.put_job(job);return job

    def sustainability_runtime(self):
        if not self.project:raise ValueError('环境评价需要原项目目录。')
        python=self.project/'data/runtime/sustainability/Scripts/python.exe'
        if not python.is_file():raise ValueError('环境评价后端尚未安装，请运行项目根目录“安装环境与经济评价.bat”。')
        return python

    def inventory_preview(self,payload):
        raw=base64.b64decode(payload['content'],validate=True)
        if len(raw)>1_000_000:raise ValueError('清单CSV最多1MB。')
        reader=csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
        required={'name','unit','quantity','unit_price','gwp_factor','source'}
        if not reader.fieldnames or set(reader.fieldnames)!=required or len(reader.fieldnames)!=len(required):
            raise ValueError('清单CSV表头需为name,unit,quantity,unit_price,gwp_factor,source。')
        rows=list(reader)
        if not 1<=len(rows)<=200 or any(None in r or any(v is None for v in r.values()) for r in rows):
            raise ValueError('清单需要1–200项，且每行列数与表头一致。')
        return {'inventory':rows,'sha256':hashlib.sha256(raw).hexdigest()}

    def start_sustainability(self,payload):
        workspace=self.store.get(payload['workspace']);config=normalize_config(payload.get('config'))
        if config['kind']=='inventory' and config['sample_id'] and config['sample_id'] not in {
            r.get('sample_id') for r in workspace['tables']['处理工艺']}|{r['record_id'] for r in self.experiments.list(workspace['id'])}:
            raise ValueError('关联样品必须来自本方案的处理工艺表或待实验记录。')
        self.sustainability_runtime()
        original=None
        if config['kind']=='inventory' and payload.get('content'):
            self.inventory_preview(payload)
            original=base64.b64decode(payload['content'],validate=True)
        ident=uuid.uuid4().hex;folder=self.data/'jobs'/ident;folder.mkdir(parents=True)
        (folder/'config.json').write_text(json.dumps(config,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf-8')
        (folder/'workspace_snapshot.json').write_text(json.dumps(workspace,ensure_ascii=False),encoding='utf-8')
        job={'id':ident,'workspace':workspace['id'],'workspace_name':workspace['name'],'workspace_revision':workspace['revision'],
             'mode':'sustainability_inventory' if config['kind']=='inventory' else 'everbatt_reference',
             'model':'Brightway / 工艺成本筛选' if config['kind']=='inventory' else 'EverBatt社区迁移参考',
             'status':'queued','config':config,'scope':'声明清单或公开参考案例；不自动认证材料与经济性结论'}
        if original is not None:
            (folder/'source_inventory.csv').write_bytes(original)
            job['source_sha256']=hashlib.sha256(original).hexdigest()
        self.store.put_job(job)
        threading.Thread(target=self.run_sustainability,args=(job,folder),daemon=True).start()
        return job

    def run_sustainability(self,job,folder):
        with self.sustainability_lock:
            job['status']='running';self.store.put_job(job)
            try:
                python=self.sustainability_runtime()
                args=[str(python),'-m','user_tools.workbench.sustainability_worker','--config',str(folder/'config.json'),
                      '--out',str(folder/'assessment'),'--project',str(self.project)]
                with (folder/'log.txt').open('wb') as log:
                    p=subprocess.run(args,cwd=self.project,stdout=log,stderr=subprocess.STDOUT,
                        timeout=300,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                if p.returncode:raise RuntimeError('环境评价计算失败，请查看运行日志。')
                data=json.loads((folder/'assessment/ui_result.json').read_text(encoding='utf-8'))
                job.update(status='completed',**data)
            except Exception as exc:job.update(status='failed',error=str(exc))
            self.store.put_job(job)

    def environment(self):
        result={'entry_version':APP_VERSION,'data_entry':True,'analysis':True,'project_found':bool(self.project),'data_directory':str(self.data),
                'battery_agent':True,'agent_llm_configured':bool(self.project and public_settings(self.project)['configured'])}
        try:
            python=self.sustainability_runtime()
            probe=subprocess.run([str(python),'-c','import json,bw2calc,bw2data; print(json.dumps({"bw2calc":bw2calc.__version__,"bw2data":bw2data.__version__}))'],
                capture_output=True,timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            result['sustainability_available']=probe.returncode==0
            result['sustainability_versions']=json.loads(probe.stdout.decode('utf-8').strip()) if probe.returncode==0 else None
        except (ValueError,OSError,subprocess.TimeoutExpired):result['sustainability_available']=False
        try:self.node_runtime();result['excel_export']=True
        except ValueError:result['excel_export']=False
        try:
            p=subprocess.run(['wsl.exe','-d','Ubuntu','--','/home/zjh/miniforge3/envs/pybamm/bin/python','-c',
                 'import json,pybamm,numpy; print(json.dumps({"pybamm":pybamm.__version__,"numpy":numpy.__version__}))'],
                 capture_output=True,timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            result['physics_runtime']=json.loads(p.stdout.decode('utf-8').strip()) if p.returncode==0 else None
        except (OSError,ValueError,subprocess.TimeoutExpired):result['physics_runtime']=None
        result['physics_available']=bool(result['project_found'] and result['physics_runtime'])
        return result

    def report(self,ident):
        workspace=self.store.get(ident);jobs=[j for j in self.store.jobs() if j['workspace']==ident]
        esc=html.escape
        sections=[]
        for spec in SCHEMA['tables']:
            rows=workspace['tables'][spec['sheet']]
            if not rows:continue
            headings=''.join('<th>'+esc(f[1])+'</th>' for f in spec['fields'])
            body=''.join('<tr>'+''.join('<td>'+esc(str(row.get(f[0]) if row.get(f[0]) is not None else ''))+'</td>' for f in spec['fields'])+'</tr>' for row in rows)
            sections.append('<h2>'+esc(spec['sheet'])+'</h2><div class="scroll"><table><tr>'+headings+'</tr>'+body+'</table></div>')
        for job in jobs:
            sections.append('<h2>'+esc(job['mode'])+' · '+esc(job['status'])+' · 数据版本 '+esc(str(job.get('workspace_revision','未记录')))+'</h2><pre>'+esc(json.dumps(job.get('result',job.get('error')),ensure_ascii=False,indent=2))+'</pre>')
            if job['mode']=='preprocess' and not job.get('result',{}).get('qc_pass'):continue
            for curve in job.get('curves',[])[:1]:
                points=[p for p in curve.get('points',[]) if len(p)>=2 and all(isinstance(v,(int,float)) and math.isfinite(v) for v in p[:2])]
                if len(points)<2:continue
                ts=[p[0] for p in points];vs=[p[1] for p in points];xmin,xmax=min(ts),max(ts);ymin,ymax=min(vs),max(vs)
                path=' '.join(('M' if i==0 else 'L')+f'{40+(p[0]-xmin)/(xmax-xmin or 1)*700:.2f},{220-(p[1]-ymin)/(ymax-ymin or 1)*180:.2f}' for i,p in enumerate(points))
                sections.append('<p>显示抽样曲线：'+esc(curve.get('name',''))+'</p><svg viewBox="0 0 780 270" style="max-width:900px;width:100%" role="img"><path d="'+path+'" fill="none" stroke="#6658c8" stroke-width="2"/><text x="40" y="250">时间(s)：'+f'{xmin:.4g}—{xmax:.4g}'+'</text><text x="40" y="20">电压(V)：'+f'{ymin:.4g}—{ymax:.4g}'+'</text></svg>')
        return ('<!doctype html><meta charset="utf-8"><title>科研报告</title><style>body{font:15px system-ui;margin:32px;color:#26334c}table{border-collapse:collapse}td,th{border:1px solid #ddd;padding:8px;white-space:nowrap}.scroll{overflow:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f5fa;padding:18px}</style><h1>'+esc(workspace['name'])+'</h1><p>当前数据版本 '+str(workspace['revision'])+'。历史任务保留其原始版本，不表示重新计算。任务运行完成不代表材料验证通过。</p>'+''.join(sections)).encode('utf-8')


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    @property
    def app(self):return self.server.app
    def json(self,value,status=200):
        raw=json.dumps(value,ensure_ascii=False,allow_nan=False).encode('utf-8');self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(raw)
    def authorized(self):
        host=self.headers.get('Host','')
        expected={'127.0.0.1:'+str(self.server.server_port),'localhost:'+str(self.server.server_port)}
        origin=self.headers.get('Origin')
        return host in expected and (not origin or origin in {'http://'+h for h in expected}) and secrets.compare_digest(self.headers.get('X-Workbench-Token',''),self.app.token)
    def binary(self,raw,mime):
        self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(raw)))
        self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        parsed=urlsplit(self.path);path=parsed.path
        if not path.startswith('/api/'):
            assets={'/multichem.js':'multichem.js','/engineering.js':'engineering.js','/agent.js':'agent.js','/':'index.html','/app.js':'app.js','/analysis.js':'analysis.js','/pipeline.js':'pipeline.js','/papers.js':'papers.js','/ml.js':'ml.js','/research.js':'research.js','/sustainability.js':'sustainability.js','/style.css':'style.css'}
            assets['/capacity.js'] = 'capacity.js'
            if path not in assets:self.send_error(404);return
            file=resource_dir()/'web'/assets[path]
            mime='text/html; charset=utf-8' if path=='/' else 'text/javascript; charset=utf-8' if path.endswith('.js') else 'text/css; charset=utf-8'
            self.binary(file.read_bytes(),mime);return
        if not self.authorized():self.json({'error':'本地会话无效，请从程序重新打开。'},403);return
        try:
            args=parse_qs(parsed.query);ident=args.get('id',[''])[0]
            if path=='/api/bootstrap':self.json({'schema':SCHEMA,'workspaces':self.app.store.list(),'jobs':self.app.store.jobs(),'physics_available':bool(self.app.project)})
            elif path=='/api/capacity_catalog':
                from user_tools.workbench.capacity_forecast import catalog
                self.json(catalog(self.app.project))
            elif path=='/api/hardware_readiness':
                from user_tools.workbench.hardware_readiness import inventory
                self.json(inventory(self.app.project))
            elif path=='/api/engineering_catalog':
                from user_tools.workbench.engineering_service import public_catalog
                self.json(public_catalog(self.app.project))
            elif path=='/api/workspace':self.json(self.app.store.get(ident))
            elif path=='/api/versions':self.json(self.app.store.revisions(ident))
            elif path=='/api/jobs':self.json(self.app.store.jobs())
            elif path=='/api/environment':self.json(self.app.environment())
            elif path=='/api/agent_llm':self.json(public_settings(self.app.project))
            elif path=='/api/mlcatalog':self.json({'fields':ml_catalog(),'targets':ml_targets()})
            elif path=='/api/experiments':
                self.app.store.get(ident);self.json(self.app.experiments.list(ident))
            elif path=='/api/report':self.binary(self.app.report(ident),'text/html; charset=utf-8')
            elif path=='/api/study':
                if not self.app.project:raise ValueError('论文学习资料在原项目目录。')
                self.binary((self.app.project/'outputs/paper_study_20261012/论文与源码学习报告.html').read_bytes(),'text/html; charset=utf-8')
            elif path=='/api/download':
                job=self.app.store.job(ident);kind=args.get('kind',['normalized'])[0]
                files={'multichem':('multichem.json','application/json'),'multichem_source':('source.csv','text/csv; charset=utf-8'),'multichem_holdout':('holdout.csv','text/csv; charset=utf-8'),'hardcarbon_prepared':('prepared.csv','text/csv; charset=utf-8'),'normalized':('normalized.csv','text/csv; charset=utf-8'),'qc':('qc.json','application/json'),'ocp':('ocp.csv','text/csv; charset=utf-8'),
                       'assessment':('assessment/result.json','application/json'),'inventory':('assessment/contributions.csv','text/csv; charset=utf-8'),
                       'assessment_config':('config.json','application/json'),
                       'ml_oof':('physics/oof.csv','text/csv; charset=utf-8'),'ml_importance':('physics/importance.csv','text/csv; charset=utf-8'),
                       'ml_predictions':('physics/predictions.csv','text/csv; charset=utf-8'),'ml_result':('physics/result.json','application/json'),
                       'campaign':('physics/campaign.csv','text/csv; charset=utf-8'),'chain_oof':('physics/chain_oof.csv','text/csv; charset=utf-8'),
                       'public_replay':('physics/replay.csv','text/csv; charset=utf-8'),'public_summary':('physics/replay_summary.csv','text/csv; charset=utf-8'),
                       'eis_fit':('physics/spectrum_fit.csv','text/csv; charset=utf-8'),
                       'sodium_curve':('physics/forward_curve.csv','text/csv; charset=utf-8'),
                       'eis_parameters':('physics/parameters.csv','text/csv; charset=utf-8'),
                       'eis_result':('physics/result.json','application/json'),
                       'engineering_csv':('physics/engineering.csv','text/csv; charset=utf-8'),
                       'stanford_model':('physics/stanford_model.json','application/json'),
                       'stanford_selection':('physics/stanford_selection.json','application/json'),
                       'eis_hppc_models':('physics/frozen_models.json','application/json'),
                       'eis_hppc_summary':('physics/summary.json','application/json'),
                       'eis_hppc_traces':('physics/window_traces.csv','text/csv; charset=utf-8'),
                       'eis_hppc_report':('physics/ablation_report.html','text/html; charset=utf-8'),
                       'engineering_result':('physics/result.json','application/json'),
                       'engineering_config':('config.json','application/json'),
                       'engineering_parameters':('physics/parameters.csv','text/csv; charset=utf-8'),
                       'engineering_eis_grid':('physics/rc_grid.json','application/json'),
                       'engineering_pack':('physics/pack_raw.json','application/json'),
                       'engineering_netlist':('physics/pack_netlist.csv','text/csv; charset=utf-8'),
                       'engineering_cycler':('physics/pyprobe_normalized.csv','text/csv; charset=utf-8'),
                       'engineering_dbc':('physics/can_database.json','application/json'),
                       'engineering_dbc_audit':('physics/dbc_compatibility.json','application/json'),
                       'engineering_split':('physics/split_manifest.json','application/json'),
                       'engineering_faults':('physics/fault_confusion.json','application/json'),
                       'engineering_bo':('physics/bo_training_manifest.json','application/json'),
                       'engineering_frontier':('physics/frontier_manifest.json','application/json'),
                       'engineering_life_split':('physics/batterylife_split.json','application/json'),
                       'engineering_life_checkpoint':('physics/batterylife_checkpoint.pt','application/octet-stream'),
                       'engineering_commercial':('physics/commercial_validation.json','application/json'),
                       'engineering_commercial_metrics':('physics/commercial_metrics.csv','text/csv; charset=utf-8'),
                       'engineering_frozen':('physics/frozen_model.json','application/json'),
                       'engineering_control_config':('physics/commercial_control_config.json','application/json'),
                       'adaptive_model':('physics/adaptive_frozen_model.json','application/json'),
                       'adaptive_validation':('physics/adaptive_validation.json','application/json'),
                       'adaptive_control_config':('physics/adaptive_control_config.json','application/json'),
                       'adaptive_metrics':('physics/adaptive_metrics.csv','text/csv; charset=utf-8'),
                       'calb_validation':('physics/calb_validation.json','application/json'),
                       'calb_metrics':('physics/calb_metrics.csv','text/csv; charset=utf-8'),
                       'calb_pulse_metrics':('physics/calb_pulse_metrics.csv','text/csv; charset=utf-8'),
                       'calb_eis_inventory':('physics/calb_eis_inventory.csv','text/csv; charset=utf-8'),
                       'calb_traces':('physics/calb_traces.csv','text/csv; charset=utf-8'),
                       'calb_calibration':('physics/calb_calibration.json','application/json'),
                       'crosscell_metrics':('physics/crosscell_metrics.csv','text/csv; charset=utf-8'),
                       'crosscell_traces':('physics/crosscell_traces.csv','text/csv; charset=utf-8'),
                       'crosscell_validation':('physics/crosscell_validation.json','application/json'),
                       'crosscell_model':('physics/pooled_model.json','application/json'),
                       'tesla_metrics':('physics/tesla_metrics.csv','text/csv; charset=utf-8'),
                       'tesla_traces':('physics/tesla_traces.csv','text/csv; charset=utf-8'),
                       'tesla_validation':('physics/tesla_validation.json','application/json'),
                       'tesla_calibration':('physics/tesla_calibration.json','application/json'),
                       'eis_audit':('physics/eis_audit.json','application/json'),
                       'eis_audit_metrics':('physics/eis_audit_metrics.csv','text/csv; charset=utf-8'),
                       'safety_cases':('physics/safety_cases.json','application/json'),
                       'safety_trace':('physics/safety_trace.json','application/json'),
                       'hardware_template':('physics/hardware_template.json','application/json')}
                files.update(capacity_csv=('capacity.csv','text/csv; charset=utf-8'),
                             capacity_json=('capacity.json','application/json'),
                             capacity_input=('capacity_input.csv','text/csv; charset=utf-8'))
                if kind not in files:raise ValueError('未知下载类型。')
                name,mime=files[kind];self.binary((self.app.data/'jobs'/job['id']/name).read_bytes(),mime)
            elif path=='/api/export':self.binary(self.app.export(ident).read_bytes(),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            elif path=='/api/joblog':
                job=self.app.store.job(ident);p=self.app.data/'jobs'/job['id']/'log.txt'
                self.json({'text':p.read_bytes()[-18000:].decode('utf-8',errors='replace') if p.exists() else '尚无日志。'})
            else:self.send_error(404)
        except (ValueError,KeyError,RuntimeError,OSError) as exc:self.json({'error':str(exc)},400)
    def do_POST(self):
        if not self.authorized():self.json({'error':'本地会话无效。'},403);return
        try:
            size=int(self.headers.get('Content-Length',0))
            if size<0 or size>40_000_000:raise ValueError('请求数据过大。')
            data=json.loads(self.rfile.read(size));path=urlsplit(self.path).path
            if path=='/api/create':result=self.app.store.create(data['name'])
            elif path=='/api/save':result=self.app.store.save(data['id'],data['revision'],data['tables'],data.get('name'))
            elif path=='/api/restore':result=self.app.store.restore(data['id'],int(data['version']),int(data['revision']))
            elif path=='/api/solve':result=solve_constraints(data.get('known',{}),data.get('bounds',{}))
            elif path=='/api/import':
                raw=base64.b64decode(data['content'],validate=True);folder=self.app.data/'imports'/uuid.uuid4().hex;folder.mkdir(parents=True)
                file=folder/'source.xlsx';file.write_bytes(raw)
                result=self.app.store.create(str(data.get('name','导入方案')),read_import(file),{'name':data.get('filename'),'sha256':hashlib.sha256(raw).hexdigest()})
            elif path=='/api/importjson':
                body=data.get('backup',{})
                if not isinstance(body,dict) or not isinstance(body.get('tables'),dict):raise ValueError('JSON备份缺少数据表。')
                tables=to_scalar_tables(body['tables'])
                result=self.app.store.create(str(body.get('name','恢复方案'))+' · 备份恢复',tables,{'name':'JSON backup'})
            elif path=='/api/job':result=self.app.start_job(data)
            elif path=='/api/agent_llm':result=save_settings(self.app.project,data)
            elif path=='/api/agent_llm_probe':result=probe_settings(self.app.project)
            elif path=='/api/mlpreview':
                workspace=self.app.store.get(data['workspace']);config=data.get('config',{})
                result=csv_dataset(base64.b64decode(data['content'],validate=True),config) if data.get('content') else workspace_dataset(workspace['tables'],config)
            elif path=='/api/experimentplan':
                workspace=self.app.store.get(data['workspace']);parent=self.app.store.job(data['parent'])
                if parent['mode']!='research_multi' or parent['status']!='completed' or parent['workspace']!=workspace['id']:raise ValueError('请选择同方案多目标任务。')
                config=json.loads((self.app.data/'jobs'/parent['id']/'config.json').read_text(encoding='utf-8'))
                ident=data.get('record_id') or (parent['result'].get('selected') or {}).get('record_id')
                record=next((r for r in config['dataset']['rows'] if r['record_id']==ident),None)
                if record is None:raise ValueError('原始候选/实验记录不存在。')
                if record['status']=='completed' and not data.get('repeat'):raise ValueError('已完成条件请选择独立重复实验。')
                result=self.app.experiments.plan(workspace['id'],config['campaign_id'],parent['id'],record,config['dataset']['objectives'],bool(data.get('repeat')))
            elif path=='/api/experimentfeedback':
                old=self.app.experiments.get(data['id'])
                if old['workspace']!=data['workspace']:raise ValueError('实验不属于当前方案。')
                result=self.app.experiments.feedback(data['id'],int(data['revision']),data.get('values',{}),data.get('status','measured'),data.get('notes',''))
            elif path=='/api/experimentinventory':
                old=self.app.experiments.get(data['id']);source=self.app.store.job(data['inventory_job'])
                if old['workspace']!=data['workspace'] or source['workspace']!=data['workspace'] or source['mode']!='sustainability_inventory' or source['status']!='completed':
                    raise ValueError('请选择同方案已完成的石墨清单评价，不能使用按进料计的EverBatt参考值。')
                inv=source['result']
                if inv['sample_id'] not in [old['record_id'],old['record'].get('sample_id')]:raise ValueError('清单评价样品编号与实验记录不匹配。')
                keys=[o['key'] for o in old['objectives']]
                if data.get('carbon_key') not in keys or data.get('cost_key') not in keys or data['carbon_key']==data['cost_key']:raise ValueError('请选择不同的碳足迹和成本目标。')
                targets={o['key']:o for o in old['objectives']}
                cost_unit=str(targets[data['cost_key']].get('unit','')).replace(' ','')
                carbon_unit=str(targets[data['carbon_key']].get('unit','')).lower().replace(' ','').replace('-','').replace('product','')
                if not cost_unit.startswith(inv['currency']+'/kg'):raise ValueError('成本目标单位与清单币种不一致；请在目标中明确CNY/kg、USD/kg或EUR/kg。')
                if carbon_unit not in ['kgco2eq/kg','kgco2e/kg']:raise ValueError('碳足迹目标需明确kg CO2-eq/kg，不能自动混用g与kg。')
                context={k:inv.get(k) for k in ['functional_unit','currency','boundary','region','price_basis','evidence_type']}
                for prior in self.app.experiments.list(old['workspace'],old['campaign']):
                    if prior.get('inventory_provenance') and prior['inventory_provenance']['context']!=context:
                        raise ValueError('本闭环已关联不同功能单位、币种或边界的清单；请分别建模。')
                values={data['carbon_key']:inv['gwp_kg_co2e_per_kg_product'],data['cost_key']:inv['cost_per_kg_product']}
                result=self.app.experiments.feedback(old['id'],int(data['revision']),values,notes=old.get('notes',''),
                    provenance={'job':source['id'],'inventory_sha256':inv['inventory_sha256'],'context':context,
                                'units':{data['carbon_key']:'kg CO2-eq/kg product',data['cost_key']:inv['currency']+'/kg product'}})
            elif path=='/api/curve':result=self.app.import_curve(data)
            elif path=='/api/analyze':result=self.app.analyze(data)
            elif path=='/api/preprocess':result=self.app.preprocess(data)
            elif path=='/api/capacity_cells':
                from user_tools.workbench.capacity_forecast import cells_info, input_data, parse_cycles
                raw, _ = input_data(self.app.project, data)
                result = cells_info(parse_cycles(raw))
            elif path=='/api/capacity_forecast':result=self.app.capacity_forecast(data)
            elif path=='/api/capacity_source_folder':
                from user_tools.workbench.capacity_forecast import source_folder
                folder = source_folder(self.app.project, data.get('source'))
                if os.name == 'nt':
                    os.startfile(str(folder))
                elif sys.platform == 'darwin' or os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'):
                    subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', str(folder)])
                result = {'folder': str(folder)}
            elif path=='/api/multichem':result=self.app.multichem(data)
            elif path=='/api/ocp':result=self.app.import_ocp(data)
            elif path=='/api/papermethod':result=self.app.paper_analysis(data)
            elif path=='/api/inventorypreview':result=self.app.inventory_preview(data)
            elif path=='/api/sustainability':result=self.app.start_sustainability(data)
            elif path=='/api/shutdown':
                if any(j['status'] in ['queued','running'] for j in self.app.store.jobs()):raise ValueError('任务仍在运行，请结束后关闭程序。')
                self.json({'status':'stopping'});threading.Thread(target=self.server.shutdown,daemon=True).start();return
            else:self.send_error(404);return
            self.json(result)
        except (ValueError,KeyError,TypeError,RuntimeError,OSError,zipfile.BadZipFile) as exc:self.json({'error':str(exc)},400)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--data',type=Path);parser.add_argument('--project',type=Path)
    parser.add_argument('--port',type=int,default=0);parser.add_argument('--no-browser',action='store_true');args=parser.parse_args()
    project=args.project or project_dir()
    data=args.data or ((project/'data/workbench_scalar10') if project else Path(sys.executable).parent/'我的研究数据')
    if not args.data and project and not (Path(data)/'workbench.sqlite').exists():
        import sqlite3
        old=project/'data/workbench_scalar9/workbench.sqlite'
        if not old.exists():old=project/'data/workbench_scalar8/workbench.sqlite'
        if not old.exists():old=project/'data/workbench_scalar7/workbench.sqlite'
        if not old.exists():old=project/'data/workbench_scalar6/workbench.sqlite'
        if not old.exists():old=project/'data/workbench_scalar5/workbench.sqlite'
        if not old.exists():old=project/'data/workbench_scalar4/workbench.sqlite'
        if not old.exists():old=project/'data/workbench_scalar3/workbench.sqlite'
        if not old.exists():old=project/'data/workbench_scalar/workbench.sqlite'
        if not old.exists():old=project/'data/workbench/workbench.sqlite'
        if old.exists():
            import shutil
            Path(data).mkdir(parents=True,exist_ok=True)
            with sqlite3.connect(old) as source,sqlite3.connect(Path(data)/'workbench.sqlite') as target:source.backup(target)
            with sqlite3.connect(old) as source,sqlite3.connect(Path(data)/'升级前备份.sqlite') as target:source.backup(target)
            for name in ['jobs','imports','exports']:
                src=old.parent/name;dest=Path(data)/name
                if src.is_dir() and not dest.exists():shutil.copytree(src,dest)
    # A second double-click opens the existing instance; never resets running jobs.
    session_file=Path(data)/'session.json'
    if not args.no_browser and session_file.exists():
        from urllib.request import Request,urlopen
        try:
            old=json.loads(session_file.read_text(encoding='utf-8'));parts=urlsplit(old['url'])
            old_token=parse_qs(parts.fragment)['token'][0]
            if parts.hostname!='127.0.0.1':raise ValueError('invalid local host')
            request=Request(f'http://127.0.0.1:{old["port"]}/api/bootstrap',headers={'X-Workbench-Token':old_token})
            with urlopen(request,timeout=2) as response:
                if response.status==200:
                    if old.get('entry_version')!=APP_VERSION:
                        if os.name=='nt':
                            import ctypes
                            ctypes.windll.user32.MessageBoxW(0,'请先在旧工作站中保存并点击“关闭程序”，再启动新版。','科研工作站',0)
                        return
                    webbrowser.open(old['url']);return
        except Exception:pass
    app=Application(data,project);server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler);server.app=app
    url=f'http://127.0.0.1:{server.server_port}/#token={app.token}'
    (app.data/'session.json').write_text(json.dumps({'url':url,'port':server.server_port,'pid':os.getpid(),
        'entry_version':APP_VERSION},ensure_ascii=False),encoding='utf-8')
    if not args.no_browser:webbrowser.open(url)
    try:server.serve_forever()
    finally:server.server_close()


if __name__=='__main__':main()

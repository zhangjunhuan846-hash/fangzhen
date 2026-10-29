"""Workbench entry for preselected Stanford HPPC open-loop cases."""
from pathlib import Path
import hashlib,json,shutil
import pandas as pd
from user_tools.workbench.engineering_common import ROOT,finish
from user_tools.workbench.engineering_stanford_frozen import replay_frozen,time_metrics

BASE=ROOT/'outputs/eis_bms_validation'
CASES={'W8_1':('W8',1),'W8_2':('W8',2),'W8_3':('W8',3),'W5_1':('W5',1)}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def run_stanford_case(config,out):
    cell,index=CASES[config['case']]
    folder=BASE/('stanford_w8_new_cycles_20261029' if cell=='W8' else 'stanford_w5_diag2_20261029')
    selection_path=folder/'selection.json';selection=json.loads(selection_path.read_text(encoding='utf8'))
    modelpath=BASE/'stanford_w8_frozen_20261029/frozen_hppc_model.json' if cell=='W8' else folder/'frozen_hppc_model.json'
    if sha(modelpath)!=selection['frozen_model_sha256'] or sha(Path(__file__).with_name('engineering_stanford_frozen.py'))!=selection['replay_code_sha256']:
        raise ValueError('冻结模型或计算代码与选择清单不一致。')
    parts=selection['part_files'] if cell=='W8' else selection['parts']
    for item in parts:
        if sha(ROOT/item['file'])!=item['sha256']:raise ValueError('输入分片与选择清单哈希不一致。')
    d=pd.concat([pd.read_csv(ROOT/p['file']) for p in parts],ignore_index=True).drop_duplicates('time_s',keep='last')
    if (d.time_s.diff().dropna()<=0).any():raise ValueError('分片时间顺序异常。')
    record=selection['baseline_and_selected'][index-1] if cell=='W8' else selection['cycle']
    lo=record['rest']['end_s'];hi=record['dynamic']['end_s']
    frame=d[(d.time_s>=lo-1e-7)&(d.time_s<=hi+1e-7)]
    if frame.empty or abs(frame.time_s.iloc[0]-lo)>1e-6 or abs(frame.time_s.iloc[-1]-hi)>1e-6:raise ValueError('选定记录不完整。')
    trace=replay_frozen(json.loads(modelpath.read_text(encoding='utf8')),frame);dynamic=trace[trace.step==14].copy()
    if len(dynamic)<2 or dynamic.time_s.diff().dropna().max()>1.:raise ValueError('动态数据缺失或采样时间间隔异常。')
    m=time_metrics(dynamic);metrics={'动态电压RMSE_mV':m['rmse_mV'],'动态电压MAE_mV':m['mae_mV'],
       '平均偏差_mV':m['bias_mV'],'去均值RMSE_mV':m['centered_rmse_mV'],
       '最大误差_mV':m['max_abs_mV'],'动态时长_s':m['duration_s'],'动态覆盖率':1.,
       'RC端点保持比例':m['endpoint_hold_time_fraction']}
    decimated=dynamic.iloc[::max(1,len(dynamic)//900)]
    curves=[{'name':'实测与开环电压','x_label':'时间 (s)','y_label':'电压 (V)',
             'primary':'HPPC 1RC开环','secondary':'实测',
             'points':[[float(r.time_s),float(r.model_V),float(r.measured_V)] for r in decimated.itertuples()]},
            {'name':'开环残差','x_label':'时间 (s)','y_label':'残差 (mV)',
             'primary':'预测减实测','secondary':'零',
             'points':[[float(r.time_s),float(r.residual_V*1000),0.] for r in decimated.itertuples()]}]
    details={'cell':cell,'diagnostic':'Diag_1' if cell=='W8' else 'Diag_2',
       'source_scope':'W8基准回合部分数据已观察' if cell=='W8' and index==1 else ('同一W8后续回合' if cell=='W8' else 'W5逐电芯HPPC标定'),
       'dynamic_start':record['dynamic']['start_datetime'],'dynamic_end':record['dynamic']['end_datetime'],
       'rest_duration_s':record['rest']['end_s']-record['rest']['start_s'],'eis_used':False,
       'eis_screening':'未使用；W8 EIS未通过原有桥接筛查' if cell=='W8' else '未使用；W5 EIS尚未完成筛查',
       'model_sha256':sha(modelpath),'selection_sha256':sha(selection_path),
       'scope':'23°C标称温度，单电芯完整UDDS回合；容量及1RC由较早同电芯HPPC辨识，开环无电压反馈；SOC初值和极化为近似，不代表BMS SOC精度或跨温度能力。'}
    result={'kind':'engineering','title':f'Stanford {config["case"]} HPPC开环标准案例','metrics':metrics,'details':details}
    Path(out).mkdir(parents=True,exist_ok=True)
    shutil.copyfile(modelpath,Path(out)/'stanford_model.json')
    shutil.copyfile(selection_path,Path(out)/'stanford_selection.json')
    return finish(config,out,result,dynamic.to_dict(orient='records'),curves,packages=['numpy','pandas','scipy'])

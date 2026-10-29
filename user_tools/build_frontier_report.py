"""Build a source-backed, static report from saved final validation evidence."""
import base64
import csv
import html
import json
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/frontier_validation_20261029'


def main():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    proof=json.loads((OUT/'desktop_final_acceptance.json').read_text(encoding='utf-8'))
    def artifact(action,name,algorithm=None):
        task=next(t for t in proof['tasks'] if t['action']==action and (algorithm is None or t['algorithm']==algorithm))
        return json.loads((ROOT/'data/workbench_scalar10/jobs'/task['job_id']/'physics'/name).read_text(encoding='utf-8'))
    commercial=artifact('commercial_validation','commercial_validation.json')
    frozen=artifact('commercial_validation','frozen_model.json')
    life=[]
    for task in [t for t in proof['tasks'] if t['action']=='batterylife']:
        life.append(json.loads((ROOT/'data/workbench_scalar10/jobs'/task['job_id']/'physics/batterylife_split.json').read_text(encoding='utf-8')))
    mpc=next(t for t in proof['tasks'] if t['action']=='mpc')['metrics']
    can=next(t for t in proof['tasks'] if t['action']=='can')['metrics']
    eis_task=next(t for t in proof['tasks'] if t['mode']=='eis_fit')
    eis=json.loads((ROOT/'data/workbench_scalar10/jobs'/eis_task['job_id']/'physics/result.json').read_text(encoding='utf-8'))
    audit=json.loads((OUT/'independent_evidence_audit.json').read_text(encoding='utf-8'))
    protocols=list(csv.DictReader((OUT/'charging_loops/evaluations.csv').open(encoding='utf-8-sig')))
    conditions=commercial['tests'][:3];aging=commercial['tests'][3:]
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,axes=plt.subplots(2,2,figsize=(11,7.5),layout='constrained')
    axes[0,0].bar(['US06','UDDS','LA92'],[x['voltage_rmse_mV'] for x in conditions],color=['#c75b39','#287d8e','#287d8e'])
    axes[0,0].axhline(50,color='#555',linestyle='--',linewidth=1,label='Screening goal: 50 mV')
    axes[0,0].set(title='Condition holdout: same commercial cell',ylabel='Voltage RMSE (mV)');axes[0,0].legend(fontsize=8)
    axes[0,1].bar(np.arange(1,len(aging)+1),[x['voltage_rmse_mV'] for x in aging],color='#c75b39')
    axes[0,1].axhline(50,color='#555',linestyle='--',linewidth=1)
    axes[0,1].set(title='Chronological holdout: aged cell, no refit',xlabel='Recorded July discharge segment',ylabel='Voltage RMSE (mV)')
    scores={}
    for item in life:scores.update(item['scores'])
    order=['BatteryLife_CPMLP','BatteryLife_CPTransformer','Ridge_alpha100','training_mean']
    axes[1,0].bar(['CPMLP','CPTransformer','Ridge','Train mean'],[scores[k]['test_mae_cycles'] for k in order],color=['#287d8e','#68a4ad','#927bb5','#acb5bd'])
    axes[1,0].set(title='HUST: 16 unseen cells, first 10 cycles only',ylabel='RUL test MAE (cycles)')
    base=[r for r in protocols if r['algorithm']=='mobo_osd' and r['round']=='0'];new=[r for r in protocols if r['algorithm']=='mobo_osd' and r['round']!='0']
    for group,color,label in [(base,'#aab4bf','12 initial protocols'),(new,'#287d8e','6 MOBO-OSD queries')]:
        axes[1,1].scatter([float(r['charge_time_s'])/3600 for r in group],[float(r['max_temperature_C']) for r in group],c=color,label=label,s=38)
    axes[1,1].set(title='Calibrated charging simulation only',xlabel='Charge time: 30% to 80% SOC (h)',ylabel='Maximum case temperature (°C)');axes[1,1].legend(fontsize=8)
    fig.savefig(OUT/'validation_overview.png',dpi=170);plt.close(fig)
    blocks=[]
    def paragraph(text):blocks.append(('p',text))
    def heading(text):blocks.append(('h2',text))
    def table(headers,rows):blocks.append(('table',(headers,rows)))
    paragraph('四个项目已接入v0.3.13，并完成公开商用单体的辨识、留出回放、SOC估计、充电MPC、虚拟CAN及独立数值核验。当前达到可复核的软件与单体仿真闭环；尚未达到老师提出的硬件＋配套EIS/BMS整套系统，也没有证明自有材料或真实充电寿命得到改善。')
    heading('接入范围与真实执行边界')
    table(['项目','来源','本次真实执行','边界'],[
      ['MOBO-OSD','NeurIPS 2025 / LamNgo1/mobo-osd','作者GP、正交子问题、一阶Pareto扩展、Pareto集合和qHVI批选；两参数双目标','单次ask顺序运行，最大化转作者最小化；未重跑论文全套基准'],
      ['rMFBO','AISTATS 2025 / SchroDeCat/rMFBO','谱正则深核GP、特征投影RBF、ROI、长度尺度熵和成本分配','有限候选池、轻量训练/4次模型采样；显式MLL损失及缩放兼容修补；非原论文预算复现'],
      ['CAMO','NeurIPS 2025 / IceLab-X/CAMO','作者FiDE/CAR连续保真核、负对数似然训练和后验','采集为固定超参数、64分位幻想的有限池随机KG/成本适配；非原论文BOCA完整复现；b限制[0.05,3]'],
      ['BatteryLife','KDD 2025 / Ruifeng-Tan/BatteryLife','官方CPMLP、CPTransformer模型，真实公开曲线训练、验证选epoch、独立电芯测试','当前入口支持这两种架构；未声称复现全部模型/全部数据集和跨数据集论文结果']])
    paragraph('四个上游固定commit记录在configs/engineering_sources.lock.json。源仓库保持未修改；兼容副本、逐文件原始/执行SHA256、精确补丁和MIT许可证保存在每个任务的upstream目录。前沿环境使用隔离的BoTorch0.9.2/GPyTorch1.11，原有BoTorch0.18.1工程环境保持独立。')
    heading('公开商用电芯与验证设计')
    paragraph('主数据为Kollmeyer发布的Panasonic NCR18650PF 2.9Ah单体，DOI 10.17632/wykht8y7tg.1，CC BY4.0。已下载并逐文件核对发布方SHA256的44个文件，包含HPPC、慢充放电、驾驶工况、EIS及后期1C测试。整包ZIP返回403，因此采用官方单文件下载；没有把未下载整包的校验值当作已验证。')
    paragraph('3月HPPC用于1RC/2RC及热参数辨识，静置电压和记录Ah用于OCV表，容量固定为公开名义2.9Ah。Cycle1仅用于选型和滤波电压残差尺度，然后冻结。5月C20只作为容量诊断，不参与3月预测拟合。US06、UDDS、LA92作留出工况，7月三个文件形成12段时间留出。重复测试文件有9个缺失充电间隔，按原始时间断点>60s拆分，保留全部记录段，不跨缺测区间插值。')
    paragraph('电流在原时间轴积分后按1秒区间守恒重采样；不把会重置的Ah计数器当电流。原始0.1秒信号在1Hz时间点比较，覆盖所有已记录区间，未宣称保留全部高频峰值。首轮未拆分的结果保留在commercial目录；审计更正记录在冻结协议中，最终用更正后的商业验证任务。更正后未按测试误差调参数。')
    paragraph('筛查目标50mV电压RMSE、3°C温度RMSE、3% SOC RMSE属于本次自定工程目标，老师没有给出这些数字。SOC参考来自电流积分/名义容量，不能视作独立绝对SOC真值；同一电芯多段测试也不能当作15颗独立电芯。质量/比热分解中的48g是配置假定，可辨识的是总热容。')
    table(['留出工况','电压RMSE / mV','温度RMSE / °C','EKF SOC RMSE / %'],[
       [x['test'],f"{x['voltage_rmse_mV']:.2f}",f"{x['temperature_rmse_C']:.3f}",f"{100*x['ekf_rmse_soc']:.2f}"] for x in commercial['tests']])
    paragraph('Cycle1选择1RC；15段中电压2段、温度15段、SOC代理参考3段达到上述筛查目标。老化电芯电压误差明显增大，最高188.78mV；不能用软件算例通过来代替跨老化验证。')
    heading('闭环优化、充电与EIS诊断')
    paragraph('三种新选点算法各完成3轮建议—仿真—回传；共84次初始化和12次新增查询，合计96次已校准电芯仿真。输入是两段充电电流，目标为充电时间与温升；多保真用60/20/5秒求解控制间隔及声明成本代理1:3:12。新建议只在仿真中评估，优化器没有读取留出实测测试标签。3轮、单个随机种子不足以比较算法优劣，也不能声称已测快充/寿命提升。')
    paragraph(f"同电芯固定工作点RC的do-mpc/SOX/Thevenin控制链达到SOC {mpc['final_model_soc']:.5f}，EKF估计{mpc['final_estimated_soc']:.5f}，最高电压{mpc['max_voltage_V']:.4f}V、最高温度{mpc['max_temperature_C']:.2f}°C，求解回退0次、仿真越界0次。随后{can['frames']}帧经foxBMS DBC编码并完成python-can虚拟总线往返。该控制算例尚未检验参数不确定性/老化失配下的安全性，未连接实物BMS。")
    paragraph(f"4月EIS全谱已执行2RC拟合和Lin-KK，R0约{eis['parameters'][0]['value']*1000:.2f}mΩ；Lin-KK归一RMS残差{eis['lin_kk']['relative_rms']*100:.2f}%、最大残差{eis['lin_kk']['relative_max']*100:.2f}%，超过当前2%筛查阈值，参数可辨识性尚未评估。Digatron导出单位行只写[EIS]，Zreal1/Zimg1按mΩ转换属于有记录的量级假设，仍需核实。没有将此谱参数强接入更早的3月测试或宣称电化学机理已验证。")
    heading('BatteryLife独立电芯结果')
    paragraph('Panasonic数据没有完整寿命标签，因此另用HUST公开LFP/石墨1.1Ah电芯数据（DOI10.17632/nsc7hnsg4s.2，CC BY4.0）。按照官方预处理对7-5首两循环的问题提示，在训练前排除此电芯，剩76颗：协议组1–6为45训练、7–8为15验证、9–10为16测试。每颗电芯只有一个快照，特征只取前10循环；按充电/放电分段重采样到10×3×64。目标为作者给定第10循环RUL。')
    paragraph('特征/标签标准化只用训练电芯；验证集选择epoch，冻结后一次性计算测试。该划分由本平台固定，并非论文原始所有基准划分。HUST与Panasonic是不同体系，当前寿命模型不能直接充当Panasonic的SOH更新器。')
    table(['模型','独立测试MAE / 循环','RMSE / 循环','MAPE / %','R²'],[[k,f"{scores[k]['test_mae_cycles']:.2f}",f"{scores[k]['test_rmse_cycles']:.2f}",f"{scores[k]['test_mape_percent']:.2f}",f"{scores[k]['test_r2']:.3f}"] for k in order])
    paragraph('CPMLP与CPTransformer已接入且训练成功，但在本划分上未超过岭回归；不能据此声称新模型提升精度。测试集只有16颗电芯，当前是一次固定划分的描述性结果。')
    heading('独立核验与交付')
    paragraph('从79,642行逐点导出独立重算15段电压/SOC指标；另用完全独立的RK4等效电路与热方程重算完整US06，最大电压差5.54×10⁻⁷V、最大温度差1.24×10⁻⁵°C。电芯划分、指标、代码SHA和每个任务的依赖清单快照核验均通过。42项工程/新适配检查、63项相关回归通过；最终exe完成9项HTTP→WSL→结果下载验收。此处“独立”指数据留出与数值实现核对，不是第三方硬件认证。')
    paragraph('双击启动科研工作站.bat，进入“Panasonic PF公开电芯 · v0.3.13最终验证”方案；电池工程仿真中可选三种选点算法、BatteryLife及商用电芯验证。结果页可下载逐点CSV、冻结参数、划分清单、模型权重和来源证据。原有“我的回收石墨研究”方案保留。')
    heading('距离老师要求仍缺什么')
    table(['老师关注点','当前证据','剩余工作 / 优先级'],[
      ['有工业级电池作为仿真基础','公开Panasonic商用单体已贯通；仅1颗主电芯','P0：多颗同型号、不同温度和SOH的独立测试；不能用同电芯切片代替跨电芯'],
      ['仿真能优化','同冻结模型96次仿真/3种算法闭环可复核','P0：SOH/容量/阻抗自适应更新，温度依赖与误差区间；再用全新数据检验优化收益'],
      ['EIS+BMS配套软件','EIS诊断、SOX估计、MPC与虚拟CAN已运行','P0：确认仪器单位，排查Lin-KK失败/感抗与扩散结构；建立同电芯SOC×温度×SOH参数映射'],
      ['硬件＋配套系统','当前无硬件连接，foxBMS仅用DBC','P0：真实电芯/测试仪/BMS通信、同步时钟、限值联锁、HIL；所有软件仿真约束需实物复测'],
      ['整套仿真完成后再考虑论文','主单体链路完成；寿命/电池包数据体系尚未统一','P1：商用电芯包参数、单体差异/均衡/热耦合；旧liionpack仍为Chen2020参考，不是PF实包验证'],
      ['材料相关可解释研究','尚无自有材料→参数→全电池→寿命的配对证据','P1：补自有材料半电池/全电池/EIS与制备信息；做跨材料外推、预算匹配多种子基线后再提论文主张']])
    paragraph('下一步应优先补老化自适应、同型号多电芯验证和硬件接口。算法数量已足够搭建对照，继续堆更多名字不会自动修复当前189mV的老化误差。新检索到的Nature 2026 Discovery Learning（s41586-025-09951-7）把物理特征、主动学习与工业软包寿命结合，可作为后续材料—寿命方向；本次仅列为候选，未接入，也未核验其全部代码与数据适配条件。')
    heading('原始来源与复跑入口')
    links=[('MOBO-OSD论文','https://proceedings.neurips.cc/paper_files/paper/2025/hash/18e780ccbd60697ea4a0184f1e680660-Abstract-Conference.html'),
      ('rMFBO论文','https://proceedings.mlr.press/v258/zhang25g.html'),('CAMO论文','https://proceedings.neurips.cc/paper_files/paper/2025/hash/d2875f6d67841b7fe6c9ba55d9a6cab7-Abstract-Conference.html'),
      ('BatteryLife代码与论文入口','https://github.com/Ruifeng-Tan/BatteryLife'),('Panasonic公开原始数据','https://data.mendeley.com/datasets/wykht8y7tg/1'),('HUST公开原始数据','https://data.mendeley.com/datasets/nsc7hnsg4s/2'),
      ('Discovery Learning候选','https://www.nature.com/articles/s41586-025-09951-7')]
    blocks.append(('links',links))
    blocks.append(('code','python user_tools/install_engineering.py --inventory-only\npython user_tools/prepare_frontier_public.py panasonic\n# HUST：已有发布方our_data.zip后，用frontier环境运行prepare_frontier_public.py hust\n# Windows HTTP / 打包入口验收：\npython -m user_tools.workbench.smoke_frontier data/workbench_scalar10 --evidence outputs/frontier_validation_20261029/desktop_final_acceptance.json\n# 数值核验需WSL frontier环境：\npython user_tools/validate_frontier_evidence.py outputs/frontier_validation_20261029/desktop_final_acceptance.json --data data/workbench_scalar10\n# 充电优化闭环需WSL frontier环境，模型路径取已完成任务的physics/frozen_model.json：\npython user_tools/run_frontier_battery_loop.py --model <frozen_model.json> --out <new_output_directory>'))
    md=['# v0.3.13 商用电芯与四项目接入实测报告','', '验证日期：2026-10-29；软件接入成功与物理精度达标分别报告。','']
    body=['<h1>商用电芯与四项目接入实测报告</h1><p class="muted">v0.3.13 · 2026-10-29 · 本地运行证据</p>']
    png=(OUT/'validation_overview.png').read_bytes();body.append('<img alt="验证结果总览" src="data:image/png;base64,'+base64.b64encode(png).decode()+'">')
    for kind,value in blocks:
        if kind=='p':md.extend([value,'']);body.append('<p>'+html.escape(value)+'</p>')
        elif kind=='h2':md.extend(['## '+value,'']);body.append('<h2>'+html.escape(value)+'</h2>')
        elif kind=='table':
            headers,rs=value;md.extend(['| '+' | '.join(headers)+' |','|'+'|'.join(['---']*len(headers))+'|']+['| '+' | '.join(map(str,r))+' |' for r in rs]+[''])
            body.append('<div class="table"><table><thead><tr>'+''.join('<th>'+html.escape(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in r)+'</tr>' for r in rs)+'</tbody></table></div>')
        elif kind=='links':
            md.extend(['- ['+label+']('+url+')' for label,url in value]+['']);body.append('<ul>'+''.join('<li><a href="'+html.escape(url)+'">'+html.escape(label)+'</a></li>' for label,url in value)+'</ul>')
        elif kind=='code':md.extend(['```text',value,'```','']);body.append('<pre>'+html.escape(value)+'</pre>')
    (ROOT/'docs/frontier_commercial_validation_v0313_20261029.md').write_text('\n'.join(md),encoding='utf-8')
    document='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>商用电芯与四项目接入实测报告</title><style>body{font:16px/1.8 system-ui,"Microsoft YaHei",sans-serif;background:#f4f7fa;color:#203047;margin:0}main{max-width:1180px;margin:30px auto;background:white;padding:40px;border-radius:14px}h1{font-size:30px}h2{font-size:22px;margin-top:36px}p{margin:16px 0}.muted{color:#617387}img{width:100%;height:auto}.table{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px}th,td{border:1px solid #dce4eb;padding:10px;text-align:left;vertical-align:top}th{background:#edf4f6}pre{background:#172b3c;color:#f1f5f8;padding:20px;overflow:auto;border-radius:8px}a{color:#176f88}</style><main>'+''.join(body)+'</main></html>'
    (OUT/'report.html').write_text(document,encoding='utf-8')
    print('Report and figure created:',OUT/'report.html')


if __name__=='__main__':main()

"""Build the v0.3.14 report from final, independently audited desktop artifacts."""
import base64
import html
import json
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/adaptive_pf_20261029/desktop_final'


def main():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    proof=json.loads((OUT/'desktop_acceptance.json').read_text(encoding='utf-8'))
    if len(proof['tasks'])!=5:raise ValueError('Final desktop chain has not completed')
    def folder(action):return ROOT/'data/workbench_scalar10/jobs'/next(t['job_id'] for t in proof['tasks'] if t['action']==action)/'physics'
    def read(action,name):return json.loads((folder(action)/name).read_text(encoding='utf-8'))
    adaptive=read('commercial_adaptive','adaptive_validation.json');frozen=read('commercial_adaptive','adaptive_frozen_model.json')
    scores=read('commercial_adaptive','result.json')['metrics'];eis=read('eis_audit','eis_audit.json');safety=read('safety_bench','result.json')['metrics']
    mpc=read('mpc','result.json');can=read('can','result.json')['metrics'];inventory=json.loads((OUT/'hardware_inventory.json').read_text(encoding='utf-8'))
    independent=json.loads((OUT/'independent_audit.json').read_text(encoding='utf-8'))
    fresh=[r for r in adaptive['tests'] if r['role']=='fresh_condition_holdout'];aging=[r for r in adaptive['tests'] if r['role']=='historical_aging_regression']
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,axes=plt.subplots(2,2,figsize=(11.5,7.5),layout='constrained')
    labels=['0C (1 record)','10C (3 records)','25C (3 records)'];positions=np.arange(3)
    groups=[[r for r in fresh if r['nominal_temperature_C']==t] for t in [0,10,25]]
    axes[0,0].bar(positions-.18,[np.mean([r['baseline_voltage_rmse_mV'] for r in g]) for g in groups],.36,label='25C baseline',color='#aab5c0')
    axes[0,0].bar(positions+.18,[np.mean([r['voltage_rmse_mV'] for r in g]) for g in groups],.36,label='Temperature table',color='#237d90')
    axes[0,0].set_xticks(positions,labels);axes[0,0].set(title='7 condition holdouts, one physical cell',ylabel='Mean voltage RMSE (mV)');axes[0,0].legend(fontsize=8)
    x=np.arange(1,len(aging)+1)
    axes[0,1].plot(x,[r['baseline_voltage_rmse_mV'] for r in aging],'o-',label='Before prior-cycle calibration',color='#aab5c0')
    axes[0,1].plot(x,[r['voltage_rmse_mV'] for r in aging],'o-',label='After calibration',color='#237d90')
    axes[0,1].axhline(50,color='#be613b',linestyle='--',linewidth=1,label='50mV screening goal')
    axes[0,1].set(title='10 aging records: historical regression',xlabel='Later discharge segment',ylabel='Voltage RMSE (mV)');axes[0,1].legend(fontsize=8)
    x=np.arange(1,15);spectra=eis['spectra']
    axes[1,0].plot(x,[s['baseline']['relative_rms']*100 for s in spectra],'o-',color='#aab5c0',label='Without series C')
    axes[1,0].plot(x,[s['augmented']['relative_rms']*100 for s in spectra],'o-',color='#237d90',label='With series C')
    axes[1,0].scatter([i+1 for i,s in enumerate(spectra) if not s['augmented']['screening_pass']],
        [s['augmented']['relative_rms']*100 for s in spectra if not s['augmented']['screening_pass']],marker='x',s=90,color='#bd5739',label='Mu cutoff not reached')
    axes[1,0].set(title='14 full spectra: no point deletion',xlabel='Spectrum index',ylabel='Lin-KK relative RMS (%)');axes[1,0].legend(fontsize=8)
    trace=read('safety_bench','safety_trace.json')
    axes[1,1].step([r['time_s'] for r in trace],[r['command_charge_A'] for r in trace],where='post',color='#237d90')
    axes[1,1].axvline(5,color='#bd5739',linestyle='--',label='Injected over-voltage; stop latched')
    axes[1,1].set(title='SIL only: zero physical commands',xlabel='Simulation time (s)',ylabel='Requested charge current (A)');axes[1,1].legend(fontsize=8)
    fig.savefig(OUT/'adaptive_overview.png',dpi=170);plt.close(fig)
    blocks=[]
    def p(text):blocks.append(('p',text))
    def h(text):blocks.append(('h',text))
    def table(headers,rows):blocks.append(('table',(headers,rows)))
    p('本轮继续补老化/温度适应、EIS单位与一致性诊断，并把更新参数接回MPC和虚拟CAN。软件已升级v0.3.14。当前仍是同一公开商用单体的离线研究与软件验证，尚未连接真实EIS仪、测试仪或BMS板。')
    h('本轮实际结果')
    table(['项目','旧模型/设置','更新后','结论'],[
      ['7条新评分工况，逐记录平均电压RMSE',f"{scores['fresh_baseline_mean_voltage_rmse_mV']:.2f}mV",f"{scores['fresh_mean_voltage_rmse_mV']:.2f}mV",'6/7达到本次50mV目标；同一电芯，不能算7颗独立电芯'],
      ['10段老化历史回归，逐记录平均电压RMSE',f"{scores['aging_baseline_mean_voltage_rmse_mV']:.2f}mV",f"{scores['aging_mean_voltage_rmse_mV']:.2f}mV",'7/10达到50mV目标；属于已见数据回归，不是新增独立寿命验证'],
      ['EIS第1谱全频段Lin-KK RMS','2.486%',f"{100*spectra[0]['augmented']['relative_rms']:.3f}%",'加入低频串联电容后，模型失配残差明显降低'],
      ['全部14谱严格筛查','原设置未同时满足RMS/最大残差/μ条件','12/14通过','第10、13谱在当前阶数上限下μ未达到0.85；低残差不能单独替代阶数诊断'],
      ['保护逻辑SIL','独立保护验证器',f"{safety['cases_passed']}/{safety['safety_cases']}用例通过",'锁存后请求电流归零，仿真SOC停止增长；没有实物控制命令']])
    h('数据划分、修正与计分边界')
    p('新增下载10个官方文件并核对发布方SHA256：0°C/10°C各1条HPPC用于辨识，各1条Cycle1用于选择模型，US06/UDDS/LA92用于后续评价。25°C参考模型保持v0.3.13原参数，并新增此前未评分的HWFETa、HWFETb、NN记录。模型选择只看3条Cycle1与7月重复放电第1段；参数在后续评价之前冻结。')
    p('开发首轮在0°C LA92遇到时间轴检查停止，此前0°C US06、UDDS两条已经输出过指标。本报告把这两条明确列为开发已见回归，剩余7条列为新评分工况，其中LA92做过时间轴结构核对。所有记录均保留，未按测试误差筛除。协议及修正说明见configs/commercial_pf_adaptive_20261029.json；最终桌面验收是同一模型的重复执行，不算又取得新的独立样本。')
    p('0°C/10°C箱温字段缺失时，显式使用文件夹标称设定值，并保留缺失比例；电芯实测表面温度有效。发现的约60秒间隔是稀疏休息日志及毫秒级时间抖动，不能当作缺失充电。仿真仍走1Hz，但稀疏区间只在原始观测附近更新电压和计分，不制造每秒一次的虚假观测；在线滤波温度按已到达样本保持。真正断开区间使用>90秒检查。')
    p('v0.3.13的历史表按均匀重采样点计分；本轮按有效观测掩码重新比较新旧模型，旧模型数值因此略有变化。表中的前后结果使用完全相同的输入、初态和计分口径。开环电压预测不读取测试电压；增广EKF会读取当时的传感器电压，单独报告SOC代理参考误差和更新前电压创新，不能把滤波后的拟合电压当作独立预测精度。')
    table(['记录','用途','旧电压RMSE/mV','更新RMSE/mV','温度RMSE/°C','SOC代理RMSE/%'],[
      [r['test'],{'fresh_condition_holdout':'新评分工况','development_exposed_regression':'开发已见回归','historical_aging_regression':'老化历史回归'}[r['role']],
       f"{r['baseline_voltage_rmse_mV']:.2f}",f"{r['voltage_rmse_mV']:.2f}",f"{r['temperature_rmse_C']:.2f}",f"{100*r['ekf_soc_proxy_rmse']:.2f}"] for r in adaptive['tests']])
    h('容量和阻抗更新究竟代表什么')
    fit=frozen['aging_fit']
    p(f"7月22日已完成参考放电给出的交付容量约{fit['usable_discharge_capacity_Ah']:.4f}Ah；基于该记录和后续松弛段辨识的模型容量参数为{fit['model_capacity_Ah']:.4f}Ah。两者不同，不能把模型容量/额定2.9Ah直接解释为独立测准的SOH。R0比例约{fit['aging_scales'][0]:.3f}，R1比例和时间常数比例分别达到0.25与4.0的设定边界；参数存在耦合，尚未证明唯一可辨识，更不能据此判定具体衰退机理。")
    p('这是上一完整循环校准后预测后续记录，加上SOX增广EKF的有激励R0在线修正；没有声称在完全未知容量、没有参考循环时自动得到准确SOH。SOC对照仍是电流积分/训练容量的代理参考，不是独立SOC仪器真值。热参数仍沿用25°C辨识，当前最差温度RMSE约5.44°C，尚未全部达到自定3°C目标。')
    h('EIS单位证据和仍未解决的问题')
    anomalies=sum(s['unit']['amplitude_points_above_manufacturer_1percent'] for s in spectra)
    maximum=max(s['unit']['amplitude_ratio_relative_max'] for s in spectra)*100
    p('Digatron厂家资料的阻抗坐标采用mΩ；原始导出的复阻抗模值与Betrag、相位与Phase相符，多数频点也满足“mvIdeal×VRelativ÷AAmplitude”的电压/电流幅值关系。14条谱的中位尺度证据支持mΩ到Ω的0.001转换，这比仅凭经验量级更可复核，但仍不是仪器计量校准。')
    p(f"有{anomalies}个频点的幅值字段冗余差异超过厂家1%幅值标称精度，最大约{maximum:.2f}%；原始复阻抗点没有被删除或修正。异常详情保存在每条谱unit.amplitude_anomaly_records中，仍需核对采集/导出字段。所有14谱共756个频点全频段保留；增强Lin-KK的RMS均低于0.8%，但第10、13谱尚未达到当前阶数上限下的μ截止条件。残差降低不证明数据必然线性、稳态或材料机理成立。")
    p('低频串联电容按impedance.py官方文档用于没有低频截距的数据；保持相同μ0.85和预先声明的阶数上限。另用列缩放SVD独立复算线性KK，并做固定阶数、交错频率交叉验证，未靠删点或更换阈值获取通过。')
    h('更新参数已接回控制链路')
    p(f"应用内新增“用更新参数运行MPC仿真”：从本方案已完成的更新任务读取冻结模型与导出配置，校验SHA，跨方案父任务被拒绝。控制器和滤波器仍用固定SOC工作点RC；仿真电芯按SOC参数表变化。该算例使用25°C老化阻抗参数延伸，尚未验证老化×温度的联合参数面。最终模型SOC{mpc['metrics']['final_model_soc']:.5f}、估计SOC{mpc['metrics']['final_estimated_soc']:.5f}，最高{mpc['metrics']['max_voltage_V']:.4f}V/{mpc['metrics']['max_temperature_C']:.2f}°C，仿真越界与求解回退均为0；随后{can['frames']}帧进入foxBMS DBC与虚拟CAN往返。")
    p('独立SIL保护验证器覆盖过压、欠压、过温、过流、陈旧/缺失测量、时间戳/序列异常、设备故障和命令越限，并检查锁存后不自动恢复。SIL验证的是软件状态机与仿真执行效果，尚未测真实采集延迟、驱动响应或硬件保护时延。')
    p(f"设备型号仍未知。只做了Windows串口元数据枚举，得到{len(inventory['serial_ports'])}项；CAN/VISA保持未配置，不能据此断言没有其他设备。新增configs/hardware_connection.template.json，物理执行默认关闭，未实现或发送未知设备的控制命令。")
    h('验收与下一步差距')
    p('62项工程/新功能检查、63项相关回归和25项模块清单/依赖图测试通过；不是全仓全部测试声明。最终exe完成5项HTTP→WSL→下载任务：参数更新、EIS审计、SIL、更新参数MPC、CAN。独立脚本重新计算19条记录的有效观测指标，重算完整0°C US06的RK4方程，复核两求解器、EIS-SVD、SIL与代码/环境快照。每个任务保存可审查的代码副本与SHA。')
    table(['仍有缺口','当前证据与下一步'],[
      ['高动态和后期老化','新评分10°C US06约74.82mV；后期3段老化仍超过50mV，需要新的校准策略与全新数据验证，不能反复调同一批留出集'],
      ['低温热模型','最差温度RMSE约5.44°C；需用校准记录辨识温度相关热参数，再保留新的记录验证'],
      ['参数可辨识性与盲SOH','容量/阻抗参数耦合且部分触边；需要额外倍率/脉冲/慢速OCV或可信参考容量，不把参数拟合当机理证据'],
      ['EIS与真实仪器','2条μ阶数诊断待查，5个幅值冗余异常点未修正；真实设备单位、采样同步与校准仍需联调'],
      ['跨电芯、寿命和电池包','主验证仍为1颗PF；BatteryLife仍用HUST另一体系，liionpack仍是Chen2020参考，未宣称统一为PF全寿命实包'],
      ['硬件整套系统','设备型号/接口未知，当前是离线回放、仿真MPC、虚拟CAN和SIL；尚未达到实物EIS+BMS/HIL闭环']])
    p('启动科研工作站.bat已指向v0.3.14最终版，结果在“PF温度与老化更新 · v0.3.14最终验证”方案。此前方案和失败调试记录保留；原仿真核心battery_sim未修改。')
    links=[('公开原始数据与CC BY4.0来源','https://data.mendeley.com/datasets/wykht8y7tg/1'),('Digatron EIS-Meter厂家资料','https://www.digatron.com/Portals/38/Images/documents/PRODUKTBLATT_EIS_EN.PDF'),('impedance.py Lin-KK官方方法文档','https://impedancepy.readthedocs.io/en/latest/_modules/impedance/validation.html')]
    blocks.append(('links',links))
    md=['# v0.3.14 温度/SOH更新、EIS复核与控制链验收','', '日期：2026-10-29；新增独立记录、开发已见回归与历史老化回归分别计分。','']
    png=(OUT/'adaptive_overview.png').read_bytes();body=['<h1>温度/SOH更新、EIS复核与控制链验收</h1><p>v0.3.14 · 2026-10-29</p><img alt="结果总览" src="data:image/png;base64,'+base64.b64encode(png).decode()+'">']
    for kind,value in blocks:
        if kind=='p':md += [value,''];body.append('<p>'+html.escape(value)+'</p>')
        elif kind=='h':md += ['## '+value,''];body.append('<h2>'+html.escape(value)+'</h2>')
        elif kind=='table':
            headers,rows=value;md += ['| '+' | '.join(headers)+' |','|'+'|'.join(['---']*len(headers))+'|']+['| '+' | '.join(map(str,r))+' |' for r in rows]+['']
            body.append('<div class="scroll"><table><tr>'+''.join('<th>'+html.escape(h)+'</th>' for h in headers)+'</tr>'+''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in row)+'</tr>' for row in rows)+'</table></div>')
        elif kind=='links':
            md += ['- ['+label+']('+url+')' for label,url in value]+[''];body.append('<ul>'+''.join('<li><a href="'+url+'">'+html.escape(label)+'</a></li>' for label,url in value)+'</ul>')
    (ROOT/'docs/adaptive_pf_v0314_20261029.md').write_text('\n'.join(md),encoding='utf-8')
    document='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>PF温度与老化更新验证</title><style>body{font:16px/1.8 system-ui,"Microsoft YaHei",sans-serif;background:#f3f6fa;color:#213047}main{max-width:1200px;margin:30px auto;background:white;padding:36px;border-radius:12px}img{width:100%}h2{margin-top:32px;font-size:22px}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:9px;border:1px solid #dce5ed;text-align:left;vertical-align:top}th{background:#eaf3f5}a{color:#176b84}</style><main>'+''.join(body)+'</main></html>'
    (OUT/'report.html').write_text(document,encoding='utf-8');print(OUT/'report.html')


if __name__=='__main__':main()

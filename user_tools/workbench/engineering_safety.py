"""Software-in-the-loop charging-interlock verification with a Thevenin reference plant."""
import copy
import json
from pathlib import Path
import numpy as np

from user_tools.workbench.engineering_common import ROOT,finish,save
from user_tools.workbench.engineering_commercial import parameters
from user_tools.workbench.engineering_adaptive import reference
from user_tools.workbench.hardware_readiness import SafetyInterlock


def run_safety(config,out):
    import thevenin
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    limits=config['limits'];amp=min(1.,limits['current_max_A']/2)
    healthy=dict(sequence=1,measurement_time_s=0.,voltage_V=3.8,temperature_C=25.,current_A=-amp,device_fault=False)
    cases=[('healthy',{},0.,1.,False),('over_voltage',{'voltage_V':limits['voltage_max_V']+.01},0.,1.,True),
      ('under_voltage',{'voltage_V':limits['voltage_min_V']-.01},0.,1.,True),
      ('over_temperature',{'temperature_C':limits['temperature_max_C']+.1},0.,1.,True),
      ('over_current',{'current_A':-limits['current_max_A']-.1},0.,1.,True),
      ('stale_measurement',{},limits['stale_timeout_s']+.01,1.,True),('future_timestamp',{'measurement_time_s':.1},0.,1.,True),
      ('invalid_value',{'temperature_C':float('nan')},0.,1.,True),('device_fault',{'device_fault':True},0.,1.,True),
      ('command_limit',{},0.,limits['current_max_A']+.1,True)]
    rows=[]
    for name,override,now,command,expected in cases:
        if command==1.:command=amp
        gate=SafetyInterlock(limits);frame={**healthy,**override};result=gate.step(frame,now,command)
        if result['stop_latched']!=expected or (expected and result['command_charge_A']!=0.):raise RuntimeError('Interlock case failed: '+name)
        rows.append(dict(case=name,expected_stop=expected,actual_stop=result['stop_latched'],command_charge_A=result['command_charge_A'],reasons=';'.join(result['reasons']),physical_command_sent=False))
    for name,frame in [('missing_measurement',{k:v for k,v in healthy.items() if k!='voltage_V'}),('repeated_sequence',healthy)]:
        gate=SafetyInterlock(limits)
        if name=='repeated_sequence':gate.step(healthy,0.,amp)
        result=gate.step(frame,0.,amp)
        if not result['stop_latched'] or result['command_charge_A']!=0.:raise RuntimeError('Interlock failed: '+name)
        recovered=gate.step({**healthy,'sequence':2,'measurement_time_s':.1},.1,amp)
        if recovered['command_charge_A']!=0.:raise RuntimeError('Latched fault auto-restarted')
        rows.append(dict(case=name,expected_stop=True,actual_stop=result['stop_latched'],command_charge_A=result['command_charge_A'],reasons=';'.join(result['reasons']),physical_command_sent=False))
    base,_=reference();p=parameters(base,.5,25.,25.);plant=thevenin.Prediction(p);plant.set_options(rtol=1e-8,atol=1e-10)
    state=thevenin.TransientState(.5,298.15,0.,np.zeros(1));gate=SafetyInterlock(limits);trace=[];soc_at_stop=None
    for tick in range(10):
        sensor_v=float(state.voltage) if tick else p['ocv'](.5)
        injected=tick==4
        frame=dict(sequence=tick,measurement_time_s=float(tick),voltage_V=limits['voltage_max_V']+.05 if injected else sensor_v,
                   temperature_C=float(state.T_cell-273.15),current_A=-amp if not gate.latched else 0.)
        result=gate.step(frame,float(tick),amp)
        if tick==4:soc_at_stop=float(state.soc)
        state=plant.take_step(state,-result['command_charge_A'],1.)
        trace.append(dict(time_s=float(tick+1),injected_sensor_fault=injected,command_charge_A=result['command_charge_A'],soc=float(state.soc),voltage_V=float(state.voltage),stop_latched=result['stop_latched']))
    if max(r['command_charge_A'] for r in trace[4:])!=0. or abs(float(state.soc)-soc_at_stop)>1e-10:raise RuntimeError('Simulated actuator did not stop')
    save(out/'safety_trace.json',trace);save(out/'hardware_template.json',json.loads((ROOT/'configs/hardware_connection.template.json').read_text(encoding='utf-8')))
    save(out/'safety_cases.json',rows)
    return finish(config,out,dict(kind='engineering',title='设备接入准备 · 故障保护SIL',engine='latched interlock + Thevenin reference plant',
       metrics=dict(safety_cases=len(rows),cases_passed=len(rows),latched_zero_current_steps=6,physical_commands_sent=0,
                    soc_change_after_stop=abs(float(state.soc)-soc_at_stop)),
       details={'scope':'纯软件故障注入：过压/欠压/过温/过流、缺测/陈旧/时间戳/序列异常和命令越限。保护锁存后仿真电流归零，Thevenin SOC停止增长。未知设备接口仅提供配置模板，未连接仪器或发送物理控制命令，未测真实保护响应时延。'}),rows,
       [dict(name='SIL故障注入后的请求充电电流',y_label='充电电流 (A)',primary='仿真命令',secondary='参考',points=[[r['time_s'],r['command_charge_A'],None] for r in trace])],['thevenin','numpy'])

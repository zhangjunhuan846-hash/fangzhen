"""Read-only host inventory and a latched software interlock; no actuator driver."""
import copy
import json
import math
from pathlib import Path
import subprocess
import sys


class SafetyInterlock:
    def __init__(self,limits):
        self.limits=copy.deepcopy(limits);self.latched=False;self.reasons=[];self.last_sequence=-1;self.last_time=-1.;self.last_now=-1.

    def step(self,frame,now_s,requested_charge_A):
        reasons=[]
        if not isinstance(now_s,(int,float)) or isinstance(now_s,bool) or not math.isfinite(now_s) or now_s<0 or now_s<self.last_now:
            self.latched=True;self.reasons=list(dict.fromkeys(self.reasons+['invalid_controller_clock']))
            return dict(command_charge_A=0.,stop_latched=True,reasons=list(self.reasons),physical_command_sent=False)
        self.last_now=now_s
        required=['sequence','measurement_time_s','voltage_V','temperature_C','current_A']
        if not isinstance(frame,dict) or any(k not in frame for k in required):reasons.append('missing_measurement')
        elif any(isinstance(frame[k],bool) or not isinstance(frame[k],(int,float)) or not math.isfinite(frame[k]) for k in required):reasons.append('invalid_measurement')
        else:
            if frame['sequence']!=int(frame['sequence']) or frame['sequence']<=self.last_sequence:reasons.append('out_of_order_sequence')
            if frame['measurement_time_s']<self.last_time or frame['measurement_time_s']>now_s:reasons.append('invalid_timestamp')
            if now_s-frame['measurement_time_s']>self.limits['stale_timeout_s']:reasons.append('stale_measurement')
            if frame['voltage_V']>self.limits['voltage_max_V']:reasons.append('over_voltage')
            if frame['voltage_V']<self.limits['voltage_min_V']:reasons.append('under_voltage')
            if frame['temperature_C']>self.limits['temperature_max_C']:reasons.append('over_temperature')
            if abs(frame['current_A'])>self.limits['current_max_A']:reasons.append('over_current')
            if frame.get('device_fault',False):reasons.append('device_fault')
            self.last_sequence=max(self.last_sequence,frame['sequence']);self.last_time=max(self.last_time,frame['measurement_time_s'])
        if not isinstance(now_s,(int,float)) or isinstance(now_s,bool) or not math.isfinite(now_s):reasons.append('invalid_controller_clock')
        if not isinstance(requested_charge_A,(int,float)) or isinstance(requested_charge_A,bool) or not math.isfinite(requested_charge_A) or not 0<=requested_charge_A<=self.limits['current_max_A']:
            reasons.append('invalid_current_command')
        if reasons:self.latched=True;self.reasons=list(dict.fromkeys(self.reasons+reasons))
        return dict(command_charge_A=0. if self.latched else float(requested_charge_A),stop_latched=self.latched,
                    reasons=list(self.reasons),physical_command_sent=False)


def inventory(project):
    """Enumerate Windows device metadata only. Never opens COM, VISA or CAN resources."""
    template=Path(project)/'configs/hardware_connection.template.json'
    result=dict(hardware_connected=False,actuator_enabled=False,device_model=None,inventory_scope='read-only serial-port metadata; CAN/VISA resources not opened',
                operating_system=sys.platform,serial_ports=[],can_status='not_configured',visa_status='not_configured',template=str(template))
    if sys.platform=='win32':
        script="[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); @(Get-CimInstance Win32_SerialPort | Select-Object DeviceID,Name,PNPDeviceID) | ConvertTo-Json -Compress"
        try:
            r=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],capture_output=True,timeout=12,
                             creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if r.returncode:raise OSError(r.stderr.decode('utf-8',errors='replace')[-400:])
            text=r.stdout.decode('utf-8-sig').strip();ports=json.loads(text) if text else []
            result['serial_ports']=ports if isinstance(ports,list) else [ports] if ports else []
            result['serial_inventory_status']='enumerated'
        except (OSError,ValueError,subprocess.TimeoutExpired) as exc:result.update(serial_inventory_status='unavailable',inventory_error=str(exc))
    else:result['serial_inventory_status']='host_not_windows'
    result['missing_configuration']=['physical cell identifier','tester/EIS/BMS model','transport and address','protocol/DBC mapping','independent hardware protection and interlock verification']
    return result

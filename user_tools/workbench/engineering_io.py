"""PyProBE input normalization and actual foxBMS DBC / virtual CAN transport."""
import hashlib
import re
from pathlib import Path
import numpy as np

from user_tools.workbench.engineering_common import ROOT, finish, save
from user_tools.workbench.engineering_contracts import csv_rows, finite


def run_cycler(config, out, raw=None):
    import polars as pl
    from pyprobe.result import Result
    if raw is None:
        rows = [{'time_s': i*10., 'current_A': 1., 'voltage_V': 4.1 - i*.004,
                 'capacity_Ah': i/360., 'cycle': 1} for i in range(91)]
    else:
        rows = csv_rows(raw)
    required = {'time_s', 'current_A', 'voltage_V', 'capacity_Ah', 'cycle'}
    if not required <= set(rows[0]):
        raise ValueError('PyProBE输入需time_s,current_A,voltage_V,capacity_Ah,cycle；电流为放电正。')
    clean_rows = []
    last = {}
    for row in rows:
        point = {key: finite(row[key], key) for key in required}
        if point['cycle'] != int(point['cycle']) or point['cycle'] < 0:
            raise ValueError('cycle必须为非负整数。')
        cycle = int(point['cycle'])
        if cycle in last and point['time_s'] <= last[cycle]:
            raise ValueError('每个循环中的时间需严格递增。')
        last[cycle] = point['time_s']
        clean_rows.append({'Time [s]': point['time_s'], 'Current [A]': -point['current_A'],
                           'Voltage [V]': point['voltage_V'], 'Capacity [Ah]': point['capacity_Ah'], 'Cycle': cycle})
    # PyProBE uses charge-positive; the platform CSV is discharge-positive.
    data = Result(lf=pl.DataFrame(clean_rows), info={'cell_id': config['cell']['cell_id'],
                  'source': config.get('source', 'synthetic'), 'current_convention': 'positive_charge'})
    t = data.get('Time [s]')
    voltage = data.get('Voltage [V]')
    frame = data.collect()
    frame.write_csv(out / 'pyprobe_normalized.csv')
    definitions = {'time_s': 's', 'voltage_V': 'V', 'current_A': 'A positive discharge -> PyProBE positive charge',
                   'capacity_Ah': 'Ah (declared measured counter, not inferred from units)'}
    save(out / 'pyprobe_info.json', {'info': data.info, 'units': definitions})
    result = {'kind': 'engineering', 'title': 'PyProBE标准化数据与循环索引', 'columns': data.columns,
              'metrics': {'rows': len(frame), 'cycles': len(last), 'voltage_min_V': float(np.min(voltage)),
                          'voltage_max_V': float(np.max(voltage))},
              'scope': '真实PyProBE Result对象、列提取和CSV导出。保留输入容量计数器；电流显式从平台放电正转换成PyProBE充电正，未据此宣称任意测试仪原始格式已适配。'}
    return finish(config, out, result, frame.to_dicts(),
                  [{'name': '标准化电压', 'points': [[float(ti), float(vi), None] for ti, vi in zip(t, voltage)]}],
                  ['PyProBE-Data', 'polars'])


def run_can(config, out, raw=None):
    import can
    import cantools
    path = ROOT / 'data/vendor/foxbms-2/tools/dbc/foxbms.dbc'
    if not path.is_file():
        raise ValueError('未安装固定foxBMS DBC来源，请运行工程环境安装脚本。')
    original = path.read_text(encoding='utf-8-sig')
    # Upstream contains VAL_ declarations for deleted messages. New cantools
    # rejects these before its strict flag is applied. Remove only orphan VAL_
    # metadata in memory, retain and hash the untouched upstream source.
    defined = {int(x) for x in re.findall(r'^BO_\s+(\d+)\s', original, re.M)}
    removed = []
    def drop_orphan(match):
        if int(match.group(1)) not in defined:
            removed.append(match.group(0))
            return ''
        return match.group(0)
    compatible = re.sub(r'^VAL_\s+(\d+)\s+[^\n]*', drop_orphan, original, flags=re.M)
    save(out / 'dbc_compatibility.json', {'removed_orphan_VAL_declarations': removed,
         'original_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
         'compatible_text_sha256': hashlib.sha256(compatible.encode()).hexdigest()})
    database = cantools.database.load_string(compatible, database_format='dbc', strict=True)
    catalog = [{'name': m.name, 'can_id': m.frame_id, 'length': m.length,
                'signals': [{'name': s.name, 'unit': s.unit, 'minimum': s.minimum, 'maximum': s.maximum}
                            for s in m.signals]} for m in database.messages]
    save(out / 'can_database.json', {'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'messages': catalog})
    channel = 'fangzhen-isolated-' + out.name
    rows = []
    with can.Bus(interface='virtual', channel=channel, receive_own_messages=False) as sender, \
            can.Bus(interface='virtual', channel=channel) as receiver:
        if config.get('can_telemetry'):
            telemetry=config['can_telemetry']
            if raw is not None or not 2 <= len(telemetry) <= 1001:
                raise ValueError('遥测桥接需要2–1001点，不能同时输入CSV。')
            message=database.get_message_by_name('f_CellVoltages')
            frames=[]
            for sample in telemetry:
                values={'f_CellVoltages_Mux':0, 'CellVoltage_000':round(1000*finite(sample['voltage_V'],'voltage_V',0,8.191)),
                        **{f'CellVoltage_{i:03}_invalidFlag':0 if i==0 else 1 for i in range(4)},
                        **{f'CellVoltage_{i:03}':0 for i in range(1,4)}}
                frames.append({'time_s':sample['time_s'],'can_id':message.frame_id,'data_hex':message.encode(values).hex()})
        elif raw is None:
            # A data/telemetry frame, never a bootloader or state command.
            message = database.get_message_by_name(config.get('message_name', 'f_CellVoltages'))
            provided = config.get('signals', {})
            values = {}
            for signal in message.signals:
                if signal.is_multiplexer:
                    mux=finite(provided.get(signal.name,signal.minimum or 0),signal.name,0)
                    if int(mux)!=mux:raise ValueError('CAN复用索引需为整数。')
                    values[signal.name] = int(mux)
                elif signal.name in provided:
                    values[signal.name] = finite(provided[signal.name], signal.name)
                elif signal.unit == 'mV' and signal.name.startswith('CellVoltage_'):
                    values[signal.name] = 3700
                else:
                    values[signal.name] = signal.minimum if signal.minimum is not None else 0
            values = message.gather_signals(values)
            payload = message.encode(values)
            frames = [{'time_s': 0., 'can_id': message.frame_id, 'data_hex': payload.hex()}]
        else:
            frames = csv_rows(raw)
            if not {'time_s', 'can_id', 'data_hex'} <= set(frames[0]) or len(frames) > 10000:
                raise ValueError('回放需time_s,can_id,data_hex，最多10000帧。')
        previous_time = None
        for frame in frames:
            timestamp=finite(frame['time_s'],'time_s',0)
            if previous_time is not None and timestamp < previous_time:
                raise ValueError('CAN日志时间必须不减。')
            previous_time=timestamp
            ident = int(str(frame['can_id']), 0) if isinstance(frame['can_id'], str) else int(frame['can_id'])
            payload = bytes.fromhex(frame['data_hex'])
            if not 0 <= ident <= 0x1FFFFFFF or len(payload) > 64:
                raise ValueError('CAN编号或载荷长度不合法。')
            definition = database.get_message_by_frame_id(ident)
            if len(payload) != definition.length:
                raise ValueError('CAN载荷长度与DBC不一致。')
            sender.send(can.Message(arbitration_id=ident, is_extended_id=definition.is_extended_frame,
                                    data=payload, is_fd=len(payload) > 8))
            received = receiver.recv(timeout=1)
            if received is None or received.arbitration_id != ident or bytes(received.data) != payload:
                raise RuntimeError('虚拟CAN往返不一致。')
            decoded = database.decode_message(ident, received.data, decode_choices=False)
            for name, value in decoded.items():
                signal = definition.get_signal_by_name(name)
                rows.append({'time_s': finite(frame['time_s'], 'time_s', 0), 'can_id': ident,
                             'message': definition.name, 'signal': name, 'value': float(value), 'unit': signal.unit or '',
                             'data_hex': payload.hex()})
    result = {'kind': 'engineering', 'title': 'foxBMS原始DBC + python-can虚拟总线回放',
              'metrics': {'dbc_messages': len(catalog), 'frames': len(frames), 'decoded_signals': len(rows)},
              'dbc_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
              'transport': 'python-can virtual / process-local only',
              'timing': 'CSV row order and declared timestamps preserved; no wall-clock pacing',
              'scope': '实际解析foxBMS DBC并执行编码/虚拟发送/接收/解码；保存全部信号和单位。没有向物理CAN口发送，未烧录foxBMS固件；真实板卡与设备型号仍需匹配。'}
    return finish(config, out, result, rows, packages=['python-can', 'cantools'])

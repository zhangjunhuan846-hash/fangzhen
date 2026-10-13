"""Conservative cycler CSV normalization. Never smooth or reconstruct signals."""
import csv
import io
import math
import statistics
from datetime import datetime


ALIASES={
    'time':['time_s','test_time_s','Total Time(s)','Program Duration#s','总时间(s)','总时间（s）','测试时间(s)','Time(s)'],
    'voltage':['voltage_V','Voltage(V)','Voltage#V','电压(V)','电压（V）','Voltage(mV)','电压(mV)'],
    'current':['current_A','Current(A)','Current#A','电流(A)','Current(mA)','电流(mA)','current_mA'],
}


def parse_time(value):
    value=value.strip()
    if ':' not in value:return float(value)
    parts=value.split(':')
    if len(parts)!=3:raise ValueError('持续时间需为h:m:s')
    h,m,s=map(float,parts)
    if h<0 or not 0<=m<60 or not 0<=s<60:raise ValueError('持续时间范围不合法')
    return h*3600+m*60+s


def normalize_csv(raw,config=None):
    config=config or {};encoding=None
    for codec in ['utf-8-sig','gb18030']:
        try:text=raw.decode(codec);encoding=codec;break
        except UnicodeDecodeError:pass
    if encoding is None:raise ValueError('仅支持UTF-8或GB18030文本CSV。')
    lines=text.splitlines();header_index=None;headers=None;delimiter=None
    for index,line in enumerate(lines[:100]):
        for sep in [',','\t',';']:
            candidate=next(csv.reader([line],delimiter=sep));candidate=[x.strip() for x in candidate]
            volts=config.get('voltage_column') or next((x for x in ALIASES['voltage'] if x in candidate),None)
            times=config.get('time_column') or next((x for x in ALIASES['time'] if x in candidate),None)
            if volts in candidate and times in candidate:
                header_index=index;headers=candidate;delimiter=sep;break
        if headers is not None:break
    if headers is None:raise ValueError('未识别时间、电压列。请填写原始列名；文件前100行内需有表头。')
    if len(set(headers))!=len(headers):raise ValueError('表头存在重复列名，无法唯一映射。')
    mapping={k:config.get(k+'_column') or next((x for x in names if x in headers),None) for k,names in ALIASES.items()}
    if any(v is not None and v not in headers for v in mapping.values()):raise ValueError('指定列名不存在。')
    units={};warnings=[]
    for k in ['time','voltage','current']:
        if mapping[k] is None:continue
        declared=config.get(k+'_unit','auto');h=mapping[k].lower()
        if declared=='auto':
            if k=='time':unit='s' if h in [x.lower() for x in ALIASES['time']] else None
            elif k=='voltage':unit='mV' if 'mv' in h else 'V' if '#v' in h or '(v)' in h or '_v' in h or '（v）' in h else None
            else:unit='mA' if 'ma' in h else 'A' if '#a' in h or '(a)' in h or '_a' in h else None
        else:unit=declared
        factors={'time':{'s':1,'ms':.001,'min':60,'h':3600},'voltage':{'V':1,'mV':.001},'current':{'A':1,'mA':.001}}
        if unit not in factors[k]:raise ValueError(k+'单位无法确定，请显式选择。')
        units[k]={'unit':unit,'factor':factors[k][unit],'source':'header' if declared=='auto' else 'user_override'}
    records=[];issues=[];duplicate_count=0;empty_extra_count=0;last_raw=None;segment=0;previous=None;ratios=[];previous_stamp=None
    reader=csv.DictReader(lines[header_index+1:],fieldnames=headers,delimiter=delimiter)
    for rownum,row in enumerate(reader,header_index+2):
        if len(records)>=200000:raise ValueError('一次最多处理200000行，请按实验拆分文件。')
        if not any(v for v in row.values()):continue
        if None in row:
            if any(v.strip() for v in row[None]):
                issues.append({'row':rownum,'reason':'非空数据列数超过表头；未截断或猜测映射'});continue
            empty_extra_count+=1;row.pop(None)
        raw_signature=tuple(row.get(h) for h in headers)
        if raw_signature==last_raw:duplicate_count+=1;continue
        last_raw=raw_signature
        try:
            tvalue=row[mapping['time']];duration=':' in tvalue
            if duration and units['time']['unit']!='s':raise ValueError('h:m:s格式已经表示秒，不能同时指定其他时间单位')
            t=parse_time(tvalue)*units['time']['factor']
            v=float(row[mapping['voltage']])*units['voltage']['factor']
            current=float(row[mapping['current']])*units['current']['factor'] if mapping['current'] else None
            if not all(math.isfinite(x) for x in [t,v]+([current] if current is not None else [])) or t<0:raise ValueError('缺失、非有限数值或负时间')
        except (ValueError,TypeError,KeyError) as exc:
            issues.append({'row':rownum,'reason':str(exc)});continue
        stamp=None
        stamp_raw=row.get('Timestamp') or row.get('Date') or row.get('date_time_iso_string')
        if stamp_raw:
            try:stamp=datetime.fromisoformat(stamp_raw).timestamp()
            except ValueError:pass
        if previous is not None:
            if t<=previous:
                segment+=1;issues.append({'row':rownum,'reason':'时间回跳或相同时间但不同记录；分段保留，未修复'})
            elif stamp is not None and previous_stamp is not None and stamp>previous_stamp:
                ratios.append((t-previous)/(stamp-previous_stamp))
        records.append({'source_row':rownum,'segment':segment,'time_s':t,'voltage_V':v,'current_A':current})
        previous=t;previous_stamp=stamp
    if len(records)<2:raise ValueError('少于两个有效数据点。')
    suspect=False
    if len(ratios)>=10:
        ratio=statistics.median(ratios)
        if 900<ratio<1100 or .0009<ratio<.0011:
            suspect=True;warnings.append('持续时间与时间戳增量约差1000倍，疑似时间单位错误；请核查并重新选择单位。')
    if mapping['current'] is None:warnings.append('没有电流列；只能画电压曲线，不能开展协议重建、GITT或电量积分。')
    summary={'encoding':encoding,'header_row':header_index+1,'delimiter':delimiter,'mapping':mapping,'units':units,
             'valid_rows':len(records),'consecutive_exact_duplicates_removed':duplicate_count,'segments':segment+1,
             'rows_with_empty_trailing_columns':empty_extra_count,
             'issue_count':len(issues),'issues':issues[:100],'issues_truncated':len(issues)>100,'warnings':warnings,
             'qc_pass':not issues and not suspect,'voltage_min_V':min(r['voltage_V'] for r in records),
             'voltage_max_V':max(r['voltage_V'] for r in records),
             'scope':'保留原始文件；只做列映射、明确单位换算、相邻完全重复行删除。缺失行与时间异常单独记录；不排序、不插值、不平滑、不推断电流符号。标准化数据不等于材料参数已可信。'}
    return records,summary


def save_normalized(path,records):
    with path.open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=['source_row','segment','time_s','voltage_V','current_A']);writer.writeheader();writer.writerows(records)

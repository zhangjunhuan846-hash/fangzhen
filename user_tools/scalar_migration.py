"""Legacy long observations become individual wide records, never fabricated pairs."""
import copy
import json
import re
from pathlib import Path

LEGACY_SCHEMA=json.loads(Path(__file__).with_name('rg_lite_schema_v1.json').read_text(encoding='utf-8'))
SCALAR_V2_SCHEMA=json.loads(Path(__file__).with_name('rg_lite_schema_v2.json').read_text(encoding='utf-8'))


def schema_for_cells(cells,current):
    grid=cells.get('表征',{})
    if grid.get('B4')=='表征指标':return LEGACY_SCHEMA
    headers={v for k,v in grid.items() if re.fullmatch(r'[A-Z]+4',k) and isinstance(v,str)}
    if '石墨粉体真密度 (g/cm³)' not in headers:return SCALAR_V2_SCHEMA
    return current


def to_scalar_tables(tables):
    if not isinstance(tables,dict):raise ValueError('表格数据必须为对象。')
    result=copy.deepcopy(tables)
    result.setdefault('仿真输入',[])
    for r in result.get('处理工艺',[]):
        value=r.get('concentration')
        if isinstance(value,str) and not r.get('concentration_unit'):
            m=re.fullmatch(r'\s*([+-]?\d+(?:\.\d+)?)\s*([^\d\s].*)?',value)
            if m:
                r['concentration']=float(m[1]);r['concentration_unit']=m[2].strip() if m[2] else None
    for r in result.get('表征',[]):
        if 'metric' not in r and 'value' not in r:continue
        original=copy.deepcopy(r);sample=r.get('sample_id');note=r.get('notes') or ''
        metric=re.sub(r'\s+','',str(r.get('metric') or '')).lower()
        unit=str(r.get('unit') or '').strip().lower().replace('μ','u').replace('µ','u')
        value=r.get('value');key=None;scale=1
        fractions={'碳含量':'carbon_fraction','c含量':'carbon_fraction','carbon':'carbon_fraction','灰分':'ash_fraction','ash':'ash_fraction','水分':'moisture_fraction','moisture':'moisture_fraction'}
        if metric in fractions and unit in ['%','wt%','mass%','质量%','fraction','1']:
            key=fractions[metric];scale=.01 if unit not in ['fraction','1'] else 1
        for symbol in ['li','ni','co','mn','cu','al','fe']:
            if metric in [symbol,symbol+'含量'] and unit in ['mg/kg','ppm','%','wt%']:
                key=symbol+'_mg_kg';scale=10000 if unit in ['%','wt%'] else 1
        for symbol in ['d10','d50','d90']:
            if metric==symbol and unit in ['um','nm']:key=symbol+'_um';scale=.001 if unit=='nm' else 1
        if metric in ['bet','比表面积'] and unit in ['m2/g','m²/g']:key='bet_m2_g'
        if metric in ['id/ig','id_ig','拉曼id/ig'] and unit in ['','1','ratio']:key='id_ig'
        for symbol in ['d002','lc','la']:
            if metric in [symbol,'xrd'+symbol] and unit in ['nm','angstrom','å','a']:
                key=symbol+'_nm';scale=.1 if unit!='nm' else 1
        if metric in ['真密度','石墨真密度','粉体真密度'] and unit in ['g/cm3','g/cm³','g/cc']:key='true_density_g_cm3'
        if metric in ['振实密度','tapdensity'] and unit in ['g/cm3','g/cm³','g/cc']:key='tap_density_g_cm3'
        r.clear();r['sample_id']=sample
        if '_row' in original:r['_row']=original['_row']
        if key and isinstance(value,(int,float)):
            r[key]=value*scale
            r['notes']=note+' [由旧表单条观测转换；不同指标未合并成配对测量]'
        else:r['notes']=note+' [旧表未映射原值：'+json.dumps(original,ensure_ascii=False,default=str)+']'
    return result

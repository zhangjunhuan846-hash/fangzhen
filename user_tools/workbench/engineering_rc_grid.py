"""Shared, bounded interpolation of EIS RC parameters for fitting and replay."""
from bisect import bisect_right
import math
from user_tools.workbench.engineering_contracts import finite


def make_rc_interpolator(table, branches, mode='linear'):
    if mode not in ('linear','log_invT'):
        raise ValueError('RC插值仅支持linear或log_invT。')
    if branches not in (1,2) or not isinstance(table,list) or not 2 <= len(table) <= 1000:
        raise ValueError('RC参数表需2–1000个条件，支持1或2支路。')
    mapped = {}
    keys = ['R0_ohm'] + [key for i in range(1,branches+1) for key in (f'R{i}_ohm',f'C{i}_F')]
    for row in table:
        s=finite(row.get('soc'),'rc_table.soc',0,1); t=finite(row.get('temperature_C'),'rc_table.temperature_C',-30,80)
        if (s,t) in mapped: raise ValueError('RC表存在重复条件。')
        mapped[(s,t)]={key:finite(row.get(key),key,1e-12) for key in keys}
    socs=sorted({s for s,t in mapped});temps=sorted({t for s,t in mapped})
    if len(socs)*len(temps)!=len(mapped):raise ValueError('RC参数表必须是完整的SOC×温度网格。')

    def bracket(nodes,x,inverse_temperature=False):
        if len(nodes)==1: return nodes[0],nodes[0],0.
        i=min(max(bisect_right(nodes,x)-1,0),len(nodes)-2)
        a,b=nodes[i],nodes[i+1]
        if inverse_temperature:
            weight=(1/(x+273.15)-1/(a+273.15))/(1/(b+273.15)-1/(a+273.15))
        else:weight=(x-a)/(b-a)
        return a,b,weight

    def interpolate(soc,temp):
        s=float(soc);t=float(temp)
        if socs[0]-1e-9<=s<=socs[-1]+1e-9:s=min(max(s,socs[0]),socs[-1])
        if temps[0]-1e-7<=t<=temps[-1]+1e-7:t=min(max(t,temps[0]),temps[-1])
        if not socs[0]<=s<=socs[-1] or not temps[0]<=t<=temps[-1]:
            raise ValueError(f'RC参数表不支持外推：SOC={s:.6g}, 温度={t:.6g}°C。')
        a,b,u=bracket(socs,s); c,d,v=bracket(temps,t,mode=='log_invT')
        corners=[(a,c,(1-u)*(1-v)),(b,c,u*(1-v)),(a,d,(1-u)*v),(b,d,u*v)]
        return {key:(math.exp(sum(w*math.log(mapped[(x,y)][key]) for x,y,w in corners)) if mode=='log_invT'
                     else sum(w*mapped[(x,y)][key] for x,y,w in corners)) for key in keys}
    return interpolate


def make_ocv_interpolator(table):
    """Bounded SOC/temperature OCV interpolation using the same grid checks."""
    if not isinstance(table,list):raise ValueError('OCV温度表必须为列表。')
    adapted=[{'soc':r.get('soc'),'temperature_C':r.get('temperature_C'),
              'R0_ohm':r.get('ocv_V'),'R1_ohm':1.,'C1_F':1.} for r in table]
    lookup=make_rc_interpolator(adapted,1,'linear')
    return lambda soc,temp:lookup(soc,temp)['R0_ohm']

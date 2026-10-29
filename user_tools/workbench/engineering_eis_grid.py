"""EIS-derived 1RC grid with explicit held-out spectrum diagnostics."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import numpy as np
from scipy.optimize import least_squares
from user_tools.workbench.engineering_contracts import csv_rows,finite
from user_tools.workbench.engineering_common import finish,save,write_csv
from user_tools.workbench.engineering_eis_audit import lin_kk
from user_tools.workbench.engineering_rc_grid import make_rc_interpolator


def rc_impedance(freq,pars):
    z=np.full(len(freq),pars[0],dtype=complex)
    for i in range(1,len(pars),2):
        r,c=pars[i:i+2];z+=r/(1+2j*np.pi*freq*r*c)
    return z


def fit_rc(freq,z,branches=1):
    if len(freq)<12 or np.any(abs(z)<=0):raise ValueError('每谱需至少12个非零阻抗频点。')
    hi=np.argmax(freq);r0=max(float(z.real[hi]),1e-7)
    r1=max(float(np.max(z.real)-r0),r0*.05,1e-6)
    peak=freq[np.argmax(-z.imag)];c1=1/(2*np.pi*peak*r1)
    if branches==1:guess=[r0,r1,c1]
    else:guess=[r0,r1/2,c1/5,r1/2,c1*5]
    lower=np.array([1e-7]+[v for _ in range(branches) for v in (1e-7,.01)])
    upper=np.array([2.]+[v for _ in range(branches) for v in (2.,1e7)])
    initial=np.log(np.clip(guess,lower,upper))
    def fun(p):
        error=(rc_impedance(freq,np.exp(p))-z)/abs(z)
        return np.r_[error.real,error.imag]
    fitted=least_squares(fun,initial,bounds=(np.log(lower),np.log(upper)),max_nfev=1200)
    p=np.exp(fitted.x)
    if branches==2:
        pairs=sorted([(p[1],p[2]),(p[3],p[4])],key=lambda x:x[0]*x[1]);p=np.array([p[0],*pairs[0],*pairs[1]])
    return p,fitted


def run_grid(config,out,raw):
    rows=csv_rows(raw)
    required={'cell_id','spectrum_id','role','soc','temperature_C','frequency_Hz','Z_real_ohm','Z_imag_ohm'}
    if not required<=set(rows[0]):raise ValueError('CSV需要cell_id,spectrum_id,role,soc,temperature_C,frequency_Hz,Z_real_ohm,Z_imag_ohm。')
    low=finite(config.get('frequency_min_Hz',.1),'frequency_min_Hz',1e-6,1e7)
    high=finite(config.get('frequency_max_Hz',10000),'frequency_max_Hz',low,1e7)
    train_limit=finite(config.get('max_train_relative_rms',.15),'max_train_relative_rms',.001,.5)
    test_limit=finite(config.get('max_test_relative_rms',.2),'max_test_relative_rms',.001,.5)
    branches=config.get('rc_branches',1)
    if isinstance(branches,bool) or branches not in (1,2):raise ValueError('rc_branches仅支持1或2。')
    interpolation=config.get('interpolation','linear')
    if interpolation not in ('linear','log_invT'):raise ValueError('interpolation仅支持linear或log_invT。')
    groups={};cells=set()
    for row in rows:
        cell=row['cell_id'].strip();name=row['spectrum_id'].strip();role=row['role'].strip()
        if not cell or not name or role not in ('train','test'):raise ValueError('需填写电芯、谱编号和train/test。')
        cells.add(cell);soc=finite(row['soc'],'soc',0,1);temp=finite(row['temperature_C'],'temperature_C',-30,80)
        freq=finite(row['frequency_Hz'],'frequency_Hz',1e-6,1e7)
        z=complex(finite(row['Z_real_ohm'],'Z_real_ohm',-10,10),finite(row['Z_imag_ohm'],'Z_imag_ohm',-10,10))
        meta=(cell,role,soc,temp)
        if name not in groups:groups[name]={'meta':meta,'points':[]}
        if groups[name]['meta']!=meta:raise ValueError('同一谱编号的电芯、角色与工况必须一致。')
        if low<=freq<=high:groups[name]['points'].append((freq,z))
    if len(cells)!=1 or not 3<=len(groups)<=50:raise ValueError('仅支持同一电芯的3–50条谱。')
    train={k:g for k,g in groups.items() if g['meta'][1]=='train'}
    test={k:g for k,g in groups.items() if g['meta'][1]=='test'}
    if len(train)<2 or not test:raise ValueError('至少2条训练谱和1条留出谱。')
    nodes={};spectra={};fingerprints={}
    for name,g in groups.items():
        points=g['points']
        if not 12<=len(points)<=500:raise ValueError(name+'筛选频带内需12–500个频点。')
        f=np.array([p[0] for p in points]);z=np.array([p[1] for p in points])
        if len(set(f))!=len(f):raise ValueError(name+'包含重复频率。')
        order=np.argsort(f)
        fingerprint=hashlib.sha256(np.column_stack((f[order],z.real[order],z.imag[order])).astype('<f8').tobytes()).hexdigest()
        previous=fingerprints.get(fingerprint)
        if previous and previous!=g['meta'][1]:raise ValueError('训练与留出谱内容完全相同，请提供独立测量。')
        fingerprints[fingerprint]=g['meta'][1]
        try:_,kk=lin_kk(f,z,True)
        except (ValueError,RuntimeError,np.linalg.LinAlgError,FloatingPointError) as exc:
            kk={'screening_pass':False,'relative_rms':None,'mu':None,'error':str(exc)[:200]}
        spectra[name]={'f':f,'z':z,'kk':kk}
        if g['meta'][1]=='train':
            pos=(g['meta'][2],g['meta'][3])
            if pos in nodes:raise ValueError('训练网格同一SOC与温度不能有多条谱。')
            pars,fit=fit_rc(f,z,branches);pred=rc_impedance(f,pars);rr=float(np.sqrt(np.mean(abs((pred-z)/abs(z))**2)))
            singular=np.linalg.svd(fit.jac,compute_uv=False)
            condition=float(singular[0]/singular[-1]) if singular[-1]>1e-12 else None
            bounded=bool(np.any(fit.active_mask!=0))
            nodes[pos]={'name':name,'parameters':pars,'relative_rms':rr,'fit_success':bool(fit.success),
                        'local_jacobian_condition':condition,'at_parameter_bound':bounded}
    socs=sorted({x[0] for x in nodes});temps=sorted({x[1] for x in nodes})
    if len(socs)*len(temps)!=len(nodes):raise ValueError('训练谱必须组成完整的SOC×温度矩形网格。')
    summaries=[];traces=[];table=[]
    for (s,t),node in sorted(nodes.items()):
        p=node['parameters'];entry={'soc':s,'temperature_C':t,'R0_ohm':float(p[0]),'R1_ohm':float(p[1]),'C1_F':float(p[2])}
        if branches==2:entry.update(R2_ohm=float(p[3]),C2_F=float(p[4]))
        table.append(entry)
    interp=make_rc_interpolator(table,branches,interpolation)
    for name,g in groups.items():
        _,role,s,t=g['meta'];f=spectra[name]['f'];z=spectra[name]['z'];kk=spectra[name]['kk']
        if role=='train':
            node=nodes[(s,t)];pars=node['parameters'];fit_success=node['fit_success']
        else:
            if not (socs[0]<=s<=socs[-1] and temps[0]<=t<=temps[-1]):
                summaries.append({'spectrum_id':name,'role':role,'soc':s,'temperature_C':t,'status':'outside_grid','relative_rms':None,'kk_pass':kk['screening_pass'],'kk_diagnostics':kk});continue
            interpolated=interp(s,t)
            pars=np.array([interpolated['R0_ohm']]+[interpolated[key] for j in range(1,branches+1) for key in (f'R{j}_ohm',f'C{j}_F')]);fit_success=True
        predicted=rc_impedance(f,pars);err=float(np.sqrt(np.mean(abs((predicted-z)/abs(z))**2)))
        condition=node['local_jacobian_condition'] if role=='train' else None
        bounded=node['at_parameter_bound'] if role=='train' else False
        summaries.append({'spectrum_id':name,'role':role,'soc':s,'temperature_C':t,'status':'ok','relative_rms':err,
            'kk_pass':kk['screening_pass'],'kk_relative_rms':kk['relative_rms'],'kk_relative_max':kk.get('relative_max'),'kk_mu':kk['mu'],
            'kk_cutoff_reached':kk.get('cutoff_reached'),'fit_success':fit_success,
            'local_jacobian_condition':condition,'at_parameter_bound':bounded,
            'kk_diagnostics':kk})
        traces.extend({'spectrum_id':name,'role':role,'soc':s,'temperature_C':t,'frequency_Hz':float(fi),
            'Z_real_ohm':float(zi.real),'Z_imag_ohm':float(zi.imag),'fit_real_ohm':float(pi.real),'fit_imag_ohm':float(pi.imag)} for fi,zi,pi in zip(f,z,predicted))
    usable=all(x['status']=='ok' and x['kk_pass'] and x.get('fit_success',False) and x['relative_rms'] <= (train_limit if x['role']=='train' else test_limit)
        and (x['role']=='test' or (not x['at_parameter_bound'] and x['local_jacobian_condition'] is not None and x['local_jacobian_condition']<1e8)) for x in summaries)
    out=Path(out);out.mkdir(parents=True,exist_ok=True);write_csv(out/'parameters.csv',table)
    grid={'cell_id':next(iter(cells)),'table':table,'rc_branches':branches,'interpolation':interpolation,'frequency_band_Hz':[low,high],
          'heldout_spectra':summaries,'usable_for_replay':bool(usable),'limits':{'train_relative_rms':train_limit,'test_relative_rms':test_limit}}
    save(out/'rc_grid.json',grid);digest=hashlib.sha256((out/'rc_grid.json').read_bytes()).hexdigest()
    result={'kind':'engineering','title':'EIS多工况RC参数表与留出谱验证','cell_id':grid['cell_id'],'spectra_summary':summaries,
            'rc_grid_sha256':digest,'grid_usable_for_replay':bool(usable),'parameters':table,'interpolation':interpolation,
            'metrics':{'train_spectra':len(train),'test_spectra':len(test),'soc_nodes':len(socs),'temperature_nodes':len(temps),
                       'kk_passed':sum(x['kk_pass'] for x in summaries),'total_spectra':len(groups)},
            'details':{'scope':'单电芯1RC或2RC参数表由训练谱拟合，2RC按时间常数排序，不保证不同工况下支路物理含义一致；留出谱仅验证网格内插值。Lin-KK与固定频带残差门槛仅为研究筛查；不证明电路物理机制、时域脉冲预测或硬件可用。'}}
    return finish(config,out,result,traces,packages=['impedance','numpy','scipy'])

"""Small audited adapters; names distinguish adaptation from paper reproduction."""
import csv
import hashlib
import io
import math
import statistics


def split_conformal(raw,config):
    """Grouped frozen-predictor split conformal, NOT full SC-CP."""
    if config.get('frozen_independent_model') is not True:raise ValueError('需明确声明模型独立训练并在校准前冻结。')
    alpha=float(config.get('alpha',.1))
    if not math.isfinite(alpha) or not 0<alpha<1:raise ValueError('alpha需在0–1之间。')
    rows=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))));groups=set();ids=set();batches=set();protocols=set();residuals=[];tests=[]
    if not 2<=len(rows)<=20000:raise ValueError('校准表需要2–20000行。')
    for r in rows:
        ident=str(r.get('record_id') or '').strip();group=str(r.get('group_id') or '').strip();batch=str(r.get('batch_id') or '').strip();protocol=str(r.get('protocol_id') or '').strip();role=str(r.get('role') or '').strip()
        if not all([ident,group,batch,protocol]) or ident in ids:raise ValueError('记录/独立条件/批次/协议编号缺失或记录编号重复。')
        if group in groups:raise ValueError('独立条件重复或跨训练/校准/测试重叠；不能把相关时间点当独立样本。')
        groups.add(group);ids.add(ident);batches.add(batch);protocols.add(protocol)
        if role not in ['training','calibration','test']:raise ValueError('role只能training/calibration/test。')
        if role=='training':continue
        pred=float(r['predicted']);observed=float(r['observed'])
        if not math.isfinite(pred) or not math.isfinite(observed):raise ValueError('预测和实测必须是有限数值。')
        if role=='calibration':residuals.append(abs(observed-pred))
        else:tests.append({'record_id':ident,'group_id':group,'predicted':pred,'observed':observed})
    if len(batches)!=1 or len(protocols)!=1:raise ValueError('本版只校准同一批次和同一协议；不得混合A/B或倍率分布。')
    if not residuals:raise ValueError('没有独立校准观测。')
    n=len(residuals);rank=math.ceil((n+1)*(1-alpha)-1e-12);bounded=rank<=n
    threshold=sorted(residuals)[rank-1] if bounded else None
    for r in tests:
        r['lower']=r['predicted']-threshold if bounded else None;r['upper']=r['predicted']+threshold if bounded else None
        r['covered']=abs(r['observed']-r['predicted'])<=threshold if bounded else None
    return {'kind':'split_conformal','evidence_type':'user_calibration_diagnostic','method':'frozen_grouped_split_conformal_not_sc_cp','alpha':alpha,'nominal_coverage':1-alpha,
            'calibration_n':n,'finite_sample_rank':rank,'finite_interval':bounded,'residual_threshold':threshold,
            'interval_width':2*threshold if bounded else None,'test_n':len(tests),'tests':tests,
            'empirical_test_coverage':statistics.mean(r['covered'] for r in tests) if tests and bounded else None,
            'coverage_evaluation':'finite_intervals' if bounded else 'not_meaningful_unbounded',
            'batch_id':next(iter(batches)),'protocol_id':next(iter(protocols)),'source_sha256':hashlib.sha256(raw).hexdigest(),
            'scope':'独立冻结模型的绝对残差split conformal；这是借鉴后的轻量方法，不是SC-CP增广等距回归复现。有限样本分位阶次不足时区间无界，绝不替换成最大残差。条件/电芯组必须独立；训练独立性和同分布目前依赖明确声明，主动选点、批次漂移和相关时间点可破坏交换性。覆盖率保证不等于材料机制正确。'}


def read_eis(raw,config):
    config=config or {};rows=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
    if not 2<=len(rows)<=20000:raise ValueError('EIS CSV需要2–20000行。')
    fields=set(rows[0]);aliases={'frequency':['frequency_Hz','frequency','Frequency [Hz]','freq/Hz'],
        'real':['Z_real_ohm','Z_re [Ohm]','Zreal','Re(Z)/Ohm'],
        'imag':['Z_imag_ohm','Z_im [Ohm]','Zimag','Im(Z)/Ohm','-Im(Z)/Ohm']}
    mapping={k:config.get(k+'_column') or next((a for a in names if a in fields),None) for k,names in aliases.items()}
    if any(v not in fields for v in mapping.values()):raise ValueError('缺少频率、实部或虚部列；请明确列名。')
    f_unit=config.get('frequency_unit','Hz');z_unit=config.get('impedance_unit','ohm')
    if f_unit not in ['Hz','rad/s'] or z_unit not in ['ohm','mohm']:raise ValueError('频率只支持Hz/rad/s，阻抗只支持Ω/mΩ；面积归一阻抗需先提供面积并转换。')
    negative=config.get('imag_is_negative') is True or mapping['imag'].startswith('-')
    spectra={};warnings=[];duplicate=0;seen=set()
    for index,row in enumerate(rows,2):
        f=float(row[mapping['frequency']])/(2*math.pi if f_unit=='rad/s' else 1)
        scale=.001 if z_unit=='mohm' else 1
        real=float(row[mapping['real']])*scale;imag=float(row[mapping['imag']])*scale*(-1 if negative else 1)
        if not all(math.isfinite(v) for v in [f,real,imag]) or f<=0:raise ValueError(f'第{index}行频率需为正，阻抗需为有限数。')
        group=str(row.get('spectrum_id') or 'single');identity=(group,f)
        if identity in seen:duplicate+=1
        seen.add(identity)
        spectra.setdefault(group,[]).append({'frequency_Hz':f,'Z_real_ohm':real,'Z_imag_ohm':imag,
                                           'magnitude_ohm':math.hypot(real,imag),'phase_deg':math.degrees(math.atan2(imag,real))})
    if any(len(v)<2 for v in spectra.values()):raise ValueError('每条谱至少两个频率点。')
    if duplicate:warnings.append('存在重复频率，原点保留；未自动平均。')
    if any(p['Z_real_ohm']<0 for pts in spectra.values() for p in pts):warnings.append('存在负实部，请核查测量极性、稳定性和仪器。')
    for points in spectra.values():points.sort(key=lambda p:p['frequency_Hz'],reverse=True)
    return {'evidence_type':'user_eis_spectrum','eis_spectra':[{'name':k,'points':v} for k,v in spectra.items()],
            'mapping':mapping,'declared_frequency_unit':f_unit,'declared_impedance_unit':z_unit,'imag_sign_converted':negative,
            'duplicate_frequencies':duplicate,'warnings':warnings,'linearity_assessed':False,'stationarity_assessed':False,
            'source_sha256':hashlib.sha256(raw).hexdigest(),
            'scope':'频率转换到Hz，阻抗转换到Ω；数据保持Z_im符号，Nyquist显示−Z_im。按频率排序只用于谱展示，原件保持不变。没有原始激励/响应与协议时不能证明线性、稳态或Kramers-Kronig一致性；结构导入成功不意味着可可信辨识参数。'}

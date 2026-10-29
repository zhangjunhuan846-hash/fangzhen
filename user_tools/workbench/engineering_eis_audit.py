"""Full-band EIS export-unit audit and fixed-policy Lin-KK comparison."""
import csv
import hashlib
import io
from pathlib import Path
import time
import numpy as np

from user_tools.workbench.engineering_common import finish,save,write_csv
from user_tools.workbench.engineering_commercial import DATA

MANUFACTURER='https://www.digatron.com/Portals/38/Images/documents/PRODUKTBLATT_EIS_EN.PDF'
DOCUMENTATION='https://impedancepy.readthedocs.io/en/latest/_modules/impedance/validation.html'


def parse_digatron(raw):
    lines=raw.decode('utf-8-sig').splitlines()
    start=next(i for i,line in enumerate(lines) if line.startswith('Time Stamp;'))
    reader=csv.DictReader(lines[start:],delimiter=';');points=[]
    for row in reader:
        if not row.get('Time Stamp'):continue
        if row.get('ActFreq')=='[EIS]':continue
        point={k:float(row[k]) for k in ['ActFreq','Zreal1','Zimg1','Betrag','Phase','AAmplitude','VRelativ','mvIdeal','U1']}
        if not np.isfinite(list(point.values())).all() or min(point['ActFreq'],point['Betrag'],point['AAmplitude'],point['mvIdeal'])<=0:
            raise ValueError('Non-finite/nonpositive EIS export field')
        points.append(point)
    if len(points)<12:raise ValueError('EIS spectrum has insufficient points')
    f=np.array([p['ActFreq'] for p in points]);zraw=np.array([complex(p['Zreal1'],p['Zimg1']) for p in points])
    if len(set(f))!=len(f):raise ValueError('Repeated EIS frequencies require an explicit separate-spectrum label')
    mag=np.array([p['Betrag'] for p in points]);phase=np.array([p['Phase'] for p in points])
    estimated=np.array([p['mvIdeal']*p['VRelativ']/p['AAmplitude'] for p in points])
    audit=dict(magnitude_relative_max=float(np.max(abs(abs(zraw)-mag)/mag)),
          phase_max_abs_deg=float(np.max(abs((np.degrees(np.angle(zraw))-phase+180)%360-180))),
          amplitude_ratio_relative_max=float(np.max(abs(estimated-mag)/mag)),
          amplitude_ratio_relative_median=float(np.median(abs(estimated-mag)/mag)),
          amplitude_points_above_manufacturer_1percent=int(np.sum(abs(estimated-mag)/mag>.01)),
          amplitude_tolerance_origin='manufacturer specified1percent magnitude accuracy; redundancy is scale evidence, not a traceable calibration',
          scale_to_ohm=.001,voltage_amplitude_mV_field='mvIdeal * VRelativ',current_amplitude_A_field='AAmplitude',
          unit_evidence='export magnitude/phase/current-voltage amplitude redundancies and manufacturer mOhm axes',manufacturer=MANUFACTURER,
          instrument_calibration_verified=False,dc_voltage_drift_mV=float((points[-1]['U1']-points[0]['U1'])*1000))
    audit['unit_consistency_pass']=(audit['magnitude_relative_max']<1e-4 and audit['phase_max_abs_deg']<.05 and audit['amplitude_ratio_relative_median']<.01)
    audit['amplitude_anomaly_records']=[dict(frequency_Hz=float(f[i]),export_magnitude_mOhm=float(mag[i]),
          amplitude_inferred_mOhm=float(estimated[i]),relative_discrepancy=float(abs(estimated[i]/mag[i]-1)),
          current_amplitude_A=points[i]['AAmplitude'],voltage_relative=points[i]['VRelativ']) for i in range(len(f)) if abs(estimated[i]/mag[i]-1)>.01]
    if not audit['unit_consistency_pass']:raise ValueError('Export amplitude/magnitude/phase does not support the declared mOhm conversion')
    return f,zraw*.001,audit


def stable_kk_fit(f,z,order,add_cap,all_f=None):
    """Independent, column-scaled SVD of the first-principles linear KK basis."""
    axis=f if all_f is None else all_f
    tau=np.geomspace(1/(2*np.pi*max(axis)),1/(2*np.pi*min(axis)),order)
    def design(freq):
        w=2*np.pi*freq
        cols=[np.ones(len(freq),dtype=complex)]+[1/(1+1j*w*t) for t in tau]
        if add_cap:cols.append(-1j/w)
        cols.append(1j*w)
        return np.column_stack(cols)
    a=design(f)/abs(z)[:,None];matrix=np.vstack([a.real,a.imag]);target=np.r_[z.real/abs(z),z.imag/abs(z)]
    norms=np.linalg.norm(matrix,axis=0);norms[norms==0]=1.
    coeff,_,rank,singular=np.linalg.lstsq(matrix/norms,target,rcond=1e-12);coeff=coeff/norms
    return design(axis)@coeff,dict(rank=int(rank),columns=len(coeff),scaled_condition_number=float(singular[0]/max(singular[-1],1e-30)))


def lin_kk(f,z,add_cap):
    import contextlib
    import impedance
    import impedance.validation as validation
    missing='np' not in validation.circuit_elements
    if missing:validation.circuit_elements['np']=np
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            order,mu,pred,rr,ri=validation.linKK(f,z,c=.85,max_M=min(50,len(f)//2),fit_type='complex',add_cap=add_cap)
    finally:
        if missing:validation.circuit_elements.pop('np',None)
    relative=np.hypot(rr,ri)
    if not np.isfinite(relative).all() or not np.isfinite(mu):raise ValueError('Non-finite Lin-KK result')
    independent,condition=stable_kk_fit(f,z,int(order),add_cap)
    max_order=min(50,len(f)//2)
    result=dict(add_cap=add_cap,library_version=impedance.__version__,fit_type='complex',c=.85,max_M=max_order,
                M=int(order),mu=float(mu),reached_max_M=bool(order>=max_order),
                real_relative_rms=float(np.sqrt(np.mean(np.asarray(rr)**2))),
                imag_relative_rms=float(np.sqrt(np.mean(np.asarray(ri)**2))),
                relative_rms=float(np.sqrt(np.mean(relative**2))),
                relative_max=float(np.max(relative)),cutoff_reached=bool(mu<=.85),
                independent_SVD_max_difference_ohm=float(np.max(abs(pred-independent))),**condition)
    # This fixed threshold is an engineering screen, not proof of stationarity or linearity.
    result['screening_pass']=bool(result['relative_rms']<=.02 and result['relative_max']<=.05 and result['cutoff_reached'])
    result['screening_thresholds']={'relative_rms_max':.02,'relative_max_max':.05,'mu_cutoff':.85}
    result['screening_failures']=(["relative_rms_above_threshold"] if result['relative_rms']>.02 else []) + \
        (["relative_max_above_threshold"] if result['relative_max']>.05 else []) + \
        (["mu_cutoff_not_reached_at_max_M"] if not result['cutoff_reached'] and result['reached_max_M'] else []) + \
        (["mu_cutoff_not_reached"] if not result['cutoff_reached'] and not result['reached_max_M'] else [])
    for name,mask in [('below_0_1Hz',f<.1),('0_1_to_100Hz',(f>=.1)&(f<=100)),('above_100Hz',f>100)]:
        result[name+'_relative_rms']=float(np.sqrt(np.mean(relative[mask]**2))) if mask.any() else None
    return pred,result


def run_eis_audit(config,out):
    start=time.perf_counter();out=Path(out);out.mkdir(parents=True,exist_ok=True)
    files=sorted((DATA/'25degC/EIS').glob('*EIS*.csv'))
    if len(files)!=14:raise ValueError('Expected all14 original25C EIS spectra')
    rows=[];scores=[];audits=[];curves=[]
    for path in files:
        raw=path.read_bytes();f,z,unit=parse_digatron(raw)
        old,old_score=lin_kk(f,z,False);new,new_score=lin_kk(f,z,True)
        # Interleaved frequency validation has a fixed order and is a separate diagnostic.
        cv_order=max(3,len(f)//4);cv=np.zeros(len(f),dtype=complex)
        for fold in range(3):
            test=np.arange(len(f))%3==fold
            predictions,_=stable_kk_fit(f[~test],z[~test],cv_order,True,all_f=f)
            cv[test]=predictions[test]
        audit=dict(spectrum=path.stem,source_sha256=hashlib.sha256(raw).hexdigest(),unit=unit,baseline=old_score,augmented=new_score,
             frequency_cv_order=cv_order,frequency_cv_relative_rms=float(np.sqrt(np.mean(abs((cv-z)/abs(z))**2))),
             points=len(f),frequency_min_Hz=float(min(f)),frequency_max_Hz=float(max(f)),excluded_points=0,
             scope='full-frequency residual diagnostics; adding a capacitance does not certify stationarity, linearity or a material mechanism')
        audits.append(audit)
        scores.append(dict(spectrum=path.stem,points=len(f),unit_consistency_pass=unit['unit_consistency_pass'],
              baseline_relative_rms=old_score['relative_rms'],augmented_relative_rms=new_score['relative_rms'],
              augmented_relative_max=new_score['relative_max'],M=new_score['M'],mu=new_score['mu'],
              baseline_screening_pass=old_score['screening_pass'],augmented_screening_pass=new_score['screening_pass'],
              frequency_cv_relative_rms=audit['frequency_cv_relative_rms'],dc_voltage_drift_mV=unit['dc_voltage_drift_mV']))
        for i in range(len(f)):rows.append(dict(spectrum=path.stem,frequency_Hz=f[i],Z_real_ohm=z[i].real,Z_imag_ohm=z[i].imag,
             baseline_KK_real_ohm=old[i].real,baseline_KK_imag_ohm=old[i].imag,augmented_KK_real_ohm=new[i].real,
             augmented_KK_imag_ohm=new[i].imag,augmented_relative_error=abs((new[i]-z[i])/z[i]),
             frequency_cv_relative_error=abs((cv[i]-z[i])/z[i])))
        if len(curves)<3:curves.append(dict(name=path.stem+' 复阻抗幅值',x_label='频率 (Hz)',y_label='阻抗模值 (Ω)',primary='串联C增强Lin-KK',secondary='原始实测',
              points=[[f[i],abs(new[i]),abs(z[i])] for i in np.argsort(f)]))
        print(path.stem,'KK RMS',round(old_score['relative_rms']*100,3),'->',round(new_score['relative_rms']*100,3),'%',flush=True)
    write_csv(out/'eis_audit_metrics.csv',scores)
    save(out/'eis_audit.json',dict(spectra=audits,manufacturer=MANUFACTURER,method_documentation=DOCUMENTATION,
            point_deletion=False,prior_single_spectrum_result_preserved=True,thresholds=dict(rms=.02,maximum=.05),
            fresh_spectra_count=13,known_spectra_count=1,instrument_calibration_verified=False))
    return finish(config,out,dict(kind='engineering',title='Panasonic PF · EIS单位与全谱一致性复核',engine='Digatron redundancy audit + impedance.py Lin-KK + independent SVD',
          metrics=dict(spectra=14,points=sum(s['points'] for s in scores),unit_checks_passed=sum(s['unit_consistency_pass'] for s in scores),
              amplitude_anomaly_points=sum(s['unit']['amplitude_points_above_manufacturer_1percent'] for s in audits),
              baseline_spectra_passed=sum(s['baseline_screening_pass'] for s in scores),augmented_spectra_passed=sum(s['augmented_screening_pass'] for s in scores),
              maximum_augmented_relative_rms=max(s['augmented_relative_rms'] for s in scores),excluded_points=0,elapsed_s=time.perf_counter()-start),
          spectra_summary=scores,details={'scope':'原始幅值/相位及电压电流幅值冗余核对mΩ转换；14条全频谱固定设置对照。Lin-KK含/不含低频串联电容，独立SVD复算及频率交叉验证。未连接仪器，不以残差通过代替线性/稳态或机理证明。'}),rows,curves,['impedance','numpy','scipy'])

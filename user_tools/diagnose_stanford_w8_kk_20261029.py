"""Reproduce and explain W8 Lin-KK screening; do not change the bridge policy."""
from pathlib import Path
import contextlib
import csv
import io
import json
import warnings
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import impedance
import impedance.validation as validation
from user_tools.workbench.engineering_eis_audit import lin_kk

INPUT=Path('outputs/eis_bms_validation/stanford_aging_w8_eis_20261029/eis_input.csv')
OUT=Path('outputs/eis_bms_validation/stanford_w8_kk_diagnostics_20261029')

def main():
    OUT.mkdir(parents=True,exist_ok=True);data=pd.read_csv(INPUT);report=[];traces=[]
    for sid,raw in data.groupby('spectrum_id'):
        for band,cap in [('full',20000),('under_500Hz',500)]:
            x=raw[raw.frequency_Hz<=cap].sort_values('frequency_Hz');f=x.frequency_Hz.to_numpy();z=x.Z_real_ohm.to_numpy()+1j*x.Z_imag_ohm.to_numpy()
            pred,diag=lin_kk(f,z,True)
            # Sensitivity only: a larger M can overfit and is not a revised pass.
            validation.circuit_elements.setdefault('np',np)
            with contextlib.redirect_stdout(io.StringIO()),warnings.catch_warnings():
                warnings.simplefilter('ignore')
                M,mu,alt,rr,ri=validation.linKK(f,z,c=.85,max_M=len(f),fit_type='complex',add_cap=True)
            delta=np.hypot(rr,ri)
            diag['sensitivity_larger_max_M']={'max_M':len(f),'M':int(M),'mu':float(mu),
                'relative_rms':float(np.sqrt(np.mean(delta**2))), 'interpretation':'exploratory; larger order can overfit'}
            diag.update(spectrum_id=sid,band=band,library_version=impedance.__version__,original_columns=['Freq','Zmod','Zphz'],
                units='Hz and ohm (source ACIM magnitude and phase converted as magnitude * exp(j phase))',
                n_raw=int(len(raw)),n_valid=int(len(x)),duplicate_frequencies=int(x.frequency_Hz.duplicated().sum()),
                frequency_min_Hz=float(f.min()),frequency_max_Hz=float(f.max()))
            report.append(diag)
            for j in range(len(f)):
                traces.append({'spectrum_id':sid,'band':band,'frequency_Hz':f[j],'real_ohm':z[j].real,'imag_ohm':z[j].imag,
                    'fit_real_ohm':pred[j].real,'fit_imag_ohm':pred[j].imag,
                    'real_residual_normalized':(z[j].real-pred[j].real)/abs(z[j]),
                    'imag_residual_normalized':(z[j].imag-pred[j].imag)/abs(z[j])})
            fig,ax=plt.subplots(3,2,figsize=(10,10)); fig.suptitle(f'{sid} {band}; M={diag["M"]}, mu={diag["mu"]:.3f}')
            ax[0,0].plot(z.real,-z.imag,'o',label='measured');ax[0,0].plot(pred.real,-pred.imag,'-',label='Lin-KK');ax[0,0].set(xlabel='Re(Z) Ω',ylabel='-Im(Z) Ω');ax[0,0].legend()
            ax[0,1].semilogx(f,abs(z),'o',label='measured');ax[0,1].semilogx(f,abs(pred),'-',label='Lin-KK');ax[0,1].set(xlabel='Hz',ylabel='|Z| Ω');ax[0,1].legend()
            ax[1,0].semilogx(f,np.angle(z,deg=True),'o',label='measured');ax[1,0].semilogx(f,np.angle(pred,deg=True),'-',label='Lin-KK');ax[1,0].set(xlabel='Hz',ylabel='phase (°)');ax[1,0].legend()
            ax[1,1].axis('off')
            ax[2,0].semilogx(f,100*(z.real-pred.real)/abs(z),'o-');ax[2,0].set(xlabel='Hz',ylabel='Re residual / |Z| (%)')
            ax[2,1].semilogx(f,100*(z.imag-pred.imag)/abs(z),'o-');ax[2,1].set(xlabel='Hz',ylabel='Im residual / |Z| (%)')
            fig.tight_layout();fig.savefig(OUT/f'{sid}_{band}.png',dpi=150);plt.close(fig)
    pd.DataFrame(traces).to_csv(OUT/'frequency_residuals.csv',index=False)
    (OUT/'diagnostics.json').write_text(json.dumps({'spectra':report,'scope':'engineering screening, not a definitive measurement validity judgement; no policy relaxed'},indent=2),encoding='utf8')
    print(json.dumps([{'spectrum':r['spectrum_id'],'band':r['band'],'M':r['M'],'max_M':r['max_M'],'mu':r['mu'],'failures':r['screening_failures'],'alternative':r['sensitivity_larger_max_M']} for r in report],indent=2))
if __name__=='__main__':main()

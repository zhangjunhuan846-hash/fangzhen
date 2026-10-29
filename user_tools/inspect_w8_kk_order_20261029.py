"""Order sensitivity and rank of the actual complex Lin-KK system; no bridge changes."""
from pathlib import Path
import contextlib,io,warnings
import numpy as np
import pandas as pd
import impedance.validation as validation
from user_tools.workbench.engineering_eis_audit import stable_kk_fit

INPUT=Path('outputs/eis_bms_validation/stanford_aging_w8_eis_20261029/eis_input.csv')
OUT=Path('outputs/eis_bms_validation/stanford_w8_kk_diagnostics_20261029/order_sensitivity.csv')
def main():
    df=pd.read_csv(INPUT);output=[];validation.circuit_elements.setdefault('np',np)
    for name,raw in df.groupby('spectrum_id'):
        for band,cap in [('full',20000),('under_500Hz',500)]:
            x=raw[raw.frequency_Hz<=cap].sort_values('frequency_Hz');f=x.frequency_Hz.to_numpy();z=x.Z_real_ohm.to_numpy()+1j*x.Z_imag_ohm.to_numpy()
            for order in range(1,len(f)+1):
                row={'spectrum':name,'band':band,'fit_type':'complex','n_frequency_points':len(f),'M':order,
                     'series_resistance_capacitance_inductance_included':True,'complex_linear_coefficient_count':order+3,
                     'real_observation_count':2*len(f)}
                try:
                    with warnings.catch_warnings(),contextlib.redirect_stdout(io.StringIO()):
                        warnings.simplefilter('ignore')
                        _,mu,pred,rr,ri=validation.linKK(f,z,c=None,max_M=order,fit_type='complex',add_cap=True)
                    svd,info=stable_kk_fit(f,z,order,True);row.update(mu=float(mu),
                        residual_rms=float(np.sqrt(np.mean(rr**2+ri**2))),rank=info['rank'],
                        scaled_condition_number=info['scaled_condition_number'],
                        library_svd_max_difference_ohm=float(max(abs(pred-svd))))
                except Exception as exc:row['error']=str(exc)
                output.append(row)
    pd.DataFrame(output).to_csv(OUT,index=False);print('rows',len(output))
if __name__=='__main__':main()

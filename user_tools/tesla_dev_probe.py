"""Quick development-only temperature OCV candidates at -20C."""
from user_tools.workbench.engineering_tesla_validation import train_model,windows,score

w=windows('m448-N',-20,'drive1')[0]
for source in ('c20','c20_corrected_half','c20_corrected','c20_corrected_double','hppc_rest'):
    model,_=train_model(source)
    for noise in (.01,.05,.1):
        try:
            m,_=score(model,-20,w,'ocv_and_rc_temperature',use_ukf=False,voltage_noise=noise)
            print(source,noise,'voltage_mV',round(m['ekf_prior_voltage_rmse_V']*1000,2),'SOCref',round(m['ekf_rmse_soc'],4),flush=True)
        except ValueError as exc:
            if '不支持外推' not in str(exc):raise
            print(source,noise,'outside_domain',str(exc),flush=True)

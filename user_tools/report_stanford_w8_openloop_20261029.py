"""Inspect W8 open-loop prediction without changing the frozen parameters."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

OUT=Path('outputs/eis_bms_validation/stanford_w8_openloop_20261029')

def main():
    data=pd.read_csv(OUT/'openloop_trace.csv.gz'); d=data[data.step==14].copy()
    span=float(d.time_s.iloc[-1]-d.time_s.iloc[0]); d['quarter']=np.minimum(((d.time_s-d.time_s.iloc[0])/span*4).astype(int),3)
    rows=[]
    for q,g in d.groupby('quarter'):
        t=g.time_s.to_numpy();e=g.residual_V.to_numpy();duration=t[-1]-t[0]
        rows.append({'quarter':int(q+1),'duration_s':float(duration),
          'bias_mV':float(1000*np.trapezoid(e,t)/duration),'rmse_mV':float(1000*np.sqrt(np.trapezoid(e**2,t)/duration)),
          'temperature_min_C':float(g.surface_C.min()),'temperature_max_C':float(g.surface_C.max()),
          'soc_proxy_start':float(g.soc_proxy.iloc[0]),'soc_proxy_end':float(g.soc_proxy.iloc[-1])})
    pd.DataFrame(rows).to_csv(OUT/'dynamic_quarter_metrics.csv',index=False)
    plot=data.iloc[::20];t=(plot.time_s-plot.time_s.iloc[0])/3600
    fig,axs=plt.subplots(3,1,figsize=(12,9),sharex=True)
    axs[0].plot(t,plot.measured_V,label='measured',lw=.8);axs[0].plot(t,plot.model_V,label='HPPC 1RC open-loop',lw=.8);axs[0].set_ylabel('Voltage (V)');axs[0].legend()
    axs[1].plot(t,1000*plot.residual_V,lw=.7);axs[1].axhline(0,color='black',lw=.5);axs[1].set_ylabel('Residual (mV)')
    axs[2].plot(t,plot.current_discharge_A,lw=.6);axs[2].set_ylabel('Discharge current (A)');axs[2].set_xlabel('Time since prior 1h rest (h)')
    fig.tight_layout();fig.savefig(OUT/'openloop_voltage.png',dpi=150);plt.close(fig)
    print(json.dumps(rows,indent=2))
if __name__=='__main__':main()

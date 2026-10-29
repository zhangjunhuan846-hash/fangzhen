"""Re-run real optimizer calls with telemetry and profile EIS time constant."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from scipy.io import loadmat
from scipy.optimize import lsq_linear
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from user_tools.workbench import engineering_calb_validation as base
from user_tools.workbench import engineering_eis_hppc_joint as joint
from user_tools.validate_calb_eis_hppc_ablation_20261029 import pulse_from_node

OUT=Path('outputs/eis_bms_validation/eis_hppc_diagnostics_20261029')
OLD=Path('outputs/eis_bms_validation/calb_eis_hppc_ablation_20261029')

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    frozen=json.loads((OLD/'frozen_models.json').read_text(encoding='utf8'))
    data=loadmat(base.EXTRA_DATA/'Temperature_25C/eis_test/60129.mat',simplify_cells=True)['Data']
    ref=base.slow_reference('60129',25);raw=base.load('60129',25,'hppc_1c');hppc=base.fit_hppc('60129',25,ref['capacity'])
    dt=np.diff(raw['t']);dt=dt[dt>0]; calls=[];profiles=[];spectra=[]
    fig,axes=plt.subplots(2,2,figsize=(10,7));overlay,oa=plt.subplots(2,2,figsize=(10,7))
    original=joint.least_squares
    for ax,ox,(soc,spectrum,node) in zip(axes.flat,oa.flat,zip((.8,.6,.4,.2),data,frozen['node_fits'])):
        m=spectrum['meas'];f=np.asarray(m['Frequency'],float);z=np.asarray(m['Zreal'],float)+1j*np.asarray(m['Zimg'],float)
        use=(f>=.5)&(f<=1000);f,z=f[use],z[use]
        h=min(hppc,key=lambda p:abs(p['soc']-soc));pulse=pulse_from_node(raw,h);local=[]
        def observed(fun,x0,**kwargs):
            result=original(fun,x0,**kwargs)
            requested=np.exp(x0[:3]).tolist()
            if 6 <= len(local) < 9:
                best=min(local[:3],key=lambda item:item['cost_sum_squared'])
                requested=(np.asarray(best['final'])*[1.,.5,2.][len(local)-6]).tolist()
            local.append({'nominal_soc':soc,'call_index':len(local),'requested_start':requested,
                'passed_start':np.exp(x0[:3]).tolist(),'v0':float(x0[3]),'final':np.exp(result.x[:3]).tolist(),
                'cost_sum_squared':float(np.sum(result.fun**2)),'nfev':int(result.nfev),'status':int(result.status),
                'message':str(result.message),'success':bool(result.success),'at_bound':bool(np.any(result.active_mask)),
                'fallback_used':False})
            return result
        joint.least_squares=observed
        try:fits=joint.fit_methods(pulse,{'frequency_Hz':f,'impedance':z},True)
        finally:joint.least_squares=original
        for item in local:item['stage']=('eis_only' if item['call_index']<3 else 'hppc_only' if item['call_index']<6 else 'eis_initial_hppc' if item['call_index']<9 else 'joint')
        calls.extend(local)
        for method in ('hppc_only','eis_initial','joint'):
            for k in ('R0_ohm','R1_ohm','tau_s'):
                assert np.isclose(fits[method][k],node['fit'][method][k],rtol=1e-7,atol=1e-9), (soc,method,k)
        taus=np.geomspace(1e-5,600,300);cost=[]
        for tau in taus:
            component=1/(1+2j*np.pi*f*tau);design=np.column_stack((np.ones(len(f)),component))
            A=np.vstack((design.real/abs(z)[:,None],design.imag/abs(z)[:,None]))/np.sqrt(len(f))
            b=np.r_[z.real/abs(z),z.imag/abs(z)]/np.sqrt(len(f))
            result=lsq_linear(A,b,bounds=(joint.LOW[:2],joint.HIGH[:2]),tol=1e-12)
            val=float(np.sum((A@result.x-b)**2));cost.append(val)
            profiles.append({'soc':soc,'tau_s':tau,'fc_Hz':1/(2*np.pi*tau),'objective':val,'R0_ohm':result.x[0],'R1_ohm':result.x[1]})
        optimal=int(np.argmin(cost));e=fits['eis_initialization'];hp=fits['hppc_only']
        spectra.append({'soc':soc,'f_min_Hz':float(f.min()),'f_max_Hz':float(f.max()),'points':len(f),
            'imag_min_ohm':float(z.imag.min()),'imag_max_ohm':float(z.imag.max()),'positive_imag_points':int(sum(z.imag>0)),
            'tau_bound_s':.25,'eis_seed_tau_s':e['tau_s'],'eis_seed_at_bound':e['at_bound'],
            'eis_fc_at_bound_Hz':1/(2*np.pi*e['tau_s']),'hppc_tau_s':hp['tau_s'],
            'hppc_fc_Hz':1/(2*np.pi*hp['tau_s']),'profile_min_tau_s':float(taus[optimal]),'profile_min_obj':cost[optimal],
            'pulse_fit_s':120,'pulse_fit_resampled_s':1,'raw_sampling_median_s':float(np.median(dt))})
        ax.semilogx(taus,cost);ax.axvline(.25,color='red',linestyle='--',label='bound 0.25 s');ax.axvline(hp['tau_s'],color='green',linestyle=':',label='HPPC');ax.axvline(taus[optimal],color='black',linestyle='-.',label='profile min')
        ax.set_title(f'SOC {soc:.0%}');ax.set_xlabel('tau (s)');ax.set_ylabel('normalized squared error');ax.legend(fontsize=7)
        model=joint.eis_impedance([e['R0_ohm'],e['R1_ohm'],e['tau_s']],f)
        ox.semilogx(f,z.real*1000,'o',markersize=3,label='real measured');ox.semilogx(f,model.real*1000,'-',label='real 1RC')
        ox.semilogx(f,z.imag*1000,'o',markersize=3,label='imag measured');ox.semilogx(f,model.imag*1000,'-',label='imag 1RC')
        ox.axhline(0,color='grey',linewidth=.5);ox.set_title(f'SOC {soc:.0%}');ox.set_xlabel('Hz');ox.set_ylabel('Z (mΩ)');ox.legend(fontsize=6)
    fig.tight_layout();fig.savefig(OUT/'eis_profile.png',dpi=150);plt.close(fig)
    overlay.tight_layout();overlay.savefig(OUT/'eis_real_imag_overlay.png',dpi=150);plt.close(overlay)
    (OUT/'optimizer_calls.json').write_text(json.dumps(calls,indent=2),encoding='utf8')
    pd.DataFrame(profiles).to_csv(OUT/'eis_profile.csv',index=False);pd.DataFrame(spectra).to_csv(OUT/'spectra_time_scales.csv',index=False)
    table=pd.read_csv(OLD/'window_metrics.csv');drive=table[table.window_type!='pulse_C3'];rows=[]
    for (kind,window),g in drive.groupby(['window_type','window']):
        a=g[g.method=='hppc_only'].iloc[0];b=g[g.method=='joint'].iloc[0]
        rows.append({'window_type':kind,'window':window,**{key+'_joint_minus_hppc':b[key]-a[key] for key in ('open_loop_rmse_mV','ekf_prior_rmse_mV','soc_proxy_rmse_pp')}})
    pd.DataFrame(rows).to_csv(OUT/'paired_driving_differences.csv',index=False)
    print(pd.DataFrame(spectra).to_string(index=False));print(pd.DataFrame(rows).to_string(index=False))
if __name__=='__main__':main()

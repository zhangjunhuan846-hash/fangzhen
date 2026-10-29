"""Temperature/SOH-aware one-RC numerics and a sensor-only SOX augmented EKF."""
import time
import numpy as np
from numba import njit


@njit(cache=True)
def interpolation(soc, temp, grid, temps, table):
    k = np.searchsorted(temps, temp)
    if k == 0: return np.interp(soc, grid, table[0])
    if k >= len(temps): return np.interp(soc, grid, table[-1])
    a = (temp-temps[k-1])/(temps[k]-temps[k-1])
    return (1-a)*np.interp(soc, grid, table[k-1])+a*np.interp(soc, grid, table[k])


@njit(cache=True)
def simulate_fast(t, current, ambient, initial_temp, capacity, grid, temps, tables, thermal, scales, dynamic):
    """Midpoint integration; current at row i acts on the preceding interval."""
    n = len(t); output = np.empty((n,3)); state = np.array([1.,0.,initial_temp])
    # OCV is indexed by the declared chamber condition; RC can follow predicted case temperature.
    ocv_temp = np.median(ambient)
    for i in range(n):
        dt = t[i]-t[i-1] if i else 0.
        steps = max(1, int(np.ceil(dt/.05))); h = dt/steps
        for _ in range(steps):
            mid = state.copy()
            for stage in range(2):
                s = state if stage == 0 else mid
                temp = s[2] if dynamic else ocv_temp
                r0 = interpolation(s[0], temp, grid, temps, tables[1])*scales[0]
                r1 = interpolation(s[0], temp, grid, temps, tables[2])*scales[1]
                c1 = interpolation(s[0], temp, grid, temps, tables[3])*scales[2]/scales[1]
                derivative = np.array([-current[i]/(3600*capacity),
                    (current[i]*r1-s[1])/(r1*c1),
                    (current[i]*(current[i]*r0+s[1])-thermal[1]*(s[2]-ambient[i]))/thermal[0]])
                if stage == 0: mid = state + h*derivative/2
                else: state = state + h*derivative
        temp = state[2] if dynamic else ocv_temp
        v = interpolation(state[0],ocv_temp,grid,temps,tables[0])-state[1]-current[i]*interpolation(state[0],temp,grid,temps,tables[1])*scales[0]
        output[i] = np.array([v,state[2],state[0]])
    return output


def arrays(model):
    return (np.asarray(model['soc_grid'],dtype=float),np.asarray(model['temperature_nodes_C'],dtype=float),
            np.asarray(model['tables'],dtype=float),np.array([model['thermal_capacity_J_K'],model['heat_transfer_W_K']]),
            np.array(model.get('aging_scales',[1.,1.,1.]),dtype=float))


def predict_fast(model, stream):
    grid,temps,tables,thermal,scales = arrays(model)
    ambient=np.full(len(stream['t']),float(np.median(stream['ambient'])))
    return simulate_fast(stream['t'],stream['current'],ambient,float(stream['temp'][0]),
          model['capacity_Ah'],grid,temps,tables,thermal,scales,model['dynamic_case_temperature'])


def predict_thevenin(model, stream):
    import thevenin
    grid,temps,tables,thermal,scales=arrays(model)
    ambient=float(np.median(stream['ambient']))
    params=dict(num_RC_pairs=1,soc0=1.,capacity=model['capacity_Ah'],gamma=0.,ce=1.,mass=.048,
         isothermal=False,Cp=thermal[0]/.048,T_inf=ambient+273.15,h_therm=thermal[1],A_therm=1.,
         ocv=lambda soc:float(interpolation(soc,ambient,grid,temps,tables[0])),M_hyst=lambda soc:0.)
    for key,index,scale in [('R0',1,scales[0]),('R1',2,scales[1]),('C1',3,scales[2]/scales[1])]:
        params[key]=lambda soc,temp,index=index,scale=scale:float(interpolation(soc,temp-273.15 if model['dynamic_case_temperature'] else ambient,grid,temps,tables[index])*scale)
    plant=thevenin.Prediction(params);plant.set_options(rtol=1e-8,atol=1e-10)
    state=thevenin.TransientState(1.,float(stream['temp'][0])+273.15,0.,np.zeros(1));output=[]
    for i,t in enumerate(stream['t']):
        if i:state=plant.take_step(state,float(stream['current'][i]),float(t-stream['t'][i-1]))
        v=state.voltage if i else params['ocv'](1.)-stream['current'][0]*params['R0'](1.,state.T_cell)
        output.append([float(v),float(state.T_cell-273.15),float(state.soc)])
    return np.asarray(output)


def observe(model, stream, voltage_noise, log_r_process=0., initial_soc=.85):
    from sox.filter.extended_kalman_filter import ExtendedKalmanFilter
    grid,temps,tables,_,scales=arrays(model)
    adaptive=log_r_process>0
    x=np.array([initial_soc,0.,0.])[:,None]
    filt=ExtendedKalmanFilter(np.eye(3),np.zeros((3,1)),np.diag([1e-8,1e-7,log_r_process]),
          np.array([[voltage_noise**2]]),x,np.diag([.15**2,.02**2,.15**2 if adaptive else 0.]))
    output=[]; clipped=0; minimum_eigenvalue=1.; start=time.perf_counter()
    def rc(soc,temp):
        return np.array([interpolation(float(soc),float(temp),grid,temps,tables[j])*scale for j,scale in [(1,scales[0]),(2,scales[1]),(3,scales[2]/scales[1])]])
    for i,t in enumerate(stream['t']):
        current=float(stream['current'][i]);temp=float(stream.get('sensor_temp_C',stream['temp'])[i]);dt=float(t-stream['t'][i-1]) if i else 0.
        soc=float(filt.x[0,0]);r0,r1,c1=rc(soc,temp);a=np.exp(-dt/(r1*c1))
        # Prediction is explicitly computed before consulting the current voltage observation.
        old=filt.x.copy(); pred=np.array([soc-dt*current/(3600*model['capacity_Ah']),a*float(old[1,0])+r1*(1-a)*current,float(old[2,0])])[:,None]
        f=np.diag([1.,a,1.]);eps=1e-5
        plus=rc(soc+eps,temp);minus=rc(soc-eps,temp)
        ap,am=np.exp(-dt/(plus[1]*plus[2])),np.exp(-dt/(minus[1]*minus[2]))
        f[1,0]=((ap*old[1,0]+plus[1]*(1-ap)*current)-(am*old[1,0]+minus[1]*(1-am)*current))/(2*eps)
        excited=adaptive and i>0 and abs(current)>.3 and abs(current-stream['current'][i-1])>.5 and .05<soc<.95
        filt.x=pred;filt.P=f@filt.P@f.T+np.diag([1e-8,1e-7,log_r_process if excited else 0.])
        if not excited:
            filt.P[2,:2]=0.;filt.P[:2,2]=0.
        def measurement(s):
            ocv=interpolation(float(s[0,0]),temp,grid,temps,tables[0]);rr=rc(s[0,0],temp)[0]*np.exp(float(s[2,0]))
            return np.array([[ocv-float(s[1,0])-current*rr]])
        def jacobian(s):
            lo=s.copy();hi=s.copy();lo[0,0]-=eps;hi[0,0]+=eps
            slope=(measurement(hi)[0,0]-measurement(lo)[0,0])/(2*eps)
            return np.array([[slope,-1.,-current*rc(s[0,0],temp)[0]*np.exp(s[2,0]) if excited else 0.]])
        predicted_voltage=float(measurement(filt.x)[0,0])
        used=bool(stream.get('measurement_mask',np.ones(len(stream['t']),dtype=bool))[i])
        innovation=float(stream['v'][i])-predicted_voltage if used else 0.
        if used:filt.update(np.array([stream['v'][i]]),measurement,jacobian)
        if not excited:filt.x[2,0]=old[2,0]
        before=filt.x.copy();filt.x[0,0]=np.clip(filt.x[0,0],0.,1.);filt.x[2,0]=np.clip(filt.x[2,0],np.log(.5),np.log(2.)) if adaptive else 0.
        clipped+=int(not np.array_equal(before,filt.x))
        filt.P=(filt.P+filt.P.T)/2
        if i%20==0:
            eig=float(np.linalg.eigvalsh(filt.P).min());minimum_eigenvalue=min(minimum_eigenvalue,eig)
            if eig < -1e-10 or not np.isfinite(filt.x).all():raise RuntimeError('Augmented EKF state/covariance invalid')
        output.append([float(filt.x[0,0]),float(np.exp(filt.x[2,0])),predicted_voltage,innovation,float(filt.P[0,0]**.5),float(excited)])
    return np.asarray(output),dict(mean_filter_step_ms=(time.perf_counter()-start)*1000/len(output),state_projection_count=clipped,
              minimum_covariance_eigenvalue=minimum_eigenvalue)

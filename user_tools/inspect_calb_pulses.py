from scipy.io import loadmat
from scipy.integrate import cumulative_trapezoid
import numpy as np

for kind in ('hppc_1c','hppc_c3'):
    p=f'data/public/calb_matched_v2/Temperature_25C/{kind}/59294.mat'
    x=loadmat(p,simplify_cells=True)['Data'];t=np.asarray(x['Times']);i=np.asarray(x['CurrentA']);v=np.asarray(x['VoltageV'])
    # Contiguous high-current runs; report locations before designing fitting windows.
    on=abs(i)>5.; edge=np.diff(np.r_[False,on,False].astype(int));a=np.flatnonzero(edge==1);b=np.flatnonzero(edge==-1)-1
    ah=cumulative_trapezoid(i,t,initial=0)/3600
    print(kind,len(a),'integrated Ah',ah[-1])
    for j,k in zip(a[:35],b[:35]):
        print(' t',round(t[j],1),'duration',round(t[k]-t[j],1),'I',round(float(np.median(i[j:k+1])),1),
              'start soc',round(float(1+ah[j]/53.3),3),'v',round(float(v[j]),3))

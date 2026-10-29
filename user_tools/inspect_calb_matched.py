"""Summarize CALB MAT structure without loading Python pickle data."""
from pathlib import Path
import numpy as np
from scipy.io import loadmat


def summarize(x,indent=''):
    if isinstance(x,dict):
        for k,v in x.items():
            print(indent+k+': ',end='');summarize(v,indent+'  ')
    elif isinstance(x,list):
        print('list',len(x))
        if x:summarize(x[0],indent+'  ')
    elif isinstance(x,np.ndarray):
        if x.dtype.kind in 'fiu' and x.size:
            print('array',x.shape,'min/max',np.nanmin(x),np.nanmax(x),'first/last',x.flat[0],x.flat[-1])
        else:print('array',x.shape,x.dtype)
    else: print(type(x).__name__,str(x)[:150])


def main():
    root=Path('data/public/calb_matched_v2')
    for p in sorted(root.rglob('59294.mat')):
        print('\n',p)
        summarize({k:v for k,v in loadmat(p,simplify_cells=True).items() if not k.startswith('__')})


if __name__=='__main__':main()

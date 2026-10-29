"""Finite normal KG by an affine upper envelope (established KG computation)."""
from __future__ import annotations
import math
import numpy as np
from scipy.special import ndtr


def normal_envelope_gain(mean, slope):
    """E[max_i(mean_i+slope_i Z)]-max_i(mean_i), Z~N(0,1).

    Sort slopes and retain the upper convex envelope; integrate each active
    line against a standard normal. A common random shift has zero value.
    """
    a = np.asarray(mean, dtype=float)
    b = np.asarray(slope, dtype=float)
    if a.ndim != 1 or len(a) != len(b) or not len(a) or not np.isfinite(a+b).all():
        raise ValueError('Finite, nonempty one-dimensional lines required')
    a = a-a.max()
    b = b-b[0]
    order = np.lexsort((a,b))
    unique = []
    for i in order:
        if unique and b[i] == b[unique[-1]]:
            unique[-1] = int(i)  # Lexsort puts the largest intercept last.
        else:
            unique.append(int(i))
    hull, left = [], []
    for i in unique:
        intersection = -np.inf
        while hull:
            j = hull[-1]
            intersection = (a[j]-a[i])/(b[i]-b[j])
            if intersection > left[-1]:
                break
            hull.pop(); left.pop()
        if not hull:
            intersection = -np.inf
        hull.append(i); left.append(float(intersection))
    value = 0.
    for k,i in enumerate(hull):
        l = left[k]
        u = left[k+1] if k+1 < len(left) else np.inf
        mass = ndtr(-l)-ndtr(-u) if l >= 0 else ndtr(u)-ndtr(l)
        pl = math.exp(-.5*l*l)/math.sqrt(2*math.pi) if math.isfinite(l) else 0.
        pu = math.exp(-.5*u*u)/math.sqrt(2*math.pi) if math.isfinite(u) else 0.
        value += a[i]*mass+b[i]*(pl-pu)
    if value < -1e-9:
        raise ArithmeticError(f'Negative KG beyond rounding: {value}')
    return max(float(value),0.)


def action_scores(mean, covariance, f, offsets, actions, criterion):
    mu = offsets+f@mean
    h = np.asarray([a['h'] for a in actions])
    cross = covariance@h.T
    var_y = np.sum(h.T*cross,axis=0)+np.array([a['noise_sd']**2 for a in actions])
    response_slopes = (f@cross)/np.sqrt(var_y)
    if criterion == 'kg':
        raw = np.array([normal_envelope_gain(mu,response_slopes[:,i]) for i in range(len(actions))])
    elif criterion == 'contrast_variance':
        # A-optimal reduction in sum of variances of centered target responses.
        centered = response_slopes-response_slopes.mean(axis=0)
        raw = np.sum(centered**2,axis=0)
    elif criterion == 'ei':
        from scipy.stats import norm
        sd = np.sqrt(np.maximum(np.einsum('ij,jk,ik->i',f,covariance,f),1e-12))
        delta = mu-mu.max()
        z = delta/sd
        ei = delta*norm.cdf(z)+sd*norm.pdf(z)
        raw = np.array([ei[int(a['candidate_id'][1:])] if a['kind']=='target' else 0. for a in actions])
    else:
        raise ValueError('Unknown criterion')
    return raw/np.array([a['cost'] for a in actions])

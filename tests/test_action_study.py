import math
import numpy as np
import pytest
from scipy.integrate import quad
from scipy.stats import norm
from user_tools.workbench.action_study_numerics import normal_envelope_gain, action_scores


def test_affine_gaussian_controls_and_duplicates():
    assert normal_envelope_gain([3,3],[2,2]) == 0
    assert normal_envelope_gain([0,0],[-1,1]) == pytest.approx(math.sqrt(2/math.pi),abs=1e-13)
    assert normal_envelope_gain([0,0,0],[-1,1,1]) == pytest.approx(math.sqrt(2/math.pi),abs=1e-13)
    assert normal_envelope_gain([1,2],[0,0]) == 0


def test_upper_envelope_against_independent_quadrature():
    rng = np.random.default_rng(42)
    for _ in range(35):
        a,b = rng.normal(size=(2,13))
        points = sorted({float((a[j]-a[i])/(b[i]-b[j])) for i in range(13) for j in range(i)
                         if b[i]!=b[j] and -12 < (a[j]-a[i])/(b[i]-b[j]) < 12})
        expected,error = quad(lambda z:(np.max(a+b*z)-np.max(a))*norm.pdf(z),-12,12,
                              points=points,epsabs=2e-11,epsrel=2e-11,limit=250)
        assert error < 1e-8
        assert normal_envelope_gain(a,b) == pytest.approx(expected,abs=2e-10)
        assert normal_envelope_gain(a+7,b-4) == pytest.approx(expected,abs=2e-10)


def test_irrelevant_and_common_shift_do_not_buy_information():
    m = np.zeros(2); cov = np.eye(2)
    f = np.array([[1.,0.],[1.,0.]])
    actions = [{'h':[0,1],'noise_sd':.2,'cost':.5}, {'h':[1,0],'noise_sd':.2,'cost':1.}]
    for criterion in ['kg','contrast_variance']:
        np.testing.assert_allclose(action_scores(m,cov,f,np.array([0.,1.]),actions,criterion),0,atol=1e-12)

"""Public replay guards: labels cannot enter features or unrevealed selectors."""
import numpy as np
from user_tools.rg_loop.public_graphite import features, select_next


def test_features_ignore_performance_and_postfabrication_structure():
    rows=[dict(coating_speed_m_min=.1+i*.1,coating_gap_um=150,
               graphite_dry_pct=95,carbon_dry_pct=1,cmc_dry_pct=1.5,sbr_dry_pct=2.5,
               calendered=i%2,drying_temperature_label='60-80',D5_mean_mAh_g=300+i,
               porosity=45+i,active_mass_mg=15+i) for i in range(4)]
    a,names=features(rows)
    for r in rows:r.update(D5_mean_mAh_g=-1000,porosity=-1,active_mass_mg=-10)
    b,_=features(rows)
    np.testing.assert_equal(a,b)
    assert not any('D5' in n or 'porosity' in n or 'mass' in n for n in names)


def test_selector_only_uses_observed_labels_and_returns_candidate_index():
    x=np.array([[0.],[.3],[.7],[1.]])
    candidates=np.array([[.2],[.5],[.8]])
    for strategy in ['bo','random','spacefill']:
        i=select_next(x,np.array([200.,230.,300.,260.]),candidates,strategy=strategy,seed=3,noise=10)
        assert 0<=i<len(candidates)

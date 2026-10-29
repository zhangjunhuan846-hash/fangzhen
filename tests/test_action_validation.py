"""Decision evidence invariants and analytically checkable Gaussian updates."""
import io
import json
import numpy as np
import pytest
from user_tools.workbench.action_validation import (Posterior, initial_posterior,
    public_design, available_actions, select_action, kg_scores, SyntheticWorld,
    run_campaign)
from collections import Counter


def test_scalar_posterior_matches_conjugate_result():
    p = Posterior(np.array([0.]), np.array([[1.]]))
    q = p.update([1.], 2., 1.)
    np.testing.assert_allclose(q.mean, [1.])
    np.testing.assert_allclose(q.covariance, [[.5]])


def test_unobserved_truth_cannot_be_passed_to_selector():
    design = public_design('coupled_ranking_sensitive')
    actions = available_actions(design, Counter(), 10)
    actions[0]['truth'] = 1000
    with pytest.raises(ValueError, match='label-free'):
        select_action(initial_posterior('joint_cost_kg'), design, actions,
                      'joint_cost_kg', instance=0, step=0)


def test_tau_preserves_radius_diffusion_coupling_and_psd():
    p = initial_posterior('joint_cost_kg').update([0,0,0,-2,1,0], .4, .12)
    assert p.covariance[3,4] > 0
    assert np.linalg.eigvalsh(p.covariance).min() >= -1e-12
    assert p.covariance[3,3] > .2


def test_irrelevant_characterization_has_zero_target_kg():
    design = public_design('matched_no_coupling')
    p = initial_posterior('joint_cost_kg')
    actions = [a for a in available_actions(design, Counter(), 10) if a['kind']=='radius_characterization']
    np.testing.assert_allclose(kg_scores(p, design, actions), [0.], atol=1e-12)


def test_ranking_stable_common_shift_has_zero_diagnostic_kg():
    design = public_design('coupled_ranking_stable')
    p = initial_posterior('joint_cost_kg').update([0,0,0,-2,1,0], .4, .12)
    actions = [a for a in available_actions(design, Counter(), 10) if a['kind']=='radius_characterization']
    np.testing.assert_allclose(kg_scores(p, design, actions), [0.], atol=1e-12)
    chosen, reason = select_action(p, design, actions, 'joint_cost_kg', instance=0, step=0)
    assert chosen is None
    assert reason['stop_reason'] == 'no_positive_acquisition'


def test_campaign_reserves_confirmation_and_persists_before_reveal():
    class Observer(SyntheticWorld):
        def observe(self, a, design):
            if a['kind']=='target' or a['kind']=='radius_characterization':
                assert stream.getvalue().rstrip().endswith('}')
                assert json.loads(stream.getvalue().splitlines()[-1])['selected_action']['id']==a['id']
            return super().observe(a, design)
        def confirm(self, r):
            frozen = json.loads(final_stream.getvalue().splitlines()[-1])
            assert frozen['selected_id'] == r['id']
            assert frozen['phase'] == 'final_decision'
            return super().confirm(r)
    stream = io.StringIO()
    final_stream = io.StringIO()
    world = Observer('coupled_ranking_sensitive', 1000)
    r,t = run_campaign(world, 'joint_cost_kg', 10, 31, stream, final_stream)
    assert r['spent'] <= 10 + 1e-9
    assert not r['confirmation_used_for_training']
    assert r['confirmation_fee'] == 1.6
    assert all('final_confirmation' not in v['phase'] for v in r['observations'])
    assert abs(r['spent']-sum(v['cost'] for v in r['observations'])-1.6) < 1e-10
    assert len(stream.getvalue().splitlines()) == len(t)
    assert len(final_stream.getvalue().splitlines()) == 1


def test_world_noise_shared_and_outside_truth_not_in_model():
    design = public_design('outside_model_sinusoid')
    w = SyntheticWorld('outside_model_sinusoid', 1000)
    a = next(a for a in available_actions(design, Counter(),10) if a['kind']=='target' and a['candidate_id']=='x01')
    assert w.observe(a,design) == w.observe(a,design)
    raw = design[1]['offset'] + np.asarray(design[1]['target_h']) @ w.theta
    assert abs(w.target_truth(design[1])-raw) > 1e-4

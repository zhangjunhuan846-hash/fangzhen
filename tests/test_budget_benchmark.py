"""Meaningful replay invariants: budget, no hidden labels and paired controls."""
import io
import json
import numpy as np
import pytest
from user_tools.workbench.budget_benchmark import (affordable, doe_order, expected_improvement,
    one_campaign, scenario_cost, select_action, paired_statistics, write_csv)


def toy_rows():
    return [dict(record_id=f'c{i}', group_id=f'g{i}', batch_id='toy', target=300+12*i,
                 coating_speed_m_min=.1+i*.02, coating_gap_um=100+10*(i%3),
                 graphite_dry_pct=93+i%2, carbon_dry_pct=2, cmc_dry_pct=2, sbr_dry_pct=3-i%2,
                 calendered=i%2, drying_temperature_label='60') for i in range(9)]


def test_selector_rejects_candidate_labels():
    rows = toy_rows()
    with pytest.raises(ValueError, match='without hidden labels'):
        select_action(rows[:5], rows[5:], 'gp_ei', seed=0, step=0, threshold=360)


def test_doe_schedule_is_label_blind_and_cost_hash_is_target_blind():
    rows = toy_rows()
    initial = [r['record_id'] for r in rows[:5]]
    order = doe_order(rows, initial)
    costs = [scenario_cost(r, 'independent_cost_sensitivity') for r in rows]
    for row in rows:
        row['target'] = -999
    assert doe_order(rows, initial) == order
    assert [scenario_cost(r, 'independent_cost_sensitivity') for r in rows] == costs


def test_shared_initial_budget_and_unit_cost_control():
    rows = toy_rows()
    records = {}
    for policy in ['random', 'doe_maximin', 'gp_ei', 'cost_gp_ei']:
        buffer = io.StringIO()
        final, trace = one_campaign(rows, policy, 'equal_test_count', seed=2,
                                    budget=7, threshold=360, decisions=buffer)
        records[policy] = final
        assert final['spent_units'] == 7
        assert all(t['cost_units'] <= 7 for t in trace)
        assert all(not json.loads(line)['candidate_payload_has_target'] for line in buffer.getvalue().splitlines())
    assert len({r['initial_ids'] for r in records.values()}) == 1
    assert records['gp_ei']['selected_ids'] == records['cost_gp_ei']['selected_ids']
    assert [r['record_id'] for r in affordable([{'record_id':'a','cost_units':1.5},
                                                {'record_id':'b','cost_units':1}], 1)] == ['b']


def test_ei_zero_variance_and_paired_ties_are_not_wins():
    np.testing.assert_allclose(expected_improvement([2., -1.], [0., 0.], 1.), [1., 0.])
    stats = paired_statistics([1,2,3], [1,2,3])
    assert stats['wins'] == stats['losses'] == 0 and stats['ties'] == 3
    assert stats['bootstrap_95_lower'] == stats['bootstrap_95_upper'] == 0


def test_initial_and_feedback_trace_export_preserves_revealed_outcomes(tmp_path):
    import csv
    final, trace = one_campaign(toy_rows(), 'gp_ei', 'equal_test_count', seed=2,
                                budget=7, threshold=360, decisions=io.StringIO())
    path = tmp_path/'traces.csv'
    write_csv(path, trace)
    with path.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == len(trace) == 3
    assert rows[0]['selected_id'] == ''
    assert rows[-1]['selected_id'] == trace[-1]['selected_id']
    assert float(rows[-1]['revealed_D5_mAh_g']) == trace[-1]['revealed_D5_mAh_g']
    assert float(rows[-1]['best_D5_mAh_g']) == final['best_D5_mAh_g']

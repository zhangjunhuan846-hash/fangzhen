"""受控公式与科研记录关系的独立数值/边界检查，无 PyBaMM 依赖。"""
import unittest
from user_tools.rg_workstation import solve_constraints, normalize_and_validate, constraint_number, design_from_cells, SCHEMA


class WorkstationTests(unittest.TestCase):
    def test_registered_constraint_unit_conversion(self):
        self.assertEqual(constraint_number('area_cm2',100,'mm²'),1)
        self.assertEqual(constraint_number('current_mA',.002,'A'),2)
        self.assertEqual(constraint_number('active_fraction','90%','%'),.9)
        with self.assertRaises(ValueError):
            constraint_number('area_cm2',1,'guess')

    def test_bounds_intersect_and_fixed_conflicts_survive(self):
        cells={'设计计算':{'B5':'参数联动','B6':1,'B7':4,'B13':1,'B14':5}}
        records={'目标约束':[{'status':'已确认','variable':'total_loading_mg_cm2','variable_role':'bounded','unit':'mg/cm²','lower':6,'upper':10}]}
        result=design_from_cells(cells,records)
        self.assertEqual(result['status'],'conflict')
        self.assertTrue(any('下限大于上限' in x for x in result['issues']))
    def test_forward_unit_conversion(self):
        r = solve_constraints({'area_cm2': 1, 'total_loading_mg_cm2': 5, 'active_fraction': .9,
                               'q_ref_mAh_g': 330, 'c_rate': 1, 'thickness_um': 50})
        self.assertEqual(r['status'], 'solved')
        self.assertAlmostEqual(r['values']['active_mass_mg'], 4.5)
        self.assertAlmostEqual(r['values']['capacity_mAh'], 1.485)
        self.assertAlmostEqual(r['values']['bulk_density_g_cm3'], 1)

    def test_reverse_infeasible_loading(self):
        r = solve_constraints({'area_cm2': 1, 'active_fraction': .9, 'q_ref_mAh_g': 330,
                               'capacity_mAh': 2}, {'total_loading_mg_cm2': (None,5)})
        self.assertEqual(r['status'],'conflict')
        self.assertAlmostEqual(r['values']['total_loading_mg_cm2'], 6.734006734)
        self.assertTrue(any('大于上限' in m for m in r['issues']))

    def test_arbitrary_entry_mass_capacity_to_composition(self):
        r = solve_constraints({'active_mass_mg': 4.5, 'capacity_mAh': 1.485,
                               'area_cm2': 1, 'total_loading_mg_cm2': 5})
        self.assertAlmostEqual(r['values']['q_ref_mAh_g'],330)
        self.assertAlmostEqual(r['values']['active_fraction'],.9)

    def test_incomplete_does_not_invent_inputs(self):
        r=solve_constraints({'capacity_mAh':2})
        self.assertEqual(r['status'],'partial')
        self.assertNotIn('total_loading_mg_cm2',r['values'])

    def test_conflicting_known_values_not_overwritten(self):
        r=solve_constraints({'active_mass_mg':5,'q_ref_mAh_g':330,'capacity_mAh':2})
        self.assertEqual(r['status'],'conflict')
        self.assertEqual(r['values']['capacity_mAh'],2)

    def test_zero_current_and_rate_do_not_identify_capacity(self):
        r=solve_constraints({'current_mA':0,'c_rate':0})
        self.assertEqual(r['status'],'partial')
        self.assertNotIn('capacity_mAh',r['values'])

    def test_zero_rate_given_capacity_predicts_zero_current(self):
        r=solve_constraints({'capacity_mAh':2,'c_rate':0})
        self.assertEqual(r['values']['current_mA'],0)

    def test_invalid_fraction_nan_and_bounds(self):
        for known in ({'active_fraction':90},{'q_ref_mAh_g':float('nan')},{'area_cm2':True}):
            self.assertEqual(solve_constraints(known)['status'],'conflict')
        self.assertEqual(solve_constraints({'area_cm2':1},{'area_cm2':('bad',None)})['status'],'conflict')

    def test_duplicate_and_dangling_id(self):
        rows={t['sheet']:[] for t in SCHEMA['tables']}
        rows['原料']=[{'_row':7,'batch_id':'A','source':'real'},{'_row':8,'batch_id':'A','source':'real'}]
        rows['样品工艺']=[{'_row':7,'prepare_id':'P1','sample_id':'S1','batch_id':'missing','status':'计划中'}]
        _,issues=normalize_and_validate(rows)
        self.assertTrue(any('编号重复' in i['message'] for i in issues))
        self.assertTrue(any('找不到对应' in i['message'] for i in issues))

    def test_performance_mass_units_and_wrong_cell(self):
        rows={t['sheet']:[] for t in SCHEMA['tables']}
        rows['原料']=[{'_row':7,'batch_id':'A','source':'real'}]
        rows['样品工艺']=[{'_row':7,'prepare_id':'P','sample_id':'S','batch_id':'A','status':'未再生对照'}]
        rows['极片']=[{'_row':7,'electrode_id':'E','prepare_id':'P','area_cm2':1,'dry_coating_mass_mg':5,'active_fraction':.9}]
        rows['电芯']=[{'_row':7,'cell_id':'C','electrode_id':'E'}]
        rows['测试']=[{'_row':7,'test_id':'T','cell_id':'C','protocol':'rate_capability','physics_role':'validation',
                     'campaign_role':'optimization','c_rate':1,'direction':'脱锂','raw_file_path':'raw.csv'}]
        rows['性能记录']=[{'_row':7,'result_id':'R','cell_id':'C','rate_test_id':'T','q_1C_mAh':1.26,
                       'first_lithiation_mAh':1,'first_delithiation_mAh':.9,'rate_cycle':3}]
        records,issues=normalize_and_validate(rows)
        self.assertAlmostEqual(records['性能记录'][0]['q_1C_mAh_g'],280)
        self.assertAlmostEqual(records['性能记录'][0]['ice'],.9)
        self.assertFalse(any(i['severity']=='error' for i in issues))
        rows['测试'][0]['cell_id']='other'
        _,issues=normalize_and_validate(rows)
        self.assertTrue(any('另一颗电芯' in i['message'] for i in issues))


if __name__=='__main__':
    unittest.main()

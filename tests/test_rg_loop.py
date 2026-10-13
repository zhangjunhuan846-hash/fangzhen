import unittest
from user_tools.rg_loop.constraints import diffusion_relation,benchmark_cases
from user_tools.rg_loop.credibility import physical_decision,gate_ablation


class ConstraintAndGateTests(unittest.TestCase):
    def test_generated_algebra_cases(self):
        r=benchmark_cases(600)
        self.assertEqual(r['passed'],600)
    def test_tau_reverse_does_not_grant_identifiability(self):
        r=diffusion_relation(radius_m=5e-6,tau_s=10000,evidence='measured_radius_assumed_tau')
        self.assertAlmostEqual(r['values']['diffusivity_m2_s'],2.5e-15)
        self.assertEqual(r['parameter_verdict'],'not_assessed')
        r=diffusion_relation(diffusivity_m2_s=2.5e-15,tau_s=10000)
        self.assertAlmostEqual(r['values']['radius_m'],5e-6)
    def test_tau_conflict_and_underdetermined(self):
        self.assertEqual(diffusion_relation(radius_m=5e-6)['status'],'partial')
        self.assertEqual(diffusion_relation(radius_m=5e-6,diffusivity_m2_s=2.5e-15,tau_s=2)['status'],'conflict')
    def test_synthetic_cannot_become_real_material_evidence(self):
        e=dict(evidence_type='synthetic_recovery',parameter_verdict='identifiable',scale_aligned=True,
               geometry_measured=True,holdout_pass=True,model_consistency_pass=True)
        self.assertEqual(physical_decision(e)['action'],'supplement_experiment')
    def test_gate_ablation_scope(self):
        r=gate_ablation()
        self.assertTrue(all(x['credible']=='supplement_experiment' for x in r['rows']))
    def test_rate_alias_cannot_disguise_training_as_holdout(self):
        from types import SimpleNamespace
        from user_tools.rg_loop.physics import holdout_rate_guard
        adapter=SimpleNamespace(rate_info=lambda rate:{'rate_slug':{'C2':'C0p5','C0p5':'C0p5','1C':'C1'}[rate]})
        with self.assertRaises(ValueError): holdout_rate_guard(adapter,'C2','C0p5')
        holdout_rate_guard(adapter,'C2','1C')
    def test_windows_workbook_path_resolves_under_wsl(self):
        import os
        from user_tools.rg_loop.physics import workbook_data_path
        from pathlib import Path
        value=workbook_data_path('C:\\data\\graphite\\ocp.csv','/tmp')
        if os.name!='nt': self.assertEqual(str(value),'/mnt/c/data/graphite/ocp.csv')
        else: self.assertTrue(value.is_absolute())
        self.assertEqual(workbook_data_path('raw/ocp.csv',Path('/tmp')),Path('/tmp/raw/ocp.csv'))


class OptimizationTests(unittest.TestCase):
    def setUp(self):
        from user_tools.rg_loop.optimization import candidate_grid
        self.candidates=candidate_grid(5)
        self.obs=[dict(candidate_id=r['candidate_id'],x=r['x'],batch='A',q=250,ice=.9,yield_=.9,
                       status='completed',role='optimization') for r in self.candidates[:3]]
        for r in self.obs: r['yield']=r.pop('yield_')
    def test_pending_and_measured_are_not_reselected(self):
        from user_tools.rg_loop.optimization import recommend
        pending=self.candidates[3]['candidate_id']
        r=recommend(self.obs,self.candidates,strategy='doe',pending=[pending])
        self.assertNotIn(r['candidate_id'],[x['candidate_id'] for x in self.obs]+[pending])
    def test_final_confirmation_and_future_state_rejected(self):
        from user_tools.rg_loop.optimization import recommend
        self.obs[0]['role']='final_confirmation'
        with self.assertRaises(ValueError): recommend(self.obs,self.candidates)
        self.obs[0]['role']='optimization';self.obs[0]['status']='pending'
        with self.assertRaises(ValueError): recommend(self.obs,self.candidates)
    def test_other_batch_cannot_be_pooled(self):
        from user_tools.rg_loop.optimization import recommend
        self.obs[0]['batch']='B'
        with self.assertRaises(ValueError): recommend(self.obs,self.candidates,batch='A')
    def test_gp_changes_with_new_actual_feedback(self):
        from user_tools.rg_loop.optimization import recommend
        r1=recommend(self.obs,self.candidates)
        self.obs.append({**self.obs[0],'candidate_id':self.candidates[4]['candidate_id'],'x':self.candidates[4]['x'],'q':320})
        r2=recommend(self.obs,self.candidates)
        self.assertNotEqual(r1['training_snapshot'],r2['training_snapshot'])
        self.assertEqual(r2['training_count'],4)


if __name__=='__main__': unittest.main()

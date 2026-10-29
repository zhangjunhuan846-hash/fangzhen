import io
import numpy as np
import pandas as pd
import pytest

from user_tools.workbench.research_extensions import uncertainty_audit, ax_recommend, helao_plan


def _audit_data():
    rows=[]
    for role, offset in [('reference',0),('calibration',100),('test',200)]:
        for i in range(12):
            rows.append({'role':role,'group_id':str(offset+i),'predicted':.7+i*.001,
                         'observed':.72+i*.002,'x':i/12})
    return pd.DataFrame(rows)


def test_uncertainty_never_uses_test_labels_to_fit_intervals():
    frame=_audit_data(); config={'feature_columns':['x'],'alpha':.1}
    a=uncertainty_audit(frame.to_csv(index=False).encode(),config)
    frame.loc[frame.role=='test','observed']=10
    b=uncertainty_audit(frame.to_csv(index=False).encode(),config)
    for name in a['methods']:
        assert a['methods'][name]['half_width']==b['methods'][name]['half_width']
    assert b['methods']['kmm_cp']['coverage']==0
    with pytest.raises(ValueError):uncertainty_audit(frame.to_csv(index=False).encode(),{'feature_columns':['observed']})


def test_uncertainty_rejects_overlapping_groups():
    frame=_audit_data();frame.loc[frame.role=='test','group_id']='100'
    with pytest.raises(ValueError,match='分组隔离'):
        uncertainty_audit(frame.to_csv(index=False).encode(),{'feature_columns':['x']})


def test_ax_uses_botorch_for_imported_observations():
    raw=b'x,y\n1,1\n2,4\n3,6\n4,8\n5,9\n6,10\n'
    result=ax_recommend(raw,{'parameters':[{'name':'x','bounds':[0,10]}],'objectives':[{'name':'y'}]})
    assert result['generator']=='BoTorch' and 0 <= result['candidate']['x'] <= 10


def test_helao_offline_sequence_model():
    result=helao_plan(b'experiment_name,temperature_C\ncarbonize,900\n',{})
    assert result['sequence']['planned_experiments'][0]['experiment_params']['temperature_C']==900

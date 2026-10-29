"""Named optional backends, each executed in its own bounded worker process."""
import argparse
import hashlib
import json
import os
from pathlib import Path

# Cap native math thread pools before importing any numerical library.
for _key in ['OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS']:
    os.environ[_key] = '1'
os.environ.setdefault('MPLBACKEND', 'Agg')

from user_tools.workbench.engineering_contracts import normalize


def run(config, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    raw = None
    if config.get('source_path'):
        raw = Path(config['source_path']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != config['source_sha256']:
            raise ValueError('原始文件在提交后发生变化，拒绝运行。')
    request = normalize(config['engineering_config'], raw)
    request['source_sha256'] = config.get('source_sha256')
    action = request['action']
    if action == 'commercial_adaptive':
        from user_tools.workbench.engineering_adaptive import run_adaptive
        return run_adaptive(request,out)
    if action == 'calb_validation':
        from user_tools.workbench.engineering_calb_validation_v3 import run_calb_v3
        return run_calb_v3(request,out)
    if action == 'crosscell_validation':
        from user_tools.workbench.engineering_crosscell import run_crosscell
        return run_crosscell(request,out)
    if action == 'tesla_refined':
        from user_tools.workbench.engineering_tesla_refined import run_tesla_refined
        return run_tesla_refined(request,out)
    if action == 'stanford_frozen':
        from user_tools.workbench.engineering_stanford_case import run_stanford_case
        return run_stanford_case(request,out)
    if action == 'eis_hppc_ablation':
        from user_tools.validate_calb_eis_hppc_ablation_20261029 import run_ablation
        return run_ablation(request,out)
    if action == 'eis_audit':
        from user_tools.workbench.engineering_eis_audit import run_eis_audit
        return run_eis_audit(request,out)
    if action == 'eis_grid':
        from user_tools.workbench.engineering_eis_grid import run_grid
        return run_grid(request,out,raw)
    if action == 'safety_bench':
        from user_tools.workbench.engineering_safety import run_safety
        return run_safety(request,out)
    if action == 'frontier':
        from user_tools.workbench.engineering_frontier import run_frontier
        return run_frontier(request, out, raw)
    if action == 'batterylife':
        from user_tools.workbench.engineering_batterylife import run_batterylife
        return run_batterylife(request, out)
    if action == 'commercial_validation':
        from user_tools.workbench.engineering_commercial import run_commercial
        return run_commercial(request, out)
    if action == 'ecm_bms':
        from user_tools.workbench.engineering_bms import run_bms
        return run_bms(request, out, raw)
    if action == 'mpc':
        from user_tools.workbench.engineering_control import run_control
        return run_control(request, out, raw)
    if action == 'eis_joint':
        from user_tools.workbench.engineering_identification import run_joint_eis
        return run_joint_eis(request, out, raw)
    if action == 'pack':
        from user_tools.workbench.engineering_pack import run_pack
        return run_pack(request, out, raw)
    if action in ['cycler', 'can']:
        from user_tools.workbench.engineering_io import run_cycler, run_can
        return (run_cycler if action == 'cycler' else run_can)(request, out, raw)
    if action in ['batteryml', 'faults']:
        from user_tools.workbench.engineering_ml import run_batteryml, run_faults
        return (run_batteryml if action == 'batteryml' else run_faults)(request, out, raw)
    if action == 'optimize':
        from user_tools.workbench.engineering_optimize import run_optimize
        return run_optimize(request, out, raw)
    raise ValueError('Unknown engineering action')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    run(json.loads(Path(args.config).read_text(encoding='utf-8')), args.out)

"""Historical version adapter, preserving the original independent verifier.

Only its data-root and executed-source location change. Historical v2 cannot
require today's v3 working source; it must check its own executed snapshot.
The independent metric/selection calculations are left byte-for-byte intact.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

def main():
    original=Path('outputs/analysis/action_validation_20261014_v2/audit_recompute.py')
    target=Path('outputs/analysis/action_study_20261015/reconstruction'); target.mkdir(exist_ok=False)
    source=original.read_text(encoding='utf-8')
    old_root='ROOT = Path(__file__).resolve().parent'
    new_root='ROOT = Path("outputs/analysis/action_validation_20261014_v2").resolve()'
    old_source='current_source = ROOT.parents[2] / "user_tools" / "workbench" / "action_validation.py"'
    new_source='current_source = ROOT / "source_snapshot.py"'
    assert source.count(old_root)==1 and source.count(old_source)==1
    adapted=source.replace(old_root,new_root).replace(old_source,new_source)
    path=target/'legacy_independent_adapted.py'; path.write_text(adapted,encoding='utf-8')
    run=subprocess.run([sys.executable,str(path)],capture_output=True,text=True)
    (target/'legacy_stdout.txt').write_text(run.stdout,encoding='utf-8')
    (target/'legacy_stderr.txt').write_text(run.stderr,encoding='utf-8')
    if run.returncode: raise RuntimeError(run.stderr)
    legacy=json.loads(run.stdout)
    second=subprocess.run([sys.executable,'outputs/analysis/action_validation_20261014_v3/audit_terminal_patch.py'],
                          capture_output=True,text=True)
    (target/'terminal_stdout.txt').write_text(second.stdout,encoding='utf-8')
    (target/'terminal_stderr.txt').write_text(second.stderr,encoding='utf-8')
    if second.returncode: raise RuntimeError(second.stderr)
    terminal=json.loads(second.stdout)
    receipt={'status':'PASS','legacy':legacy,'terminal':terminal,
             'original_helper_sha256':hashlib.sha256(original.read_bytes()).hexdigest(),
             'adapted_helper_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
             'exact_adapter_changes':[{'before':old_root,'after':new_root},{'before':old_source,'after':new_source}],
             'original_direct_run':'Correctly rejected because working v3 source differs from executed v2 snapshot; no original evidence changed.'}
    (target/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(json.dumps({'status':'PASS','legacy_campaigns':legacy['campaigns'],'terminal_records':terminal['terminal_records']}))
if __name__=='__main__': main()

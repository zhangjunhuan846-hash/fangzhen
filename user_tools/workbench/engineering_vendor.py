"""Pinned upstream copies with explicit, hash-audited compatibility edits."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import sys

from user_tools.workbench.engineering_common import ROOT, save


PATCHES = {
 'mobo-osd': {
  'mobo_osd/gp.py': [('cholesky_jitter(double=1e-1)', 'cholesky_jitter(double_value=1e-1)')],
  'mobo_osd/qHVI.py': [
   ('from botorch.sampling.samplers import MCSampler, SobolQMCNormalSampler', 'from botorch.sampling.base import MCSampler\nfrom botorch.sampling.normal import SobolQMCNormalSampler'),
   ('num_samples=1, collapse_batch_dims=True', 'sample_shape=torch.Size([1])')],
 },
 'rMFBO': {
  'src/model.py': [
   ('train_x, train_y, likelihood, outcome_transform=', 'train_x, train_y, likelihood=likelihood, outcome_transform='),
   ('RBFGPRegressionModel(feasture_extractor(model.train_inputs[0]),', 'RBFGPRegressionModel(model.scale_to_bounds(feasture_extractor(model.train_inputs[0])),')],
 },
 'CAMO': {
  'FidelityFusion_Models/__init__.py': None,
  'GaussianProcess/cigp_v10.py': [
   ('var = var + self.log_beta.exp().pow(-1)', 'var = var + self.log_beta.exp().pow(-1) * torch.eye(var.shape[-1], device=var.device, dtype=var.dtype)')],
 },
 'BatteryLife': {},
}


def upstream(name, out):
    lock = json.loads((ROOT/'configs/engineering_sources.lock.json').read_text(encoding='utf-8'))
    entry = next(x for x in lock['sources'] if x['directory'] == name)
    source = ROOT/'data/vendor'/name
    commit = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if commit != entry['commit']:
        raise ValueError('Upstream commit differs from source lock: '+name)
    if subprocess.check_output(['git', '-c', 'core.autocrlf=true', '-c', 'core.filemode=false', '-C', str(source), 'status', '--porcelain', '--untracked-files=no'], text=True).strip():
        raise ValueError('Upstream tracked source was modified: '+name)
    # Each worker owns its copy; simultaneous jobs never patch a shared module tree.
    dest = Path(out)/'upstream'/name
    dest.mkdir(parents=True, exist_ok=True)
    audit = {'repository': entry['repository'], 'commit': commit, 'files': {}, 'patches': []}
    for license_file in entry.get('license_files', []):
        shutil.copy2(source/license_file, dest/Path(license_file).name)
    for p in source.rglob('*.py'):
        if '.git' in p.parts:
            continue
        rel = p.relative_to(source).as_posix()
        raw = p.read_bytes()
        text = raw.decode('utf-8-sig')
        if rel in PATCHES[name]:
            edits = PATCHES[name][rel]
            if edits is None:
                text = '# Only the CAR submodule used by this adapter is imported.\n'
                audit['patches'].append({'file': rel, 'reason': 'remove eager imports of absent example modules'})
            else:
                for old, new in edits:
                    if old not in text:
                        raise ValueError('Compatibility patch does not match pinned source: '+rel+' '+old)
                    text = text.replace(old, new)
                    audit['patches'].append({'file': rel, 'before': old, 'after': new})
        target = dest/rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')
        audit['files'][rel] = {'original_sha256': hashlib.sha256(raw).hexdigest(),
                              'executed_sha256': hashlib.sha256(target.read_bytes()).hexdigest()}
    save(Path(out)/('upstream_'+name+'.json'), audit)
    sys.path.insert(0, str(dest))
    return audit

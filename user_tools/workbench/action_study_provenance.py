"""Post-run documentation receipt; never upgrades the original freeze claim."""
import datetime
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sys
import numpy as np


def main():
    root = Path('outputs/analysis/action_study_20261015')
    out = root / 'provenance'
    out.mkdir(exist_ok=False)
    protocol = json.loads((root / 'frozen_protocol.json').read_text())
    original = protocol['source_hashes']
    helpers = [
        'user_tools/__init__.py', 'user_tools/workbench/__init__.py',
        'tests/test_action_validation.py',
        'user_tools/workbench/action_study_precision.py',
        'user_tools/workbench/action_study_quad_refinement.py',
        'user_tools/workbench/action_study_report.py',
        'user_tools/workbench/action_study_completion.py',
        'user_tools/workbench/action_study_provenance.py',
        'user_tools/workbench/archive_action_references.py',
        'user_tools/workbench/reconstruct_legacy_actions.py',
    ]
    files = {}
    for name in list(original) + helpers:
        path = Path(name)
        if not path.exists():
            files[name] = {'exists': False}
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        files[name] = {
            'exists': True, 'sha256': digest, 'bytes': path.stat().st_size,
            'in_original_freeze': name in original,
            'matches_original_freeze': digest == original[name] if name in original else None,
        }
        if name in original:
            assert digest == original[name]
        else:
            target = out / 'auxiliary_source' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())
    packages = {k: importlib.metadata.version(k) for k in ['numpy', 'scipy', 'matplotlib', 'pytest']}
    receipt = {
        'recorded_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'provenance': 'POST-RUN local receipt; not a pre-run environment lock or trusted external timestamp',
        'python': sys.version, 'executable': sys.executable,
        'platform': platform.platform(), 'machine': platform.machine(),
        'packages': packages,
        'numpy_build_config': getattr(np.__config__, 'CONFIG', {}),
        'frozen_protocol_sha256': hashlib.sha256((root / 'frozen_protocol.json').read_bytes()).hexdigest(),
        'sources': files,
        'limits': ['Selected packages only; not a complete transitive dependency/OS lock.',
                   'Auxiliary snapshots were added after results and do not prove pre-run identity.',
                   'Original frozen source list and all experiment/statistical settings are unchanged.'],
    }
    (out / 'post_run_environment.json').write_text(json.dumps(receipt, indent=2, default=str), encoding='utf-8')
    (out / 'requirements_selected.txt').write_text(
        '# Post-run selected versions only; not a complete lock.\n' +
        '\n'.join(f'{k}=={v}' for k, v in packages.items()) + '\n', encoding='utf-8')
    print(json.dumps({'receipt': str(out / 'post_run_environment.json'), 'packages': packages,
                      'all_original_frozen_sources_unchanged': True}))


if __name__ == '__main__':
    main()

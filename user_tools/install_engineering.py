"""Install/recheck optional WSL runtimes without modifying the science core."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def checked(args, capture=False):
    result = subprocess.run([str(x) for x in args], cwd=ROOT, check=True, text=True,
                            encoding='utf-8', errors='replace', capture_output=capture,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return result.stdout.strip() if capture else None


def wpath(path):
    path = str(Path(path).resolve()).replace('\\', '/')
    return '/mnt/'+path[0].lower()+'/'+path[3:]


def wsl(*args, capture=False):
    return checked(['wsl.exe', '-d', 'Ubuntu', '--cd', wpath(ROOT), '--', *args], capture)


def inventory(runtimes, sources):
    manifest = {'schema': 1, 'runtimes': {}, 'sources': sources,
       'scope': 'optional engineering adapters; core Python/PyBaMM not replaced',
       'source_lock_sha256': hashlib.sha256((ROOT/'configs/engineering_sources.lock.json').read_bytes()).hexdigest()}
    probes = {'engineering': ['thevenin', 'do-mpc', 'sox', 'botorch', 'PyProBE-Data', 'python-can', 'cantools', 'pybop', 'numpy', 'pybamm', 'numba', 'impedance'],
              'pack': ['liionpack', 'pybamm', 'numpy', 'pandas', 'casadi'],
              'batteryml_legacy': ['BatteryML', 'numpy', 'pandas', 'torch', 'scikit-learn'],
              'frontier': ['botorch', 'gpytorch', 'pymoo', 'reformer-pytorch', 'torch', 'numpy']}
    for key, python in runtimes.items():
        script = 'import importlib.metadata as m,json;print(json.dumps({n:m.version(n) for n in '+repr(probes[key])+'}))'
        packages = json.loads(wsl(python, '-c', script, capture=True))
        frozen = wsl(python, '-m', 'pip', 'freeze', capture=True)
        manifest['runtimes'][key] = {'python': python, 'packages': packages,
             'pip_freeze_sha256': hashlib.sha256(frozen.encode()).hexdigest()}
        (ROOT/'data'/('engineering_'+key+'.freeze.txt')).write_text(frozen+'\n', encoding='utf-8')
    target = ROOT/'data/engineering_runtime.local.json'
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Runtime manifest:', target)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--inventory-only', action='store_true', help='Recheck existing installations without installing packages.')
    parser.add_argument('--base-python', default='/home/zjh/miniforge3/envs/pybamm/bin/python')
    args = parser.parse_args()
    home = wsl(args.base_python, '-c', 'from pathlib import Path;print(Path.home())', capture=True)
    runtime_root = home+'/.local/share/fangzhen'
    runtimes = {name: runtime_root+'/'+name+'/bin/python' for name in ['engineering', 'pack', 'batteryml_legacy', 'frontier']}
    sources = json.loads((ROOT/'configs/engineering_sources.lock.json').read_text())['sources']
    if not args.inventory_only:
        vendor = ROOT/'data/vendor'; vendor.mkdir(parents=True, exist_ok=True)
        for source in sources:
            destination = vendor/source['directory']
            if not destination.exists():
                checked(['git', 'clone', '--no-checkout', '--filter=blob:none', 'https://github.com/'+source['repository']+'.git', destination])
                checked(['git', '-C', destination, 'fetch', '--depth', '1', 'origin', source['commit']])
                checked(['git', '-C', destination, 'checkout', '--detach', source['commit']])
            actual = checked(['git', '-C', destination, 'rev-parse', 'HEAD'], capture=True)
            if actual != source['commit'] or checked(['git','-C',destination,'status','--porcelain','--untracked-files=no'], capture=True):
                raise RuntimeError('Source checkout differs from lock; preserved without reset: '+str(destination))
        for name, python in runtimes.items():
            command = [args.base_python, '-m', 'venv']
            if name != 'batteryml_legacy':
                command += ['--system-site-packages']
            wsl(*command, runtime_root+'/'+name)
        main_python = runtimes['engineering']
        wsl(main_python, '-m', 'pip', 'install', 'torch==2.9.1', '--index-url', 'https://download.pytorch.org/whl/cpu')
        wsl(main_python, '-m', 'pip', 'install', '-r', 'requirements-engineering.txt')
        # lcapy's obsolete importlib backport breaks modern pip's build.
        # Its numeric dependencies are already supplied; plotting is unused.
        wsl(main_python, '-m', 'pip', 'install', '--no-deps', 'lcapy==1.26', 'liionpack==0.4.0', 'data/vendor/sox')
        legacy = runtimes['batteryml_legacy']
        wsl(legacy, '-m', 'pip', 'install', 'torch==2.9.1', '--index-url', 'https://download.pytorch.org/whl/cpu')
        wsl(legacy, '-m', 'pip', 'install', '-r', 'requirements-batteryml-legacy.txt')
        wsl(legacy, '-m', 'pip', 'install', '--no-deps', 'data/vendor/BatteryML')
        # Keep liionpack's older PyBaMM isolated from the platform and PyBOP.
        link = "import site;from pathlib import Path;p=Path(site.getsitepackages()[0])/'engineering_shared.pth';p.write_text("+repr(runtime_root+'/engineering/lib/python3.11/site-packages\n')+")"
        wsl(runtimes['pack'], '-c', link)
        wsl(runtimes['pack'], '-m', 'pip', 'install', 'pybamm==24.9.0', 'numpy==1.26.4', 'pandas==2.2.3', 'casadi==3.6.7')
        link = "import site;from pathlib import Path;p=Path(site.getsitepackages()[0])/'batteryml_shared.pth';p.write_text("+repr(runtime_root+'/batteryml_legacy/lib/python3.11/site-packages\n')+")"
        wsl(runtimes['frontier'], '-c', link)
        wsl(runtimes['frontier'], '-m', 'pip', 'install', '-r', 'requirements-frontier.txt')
    inventory(runtimes, sources)


if __name__ == '__main__':
    main()

$ErrorActionPreference = 'Stop'
$MultichemScript = @'
set -eu
base=/home/zjh/miniforge3/envs/pybamm/bin/python
envdir=/home/zjh/.local/share/fangzhen/multichem-20261029
"$base" -m venv --system-site-packages "$envdir"
"$envdir/bin/python" -m pip install --disable-pip-version-check electrokitty==1.0.11.6 ixdat==0.4.0 fastnda==1.3.1 xgboost-cpu==3.2.0 catboost==1.2.10
# Only the OSBAD statistical module is used; full OSBAD's torch/CUDA stack is not installed.
"$envdir/bin/python" -m pip install --disable-pip-version-check --no-deps osbad==1.7.0
"$envdir/bin/python" -m pip install --disable-pip-version-check torch==2.9.1 --index-url https://download.pytorch.org/whl/cpu
"$envdir/bin/python" -m pip install --disable-pip-version-check shap==0.51.0 tabicl==2.2.0 tabpfn==9.2.0 ax-platform==1.3.1
helao=/home/zjh/.local/share/fangzhen/sources/helao-async
if [ ! -d "$helao/.git" ]; then
    mkdir -p "$(dirname "$helao")"
    git clone https://github.com/High-Throughput-Experimentation/helao-async.git "$helao"
    git -C "$helao" checkout ba910c4c2bdcbcbc49476e32a5b20ca0abb93529
fi
"$envdir/bin/python" -c 'from electrokitty import ElectroKitty; from ixdat import Measurement; from osbad.stats import outlier_method; import fastnda; print("Multichem upstream modules ready")'
'@
$MultichemScript = $MultichemScript.Replace("`r", "")
$MultichemScript | wsl.exe -d Ubuntu -- bash -s
if ($LASTEXITCODE -ne 0) { throw '锂钠扩展安装失败，请查看上述输出。' }

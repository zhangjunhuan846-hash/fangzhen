param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$SustainProject = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$SustainRuntime = Join-Path $SustainProject 'data\runtime\sustainability'
$SustainCommit = 'e834058d2b361c8009fe53bd73347d84b17b4704'
$SustainSource = Join-Path $SustainProject 'data\backends\recycle_cost_tool_e834058'
& $Python -c 'import sys; assert sys.version_info >= (3,13), "This backend requires Python 3.13 or newer"'
if ($LASTEXITCODE -ne 0) { throw 'Use Python 3.13 or newer for this independent backend.' }
if (-not (Test-Path -LiteralPath (Join-Path $SustainRuntime 'Scripts\python.exe'))) {
    & $Python -m venv $SustainRuntime
    if ($LASTEXITCODE -ne 0) { throw 'Could not create backend virtual environment.' }
}
$SustainPython = Join-Path $SustainRuntime 'Scripts\python.exe'
& $SustainPython -m pip install --disable-pip-version-check 'bw2calc==2.5.0' 'bw2data==4.7' 'numpy==2.5.4' 'pandas==3.0.6' 'scipy==1.18.1' 'openpyxl==3.1.5'
if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed.' }
if (-not (Test-Path -LiteralPath (Join-Path $SustainSource 'src\recycle_cost\model.py'))) {
    $SustainTree = Invoke-RestMethod -Uri ('https://api.github.com/repos/zhouzhq2021/recycle_cost_tool/git/trees/' + $SustainCommit + '?recursive=1')
    $SustainPaths = @($SustainTree.tree | Where-Object { $_.type -eq 'blob' -and ($_.path -like 'src/recycle_cost/*.py' -or $_.path -in @('docs/analysis/everbatt_analysis.json','EverBatt 2023.xlsm','README.md','LICENSE','pyproject.toml')) } | Select-Object -ExpandProperty path)
    foreach ($SustainPath in $SustainPaths) {
        $SustainDest = [IO.Path]::GetFullPath((Join-Path $SustainSource $SustainPath))
        if (-not $SustainDest.StartsWith([IO.Path]::GetFullPath($SustainSource) + [IO.Path]::DirectorySeparatorChar)) { throw 'Invalid source path.' }
        New-Item -ItemType Directory -Path (Split-Path $SustainDest -Parent) -Force | Out-Null
        Invoke-WebRequest -Uri ('https://raw.githubusercontent.com/zhouzhq2021/recycle_cost_tool/' + $SustainCommit + '/' + [uri]::EscapeUriString($SustainPath)) -OutFile $SustainDest
    }
}
$SustainManifestPath = Join-Path $SustainSource 'SOURCE.json'
if (Test-Path -LiteralPath $SustainManifestPath) {
    $SustainExisting = Get-Content -LiteralPath $SustainManifestPath -Raw | ConvertFrom-Json
    if ($SustainExisting.commit -ne $SustainCommit -or -not $SustainExisting.hashes) { throw 'Backend source manifest is invalid.' }
    foreach ($SustainEntry in $SustainExisting.hashes.PSObject.Properties) {
        $SustainFile = [IO.Path]::GetFullPath((Join-Path $SustainSource $SustainEntry.Name))
        if (-not $SustainFile.StartsWith([IO.Path]::GetFullPath($SustainSource) + [IO.Path]::DirectorySeparatorChar) -or -not (Test-Path -LiteralPath $SustainFile)) { throw 'Backend source manifest path is invalid.' }
        if ((Get-FileHash -LiteralPath $SustainFile -Algorithm SHA256).Hash.ToLower() -ne $SustainEntry.Value) { throw 'Backend source has changed; restore the pinned source before reinstalling.' }
    }
} else {
$SustainManifest = [ordered]@{repo='zhouzhq2021/recycle_cost_tool';commit=$SustainCommit;python_license='MIT';workbook_note='EverBatt workbook and background data have separate source/use conditions; local research integration only';hashes=@{}}
Get-ChildItem -LiteralPath $SustainSource -File -Recurse | Where-Object { $_.Name -ne 'SOURCE.json' -and $_.FullName -notmatch '__pycache__' } | ForEach-Object {
    $SustainRelative = $_.FullName.Substring($SustainSource.Length + 1).Replace('\','/')
    $SustainManifest.hashes[$SustainRelative] = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLower()
}
$SustainManifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $SustainManifestPath -Encoding UTF8
}
& $SustainPython -c 'import bw2calc,bw2data,openpyxl,pandas; print("Environment and cost backends ready")'
if ($LASTEXITCODE -ne 0) { throw 'Backend import check failed.' }

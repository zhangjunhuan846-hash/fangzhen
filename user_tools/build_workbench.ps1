param([string]$ReleaseDirectory = 'outputs\fangzhen_workbench_ui_v0314')
$ErrorActionPreference = 'Stop'
$WorkbenchProject = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
    $WorkbenchRelease = Join-Path $WorkbenchProject $ReleaseDirectory
if (Test-Path -LiteralPath (Join-Path $WorkbenchRelease 'FangzhenResearch')) { throw 'Release exists. Choose a new release directory; never overwrite user data.' }
Push-Location $WorkbenchProject
try {
    $WorkbenchSchema = (Join-Path $PSScriptRoot 'rg_workstation_schema.json') + ';user_tools'
    $WorkbenchLiteSchema = (Join-Path $PSScriptRoot 'rg_lite_schema.json') + ';user_tools'
    $WorkbenchLegacySchema = (Join-Path $PSScriptRoot 'rg_lite_schema_v1.json') + ';user_tools'
    $WorkbenchV2Schema = (Join-Path $PSScriptRoot 'rg_lite_schema_v2.json') + ';user_tools'
    $WorkbenchWeb = (Join-Path $PSScriptRoot 'workbench\web') + ';user_tools/workbench/web'
    $WorkbenchExport = (Join-Path $PSScriptRoot 'workbench\export.mjs') + ';user_tools/workbench'
    & python -m PyInstaller --noconfirm --windowed --onedir --name FangzhenResearch --paths $WorkbenchProject --add-data $WorkbenchSchema --add-data $WorkbenchLiteSchema --add-data $WorkbenchLegacySchema --add-data $WorkbenchV2Schema --add-data $WorkbenchWeb --add-data $WorkbenchExport --distpath $WorkbenchRelease --workpath (Join-Path $WorkbenchRelease '_build\pyinstaller') --specpath (Join-Path $WorkbenchRelease '_build') (Join-Path $PSScriptRoot 'research_workbench.py')
    if ($LASTEXITCODE -ne 0) { throw 'Workbench build failed.' }
} finally { Pop-Location }

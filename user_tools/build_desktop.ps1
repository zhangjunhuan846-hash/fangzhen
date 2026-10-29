$ErrorActionPreference = 'Stop'
$DesktopProject = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Push-Location $DesktopProject
try {
    $DesktopOutput = Join-Path $DesktopProject 'outputs\fangzhen_desktop_lite'
    if (Test-Path -LiteralPath (Join-Path $DesktopOutput 'FangzhenWorkbench')) { throw 'Release directory exists. Use a new release directory; never rebuild over user data.' }
    $DesktopSchema = (Join-Path $PSScriptRoot 'rg_workstation_schema.json') + ';user_tools'
    $DesktopTemplate = (Join-Path $DesktopProject 'outputs\fangzhen_desktop\_build\templates\workstation.xlsx') + ';templates'
    $DesktopLiteSchema = (Join-Path $PSScriptRoot 'rg_lite_schema.json') + ';user_tools'
    if (-not (Test-Path -LiteralPath ($DesktopTemplate.Split(';')[0]))) { throw 'Build template missing.' }
    & python -m PyInstaller --noconfirm --clean --windowed --onedir --name FangzhenWorkbench --paths $DesktopProject --add-data $DesktopSchema --add-data $DesktopLiteSchema --add-data $DesktopTemplate --distpath $DesktopOutput --workpath (Join-Path $DesktopOutput '_build\pyinstaller') --specpath (Join-Path $DesktopOutput '_build') (Join-Path $PSScriptRoot 'desktop_workstation.py')
    if ($LASTEXITCODE -ne 0) { throw 'Desktop build failed.' }
} finally {
    Pop-Location
}

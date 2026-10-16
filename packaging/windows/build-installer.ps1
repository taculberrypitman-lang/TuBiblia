$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$BuildRoot = Join-Path $Root "build\windows"
$Venv = Join-Path $BuildRoot "venv"
$Python = Join-Path $Venv "Scripts\python.exe"
$DistRoot = Join-Path $BuildRoot "dist"
$PyInstallerDist = Join-Path $DistRoot "TuBiblia"
$WorkRoot = Join-Path $BuildRoot "work"
$IconPath = Join-Path $BuildRoot "tubiblia.ico"

Set-Location $Root
New-Item -ItemType Directory -Force -Path $BuildRoot, $DistRoot | Out-Null

if (-not (Test-Path $Python)) {
    & py -3.12 -m venv $Venv
    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo crear el entorno virtual de Python 3.12."
    }
}

& $Python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "No se pudo actualizar pip."
}

& $Python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
if ($LASTEXITCODE -ne 0) {
    throw "No se pudo instalar PyTorch CPU."
}

& $Python -m pip install -e "$($Root)[build]"
if ($LASTEXITCODE -ne 0) {
    throw "No se pudieron instalar TuBiblia y sus herramientas de compilación."
}

@'
from pathlib import Path
from PIL import Image

source = Image.open("tubiblia/assets/logo_tu_biblia.png").convert("RGBA")
source.thumbnail((240, 240), Image.Resampling.LANCZOS)
canvas = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
canvas.alpha_composite(
    source,
    ((canvas.width - source.width) // 2, (canvas.height - source.height) // 2),
)
canvas.save(Path("build/windows/tubiblia.ico"), format="ICO")
'@ | & $Python -
if ($LASTEXITCODE -ne 0) {
    throw "No se pudo preparar el icono del instalador."
}

if (Test-Path $PyInstallerDist) {
    Remove-Item -Recurse -Force $PyInstallerDist
}
if (Test-Path $WorkRoot) {
    Remove-Item -Recurse -Force $WorkRoot
}

$PyInstallerArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--windowed",
    "--onedir",
    "--name", "TuBiblia",
    "--distpath", $DistRoot,
    "--workpath", $WorkRoot,
    "--icon", $IconPath,
    "--add-data", "$Root\tubiblia\assets;tubiblia\assets",
    "--collect-all", "pocket_tts",
    "--copy-metadata", "pocket-tts",
    "--copy-metadata", "tubiblia",
    (Join-Path $Root "tubiblia\__main__.py")
)
& $Python @PyInstallerArgs
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller no pudo generar TuBiblia.exe."
}

$Iscc = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
if ($Iscc) {
    $IsccPath = $Iscc.Source
} else {
    $DefaultIscc = Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"
    if (-not (Test-Path $DefaultIscc)) {
        throw "Instala Inno Setup 6 y vuelve a ejecutar este script."
    }
    $IsccPath = $DefaultIscc
}

& $IsccPath (Join-Path $Root "packaging\windows\TuBiblia.iss")
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup no pudo generar el instalador."
}

Write-Host "Instalador creado: $(Join-Path $Root 'dist\TuBiblia-Setup-x64.exe')"

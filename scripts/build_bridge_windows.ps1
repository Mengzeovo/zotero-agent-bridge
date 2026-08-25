param(
  [string]$Version = '0.4.0-beta',
  [string]$VenvPath = '',
  [string]$OutputPath = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $VenvPath) {
  $VenvPath = Join-Path $projectRoot 'tmp\bridge-build-venv-py312'
}
if (-not $OutputPath) {
  $OutputPath = Join-Path $projectRoot "dist\bridge\windows-x64\$Version"
}
$venvPython = Join-Path $VenvPath 'Scripts\python.exe'
$buildId = [guid]::NewGuid().ToString('N')
$workRoot = Join-Path $projectRoot "tmp\bridge-builds\$buildId"
$pyiWork = Join-Path $workRoot 'pyinstaller-work'
$pyiDist = Join-Path $workRoot 'pyinstaller-dist'
$packageRoot = Join-Path $workRoot 'package'
$bundleDir = Join-Path $pyiDist 'zab-bridge'
$manifestPath = Join-Path $packageRoot 'bridge-manifest.json'
$specPath = Join-Path $projectRoot 'packaging\windows\zab-bridge.spec'
$manifestScript = Join-Path $projectRoot 'packaging\windows\generate_bundle_manifest.py'
$supplyChainScript = Join-Path $projectRoot 'packaging\windows\generate_supply_chain.py'

if (Test-Path -LiteralPath $OutputPath) {
  throw "Bridge output already exists and will not be overwritten: $OutputPath"
}

New-Item -ItemType Directory -Path $workRoot -Force | Out-Null
[System.IO.File]::WriteAllText(
  (Join-Path $workRoot '.zab-build-staging'),
  $buildId,
  [System.Text.UTF8Encoding]::new($false)
)

if (-not (Test-Path -LiteralPath $venvPython)) {
  py.exe -3.12 -m venv $VenvPath
  if ($LASTEXITCODE -ne 0) {
    throw 'Failed to create the Python 3.12 Bridge build environment'
  }
}

& $venvPython -m pip install --disable-pip-version-check -e $projectRoot 'pyinstaller==6.21.0'
if ($LASTEXITCODE -ne 0) {
  throw 'Failed to install Bridge/PyInstaller build dependencies'
}

& $venvPython -m PyInstaller `
  --noconfirm `
  --distpath $pyiDist `
  --workpath $pyiWork `
  $specPath
if ($LASTEXITCODE -ne 0) {
  throw 'PyInstaller Bridge build failed'
}
if (-not (Test-Path -LiteralPath (Join-Path $bundleDir 'zab-bridge.exe'))) {
  throw "PyInstaller did not produce the expected entrypoint: $bundleDir"
}

New-Item -ItemType Directory -Path $packageRoot -Force | Out-Null
Move-Item -LiteralPath $bundleDir -Destination (Join-Path $packageRoot 'zab-bridge')
& $venvPython $manifestScript `
  --bundle-dir (Join-Path $packageRoot 'zab-bridge') `
  --output $manifestPath `
  --bridge-version $Version `
  --project-root $projectRoot
if ($LASTEXITCODE -ne 0) {
  throw 'Bridge manifest generation failed'
}
& $venvPython $supplyChainScript `
  --bundle-manifest $manifestPath `
  --sbom (Join-Path $packageRoot 'SBOM.cdx.json') `
  --notices (Join-Path $packageRoot 'THIRD_PARTY_NOTICES.md')
if ($LASTEXITCODE -ne 0) {
  throw 'Bridge supply-chain metadata generation failed'
}

$outputParent = Split-Path -Parent $OutputPath
New-Item -ItemType Directory -Path $outputParent -Force | Out-Null
Move-Item -LiteralPath $packageRoot -Destination $OutputPath

Write-Output "Bridge bundle built: $OutputPath"
Write-Output "Manifest: $(Join-Path $OutputPath 'bridge-manifest.json')"

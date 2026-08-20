param(
  [string]$Version = '0.3.3',
  [switch]$BuildBridge
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$addonRoot = Join-Path $projectRoot 'zotero_companion_addon'
$bundleRoot = Join-Path $projectRoot "dist\bridge\windows-x64\$Version"
$distDir = Join-Path $projectRoot 'dist'
$versionedXpi = Join-Path $distDir "zotero-agent-bridge-addon-$Version.xpi"
$compatXpi = Join-Path $distDir 'zotero-agent-bridge-addon.xpi'
$builder = Join-Path $projectRoot 'packaging\build_xpi.py'

if ($BuildBridge -or -not (Test-Path -LiteralPath (Join-Path $bundleRoot 'bridge-manifest.json'))) {
  & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass `
    -File (Join-Path $PSScriptRoot 'build_bridge_windows.ps1') `
    -Version $Version
  if ($LASTEXITCODE -ne 0) {
    throw 'Windows Bridge bundle build failed'
  }
}

New-Item -ItemType Directory -Path $distDir -Force | Out-Null
& py.exe -3.12 $builder `
  --addon-root $addonRoot `
  --bundle-root $bundleRoot `
  --output $versionedXpi `
  --compat-output $compatXpi
if ($LASTEXITCODE -ne 0) {
  throw 'XPI build failed'
}

Write-Output "Versioned XPI: $versionedXpi"
Write-Output "Compatibility XPI: $compatXpi"

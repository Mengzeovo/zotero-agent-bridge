$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$addonRoot = Join-Path $projectRoot 'zotero_companion_addon'
$distDir = Join-Path $projectRoot 'dist'
$tempZip = Join-Path $distDir 'zotero-agent-bridge-addon.zip'
$outFile = Join-Path $distDir 'zotero-agent-bridge-addon.xpi'

if (-not (Test-Path $distDir)) {
  New-Item -ItemType Directory -Path $distDir | Out-Null
}

if (Test-Path $tempZip) {
  Remove-Item $tempZip -Force
}
if (Test-Path $outFile) {
  Remove-Item $outFile -Force
}

Compress-Archive -Path (Join-Path $addonRoot '*') -DestinationPath $tempZip -Force
Move-Item $tempZip $outFile -Force
Write-Output $outFile

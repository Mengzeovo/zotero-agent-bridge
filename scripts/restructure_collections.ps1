param(
  [string]$ConfigPath = (Join-Path $PSScriptRoot '..\config\bridge-config.json')
)

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$configResolved = (Resolve-Path $ConfigPath).Path

Push-Location $projectRoot
try {
  python .\scripts\restructure_collections.py --config $configResolved
}
finally {
  Pop-Location
}

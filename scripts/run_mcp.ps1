param(
  [string]$ConfigPath = (Join-Path $PSScriptRoot '..\config\bridge-config.json')
)

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$configResolved = (Resolve-Path $ConfigPath).Path
$entrypoint = (Resolve-Path (Join-Path $PSScriptRoot 'run_mcp.py')).Path

Push-Location $projectRoot
try {
  python $entrypoint --config $configResolved
}
finally {
  Pop-Location
}

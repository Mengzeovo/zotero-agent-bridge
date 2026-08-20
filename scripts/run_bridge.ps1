param(
  [string]$ConfigPath = (Join-Path $PSScriptRoot '..\config\bridge-config.json'),
  [switch]$InstallDeps
)

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$configResolved = (Resolve-Path $ConfigPath).Path

Push-Location $projectRoot
try {
  $env:ZOTERO_AGENT_BRIDGE_CONFIG = $configResolved
  if ($InstallDeps) {
    py -3.12 -m pip install -e .
  }
  py -3.12 -m zotero_agent_bridge
}
finally {
  Pop-Location
}

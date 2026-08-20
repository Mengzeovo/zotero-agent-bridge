param(
  [string]$ConfigPath = (Join-Path $PSScriptRoot '..\config\bridge-config.json'),
  [switch]$InstallDeps
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$configResolved = (Resolve-Path $ConfigPath).Path
$config = Get-Content $configResolved -Raw -Encoding UTF8 | ConvertFrom-Json
$bridgeHome = if ($config.bridge_home) { [string]$config.bridge_home } else { Join-Path $env:USERPROFILE 'Zotero\zotero-agent-bridge' }
$launchScript = (Resolve-Path (Join-Path $PSScriptRoot 'launch_bridge_detached.ps1')).Path
$powerShellExecutable = Join-Path $PSHOME 'powershell.exe'
$pythonLauncher = (Get-Command 'py.exe' -ErrorAction Stop).Source

if ($bridgeHome -match '<[^>]+>') {
  throw "bridge_home still contains a placeholder: $bridgeHome"
}
if (-not (Test-Path $powerShellExecutable)) {
  throw "Windows PowerShell executable was not found: $powerShellExecutable"
}

Push-Location $projectRoot
try {
  if ($InstallDeps) {
    & $pythonLauncher -3.12 -m pip install -e .
    if ($LASTEXITCODE -ne 0) {
      throw 'Failed to install Bridge Python dependencies'
    }
  }

  & $pythonLauncher -3.12 -c "import fastapi, uvicorn; import zotero_agent_bridge"
  if ($LASTEXITCODE -ne 0) {
    throw 'Python 3.12 Bridge dependencies are unavailable. Re-run with -InstallDeps.'
  }

  $previousConfig = $env:ZOTERO_AGENT_BRIDGE_CONFIG
  try {
    $env:ZOTERO_AGENT_BRIDGE_CONFIG = $configResolved
    & $pythonLauncher -3.12 -c "from zotero_agent_bridge.config import Settings; Settings.from_env()"
    if ($LASTEXITCODE -ne 0) {
      throw 'Bridge configuration validation failed'
    }
  }
  finally {
    $env:ZOTERO_AGENT_BRIDGE_CONFIG = $previousConfig
  }
}
finally {
  Pop-Location
}

$piExecutable = $null
if (($config.PSObject.Properties.Name -contains 'pi') -and $config.pi -and $config.pi.executable) {
  $piExecutable = [string]$config.pi.executable
  if ([System.IO.Path]::IsPathRooted($piExecutable)) {
    if (-not (Test-Path $piExecutable)) {
      throw "Pi executable was not found: $piExecutable"
    }
  }
  elseif (-not (Get-Command $piExecutable -ErrorAction SilentlyContinue)) {
    throw "Pi executable is not available on PATH: $piExecutable"
  }
}

New-Item -ItemType Directory -Path $bridgeHome -Force | Out-Null
$descriptorPath = Join-Path $bridgeHome 'bridge-launcher.json'
$descriptor = [ordered]@{
  schema_version = 1
  platform = 'windows'
  command = $powerShellExecutable
  arguments = @(
    '-NoProfile',
    '-NonInteractive',
    '-ExecutionPolicy', 'Bypass',
    '-File', $launchScript,
    '-ConfigPath', $configResolved,
    '-ReadyTimeoutSeconds', '15'
  )
  workdir = $projectRoot
  owner_arguments = [ordered]@{
    id = '-OwnerId'
    token = '-OwnerToken'
  }
}
$json = $descriptor | ConvertTo-Json -Depth 6
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText($descriptorPath, $json, $utf8NoBom)

Write-Output "Bridge launcher registered: $descriptorPath"
Write-Output "Config: $configResolved"
Write-Output "Python: $pythonLauncher -3.12"
Write-Output "Pi: $piExecutable"

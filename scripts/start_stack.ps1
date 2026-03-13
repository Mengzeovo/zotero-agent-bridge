param(
  [string]$ConfigPath = (Join-Path $PSScriptRoot '..\config\bridge-config.json'),
  [switch]$InstallDeps,
  [switch]$BridgeOnly,
  [int]$BridgeReadyTimeoutSeconds = 20
)

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$configResolved = (Resolve-Path $ConfigPath).Path
$config = Get-Content $configResolved -Raw -Encoding UTF8 | ConvertFrom-Json
$bridgeScript = Join-Path $PSScriptRoot 'run_bridge.ps1'
$mcpScript = Join-Path $PSScriptRoot 'run_mcp.ps1'
$baseUrl = "http://$($config.host):$($config.port)"
$token = $null
$bridgeReady = $false

function New-PowerShellArgumentList {
  param(
    [string]$ScriptPath,
    [string]$ConfigPathValue,
    [switch]$PassInstallDeps
  )

  $args = @(
    '-NoExit',
    '-ExecutionPolicy', 'Bypass',
    '-File', $ScriptPath,
    '-ConfigPath', $ConfigPathValue
  )
  if ($PassInstallDeps) {
    $args += '-InstallDeps'
  }
  return $args
}

function Get-BridgeToken {
  param([object]$Cfg)

  if ($Cfg.api_token) {
    return [string]$Cfg.api_token
  }

  $tokenFile = Join-Path $Cfg.bridge_home 'bridge.generated.json'
  if (-not (Test-Path $tokenFile)) {
    return $null
  }
  return (Get-Content $tokenFile -Raw -Encoding UTF8 | ConvertFrom-Json).api_token
}

Write-Host 'Starting Zotero Agent Bridge...'
Start-Process powershell.exe -WorkingDirectory $projectRoot -ArgumentList (New-PowerShellArgumentList -ScriptPath $bridgeScript -ConfigPathValue $configResolved -PassInstallDeps:$InstallDeps)

$deadline = (Get-Date).AddSeconds($BridgeReadyTimeoutSeconds)
while ((Get-Date) -lt $deadline) {
  $token = Get-BridgeToken -Cfg $config
  if ($token) {
    try {
      $null = Invoke-RestMethod -Headers @{ 'X-Bridge-Token' = $token } -Uri "$baseUrl/health" -TimeoutSec 2
      $bridgeReady = $true
      break
    }
    catch {
    }
  }
  Start-Sleep -Milliseconds 500
}

if (-not $bridgeReady) {
  if (-not $token) {
    Write-Warning 'Bridge token was not generated in time. The bridge window may still be starting.'
  }
  else {
    Write-Warning 'Bridge window was started, but the HTTP health check did not pass in time. MCP was not started.'
  }

  if ($BridgeOnly) {
    Write-Host 'BridgeOnly specified. MCP server was not started.'
    exit 0
  }

  exit 1
}

Write-Host "Bridge is responding at $baseUrl"

if ($BridgeOnly) {
  Write-Host 'BridgeOnly specified. MCP server was not started.'
  exit 0
}

Write-Host 'Starting Zotero MCP bridge...'
Start-Process powershell.exe -WorkingDirectory $projectRoot -ArgumentList (New-PowerShellArgumentList -ScriptPath $mcpScript -ConfigPathValue $configResolved)

Write-Host ''
Write-Host 'Started:'
Write-Host "  Bridge: $baseUrl"
Write-Host '  MCP: separate PowerShell window'
Write-Host ''
Write-Host 'You can now connect your agent client to the MCP server.'

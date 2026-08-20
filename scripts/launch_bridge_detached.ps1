param(
  [Parameter(Mandatory = $true)]
  [string]$ConfigPath,
  [Parameter(Mandatory = $true)]
  [string]$OwnerId,
  [Parameter(Mandatory = $true)]
  [string]$OwnerToken,
  [int]$ReadyTimeoutSeconds = 20
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$configResolved = (Resolve-Path $ConfigPath).Path
$config = Get-Content $configResolved -Raw -Encoding UTF8 | ConvertFrom-Json
$bridgeHost = if ($config.host) { [string]$config.host } else { '127.0.0.1' }
$bridgePort = if ($config.port) { [int]$config.port } else { 8765 }
$bridgeHome = if ($config.bridge_home) { [string]$config.bridge_home } else { Join-Path $env:USERPROFILE 'Zotero\zotero-agent-bridge' }
$baseUrl = "http://${bridgeHost}:${bridgePort}"
$tokenFile = Join-Path $bridgeHome 'bridge.generated.json'
$mutexName = "Local\ZoteroAgentBridge-$bridgePort"
$mutex = [System.Threading.Mutex]::new($false, $mutexName)
$acquired = $false
$script:lastHealthError = $null

function Get-BridgeToken {
  if (($config.PSObject.Properties.Name -contains 'api_token') -and $config.api_token) {
    return [string]$config.api_token
  }
  if (-not (Test-Path $tokenFile)) {
    return $null
  }
  try {
    return [string]((Get-Content $tokenFile -Raw -Encoding UTF8 | ConvertFrom-Json).api_token)
  }
  catch {
    return $null
  }
}

function Get-BridgeHealth {
  $token = Get-BridgeToken
  if (-not $token) {
    return $null
  }
  try {
    return Invoke-RestMethod -Method Get -Uri "$baseUrl/lifecycle" -Headers @{ 'X-Bridge-Token' = $token } -TimeoutSec 2
  }
  catch {
    $script:lastHealthError = $_.Exception.Message
    return $null
  }
}

try {
  $acquired = $mutex.WaitOne([TimeSpan]::FromSeconds(30))
  if (-not $acquired) {
    throw "Timed out waiting for Bridge startup lock: $mutexName"
  }

  $existing = Get-BridgeHealth
  if ($existing) {
    Write-Output "Bridge is already responding at $baseUrl"
    exit 0
  }

  New-Item -ItemType Directory -Path $bridgeHome -Force | Out-Null
  $logDir = Join-Path $bridgeHome 'logs'
  New-Item -ItemType Directory -Path $logDir -Force | Out-Null
  $stderrLog = Join-Path $logDir 'bridge-stderr.log'
  $pythonLauncher = (Get-Command 'py.exe' -ErrorAction Stop).Source
  $pythonExecutable = (& $pythonLauncher -3.12 -c "import sys; print(sys.executable)").Trim()
  if (-not $pythonExecutable -or -not (Test-Path $pythonExecutable)) {
    throw 'Could not resolve the Python 3.12 executable'
  }
  $processWrapper = (Resolve-Path (Join-Path $PSScriptRoot 'bridge_process_wrapper.py')).Path
  $spawnBridge = (Resolve-Path (Join-Path $PSScriptRoot 'spawn_bridge_detached.py')).Path
  $previousConfig = $env:ZOTERO_AGENT_BRIDGE_CONFIG
  $previousOwnerId = $env:ZOTERO_AGENT_BRIDGE_OWNER_ID
  $previousOwnerToken = $env:ZOTERO_AGENT_BRIDGE_OWNER_TOKEN
  $previousLogHome = $env:ZOTERO_AGENT_BRIDGE_HOME_FOR_LOGS
  try {
    $env:ZOTERO_AGENT_BRIDGE_CONFIG = $configResolved
    $env:ZOTERO_AGENT_BRIDGE_OWNER_ID = $OwnerId
    $env:ZOTERO_AGENT_BRIDGE_OWNER_TOKEN = $OwnerToken
    $env:ZOTERO_AGENT_BRIDGE_HOME_FOR_LOGS = $bridgeHome
    $spawnOutput = (& $pythonExecutable $spawnBridge `
      --python $pythonExecutable `
      --wrapper $processWrapper `
      --workdir $projectRoot) -join "`n"
    if ($LASTEXITCODE -ne 0) {
      throw "Detached Bridge spawn failed: $spawnOutput"
    }
    $bridgePid = 0
    if (-not [int]::TryParse($spawnOutput.Trim(), [ref]$bridgePid)) {
      throw "Detached Bridge spawner returned an invalid PID: $spawnOutput"
    }
  }
  finally {
    $env:ZOTERO_AGENT_BRIDGE_CONFIG = $previousConfig
    $env:ZOTERO_AGENT_BRIDGE_OWNER_ID = $previousOwnerId
    $env:ZOTERO_AGENT_BRIDGE_OWNER_TOKEN = $previousOwnerToken
    $env:ZOTERO_AGENT_BRIDGE_HOME_FOR_LOGS = $previousLogHome
  }

  $deadline = (Get-Date).AddSeconds($ReadyTimeoutSeconds)
  do {
    Start-Sleep -Milliseconds 250
    $health = Get-BridgeHealth
    if ($health) {
      $reportedOwner = [string]$health.owner_id
      Write-Output "Bridge is responding at $baseUrl (owner=$reportedOwner)"
      exit 0
    }
  } while ((Get-Date) -lt $deadline)

  $stderrTail = if (Test-Path $stderrLog) { (Get-Content $stderrLog -Tail 20 -ErrorAction SilentlyContinue) -join "`n" } else { '' }
  throw "Bridge process was launched but did not become healthy within $ReadyTimeoutSeconds seconds (Bridge PID $bridgePid). health error: $script:lastHealthError. stderr: $stderrTail"
}
finally {
  if ($acquired) {
    $mutex.ReleaseMutex()
  }
  $mutex.Dispose()
}

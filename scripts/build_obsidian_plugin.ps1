param(
  [string]$OutDir = (Join-Path $PSScriptRoot '..\dist\obsidian-zotero-agent-bridge'),
  [string]$VaultPluginsDir = ""
)

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pluginRoot = Join-Path $projectRoot 'obsidian_bridge_plugin'
$outResolved = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutDir)

if (Test-Path $outResolved) {
  Remove-Item -LiteralPath $outResolved -Recurse -Force
}
New-Item -ItemType Directory -Path $outResolved | Out-Null

foreach ($fileName in @('manifest.json', 'main.js', 'styles.css', 'README.md')) {
  Copy-Item -LiteralPath (Join-Path $pluginRoot $fileName) -Destination (Join-Path $outResolved $fileName)
}

if ($VaultPluginsDir) {
  $targetDir = Join-Path $VaultPluginsDir 'zotero-agent-bridge'
  if (Test-Path $targetDir) {
    Remove-Item -LiteralPath $targetDir -Recurse -Force
  }
  New-Item -ItemType Directory -Path $targetDir | Out-Null
  Copy-Item -Path (Join-Path $outResolved '*') -Destination $targetDir -Recurse
  Write-Output $targetDir
} else {
  Write-Output $outResolved
}

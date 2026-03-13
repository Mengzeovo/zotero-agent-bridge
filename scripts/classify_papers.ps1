param(
  [string]$ConfigPath = (Join-Path $PSScriptRoot '..\config\bridge-config.json'),
  [switch]$Apply,
  [int]$Start = 0,
  [int]$Limit = 500,
  [string]$CollectionKey,
  [string]$BackupDir,
  [switch]$SkipBackup,
  [switch]$StdoutSummary
)

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$configResolved = (Resolve-Path $ConfigPath).Path

$args = @(
  '.\scripts\classify_papers.py',
  '--config', $configResolved,
  '--start', $Start,
  '--limit', $Limit
)
if ($Apply) {
  $args += '--apply'
}
if ($CollectionKey) {
  $args += '--collection-key'
  $args += $CollectionKey
}
if ($BackupDir) {
  $args += '--backup-dir'
  $args += $BackupDir
}
if ($SkipBackup) {
  $args += '--skip-backup'
}
if ($StdoutSummary) {
  $args += '--stdout-summary'
}

Push-Location $projectRoot
try {
  python @args
}
finally {
  Pop-Location
}

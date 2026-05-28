param(
  [string]$TaskName = "Job Application Pipeline Daily",
  [string]$Time = "09:00"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$runScript = Join-Path $PSScriptRoot "run_daily_report.ps1"

if (-not (Test-Path -LiteralPath $runScript)) {
  throw "Daily run script not found: $runScript"
}

$action = New-ScheduledTaskAction `
  -Execute "powershell.exe" `
  -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runScript`"" `
  -WorkingDirectory $repoRoot

$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet `
  -StartWhenAvailable `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries

Register-ScheduledTask `
  -TaskName $TaskName `
  -Action $action `
  -Trigger $trigger `
  -Settings $settings `
  -Description "Runs the local job application pipeline daily, sends the Telegram report, and cleans old PDFs." `
  -Force | Out-Null

Write-Output "Installed scheduled task '$TaskName' for $Time daily."

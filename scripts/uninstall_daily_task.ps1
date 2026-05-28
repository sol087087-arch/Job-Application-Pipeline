param(
  [string]$TaskName = "Job Application Pipeline Daily"
)

$ErrorActionPreference = "Stop"

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Output "Removed scheduled task '$TaskName'."

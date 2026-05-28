param(
  [string]$Root = "",
  [string]$Date = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $repoRoot "src"

$python = $env:JOB_PIPELINE_PYTHON
if ([string]::IsNullOrWhiteSpace($python)) {
  $candidate = Join-Path $repoRoot ".venv\Scripts\python.exe"
  if (Test-Path -LiteralPath $candidate) {
    $python = $candidate
  }
}

if ([string]::IsNullOrWhiteSpace($python)) {
  $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
  if ($null -eq $pythonCommand) {
    $pythonCommand = Get-Command py -ErrorAction SilentlyContinue
  }
  if ($null -eq $pythonCommand) {
    throw "Python not found. Set JOB_PIPELINE_PYTHON to the Python executable that should run this project."
  }
  $python = $pythonCommand.Source
}

$args = @("-m", "job_pipeline.smoke")
if ($Root -ne "") {
  $args += @("--root", $Root)
}
if ($Date -ne "") {
  $args += @("--date", $Date)
}

Set-Location $repoRoot
& $python @args
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}

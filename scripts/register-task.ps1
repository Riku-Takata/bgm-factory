[CmdletBinding()]
param([string]$TaskName = "HomeServer-BgmFactory")

. (Join-Path $PSScriptRoot "Common.ps1")

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from an Administrator PowerShell window."
}

$startScript = Join-Path $PSScriptRoot "start.ps1"
$taskCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$startScript`""
& schtasks.exe /Create /TN $TaskName /SC ONSTART /DELAY 0001:00 /RU SYSTEM /RL HIGHEST /TR $taskCommand /F
if ($LASTEXITCODE -ne 0) {
    throw "Task Scheduler registration failed."
}
Write-Host "Registered startup task: $TaskName"


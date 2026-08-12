[CmdletBinding()]
param([string]$TaskName = "HomeServer-BgmFactory")

& schtasks.exe /Delete /TN $TaskName /F
if ($LASTEXITCODE -ne 0) {
    throw "Task Scheduler removal failed."
}
Write-Host "Removed startup task: $TaskName"


[CmdletBinding()]
param(
    [switch]$WorkerOnly,
    [switch]$SkipHealthCheck
)

. (Join-Path $PSScriptRoot "Common.ps1")
Initialize-BgmFactoryDirectories
Set-BgmFactoryEnvironment
Assert-UvInstalled
Assert-AppEnvironmentInstalled

$workerPid = Join-Path $script:LogRoot "worker.pid"
$dashboardPid = Join-Path $script:LogRoot "dashboard.pid"
$acePid = Join-Path $script:LogRoot "ace-step.pid"

if (-not $WorkerOnly) {
    if (-not (Test-Path -LiteralPath $script:AceStepApi)) {
        throw "ACE-Step is not installed. Run scripts\install.ps1 first."
    }
    if (-not (Test-ProcessFromPidFile -PidFile $acePid)) {
        $aceOut = Join-Path $script:LogRoot "ace-step.stdout.log"
        $aceErr = Join-Path $script:LogRoot "ace-step.stderr.log"
        $hostName = if ($env:ACESTEP_API_HOST) { $env:ACESTEP_API_HOST } else { "127.0.0.1" }
        $port = if ($env:ACESTEP_API_PORT) { $env:ACESTEP_API_PORT } else { "8001" }
        $process = Start-Process -FilePath $script:AceStepApi `
            -ArgumentList @("--host", $hostName, "--port", $port) `
            -WorkingDirectory $script:AceStepRoot `
            -RedirectStandardOutput $aceOut `
            -RedirectStandardError $aceErr `
            -WindowStyle Hidden `
            -PassThru
        Set-Content -LiteralPath $acePid -Value $process.Id -NoNewline
        Write-Host "ACE-Step API started (PID $($process.Id))."
    }
    else {
        Write-Host "ACE-Step API is already running."
    }
}

if (-not (Test-ProcessFromPidFile -PidFile $workerPid)) {
    $workerOut = Join-Path $script:LogRoot "worker.stdout.log"
    $workerErr = Join-Path $script:LogRoot "worker.stderr.log"
    $process = Start-Process -FilePath $script:AppWorker `
        -WorkingDirectory $script:AppRoot `
        -RedirectStandardOutput $workerOut `
        -RedirectStandardError $workerErr `
        -WindowStyle Hidden `
        -PassThru
    Set-Content -LiteralPath $workerPid -Value $process.Id -NoNewline
    Write-Host "BGM Factory worker started (PID $($process.Id))."
}
else {
    Write-Host "BGM Factory worker is already running."
}

if (-not (Test-ProcessFromPidFile -PidFile $dashboardPid)) {
    $dashboardOut = Join-Path $script:LogRoot "dashboard.stdout.log"
    $dashboardErr = Join-Path $script:LogRoot "dashboard.stderr.log"
    $process = Start-Process -FilePath $script:AppDashboard `
        -WorkingDirectory $script:AppRoot `
        -RedirectStandardOutput $dashboardOut `
        -RedirectStandardError $dashboardErr `
        -WindowStyle Hidden `
        -PassThru
    Set-Content -LiteralPath $dashboardPid -Value $process.Id -NoNewline
    Write-Host "BGM Factory dashboard started (PID $($process.Id))."
}
else {
    Write-Host "BGM Factory dashboard is already running."
}

if (-not $SkipHealthCheck) {
    Start-Sleep -Seconds 3
    & (Join-Path $PSScriptRoot "healthcheck.ps1")
}

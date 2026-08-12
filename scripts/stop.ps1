. (Join-Path $PSScriptRoot "Common.ps1")
Initialize-BgmFactoryDirectories

Stop-ProcessFromPidFile -PidFile (Join-Path $script:LogRoot "worker.pid")
Stop-ProcessFromPidFile -PidFile (Join-Path $script:LogRoot "ace-step.pid")
Write-Host "BGM Factory processes stopped."


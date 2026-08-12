Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:AppRoot = Split-Path -Parent $PSScriptRoot
$script:ServerRoot = Split-Path -Parent (Split-Path -Parent $script:AppRoot)
$script:DataRoot = Join-Path $script:ServerRoot "data\app-data\bgm-factory"
$script:ConfigRoot = Join-Path $script:ServerRoot "config\bgm-factory"
$script:LogRoot = Join-Path $script:ServerRoot "logs\bgm-factory"
$script:ToolsRoot = Join-Path $script:ServerRoot "tools"
$script:AceStepRoot = Join-Path $script:DataRoot "engines\ACE-Step-1.5"
$script:UvPath = Join-Path $script:ToolsRoot "uv\uv.exe"
$script:FfmpegBin = Join-Path $script:ToolsRoot "ffmpeg\bin"
$script:AppPython = Join-Path $script:AppRoot ".venv\Scripts\python.exe"
$script:AppHealth = Join-Path $script:AppRoot ".venv\Scripts\bgm-factory-health.exe"
$script:AppWorker = Join-Path $script:AppRoot ".venv\Scripts\bgm-factory-worker.exe"
$script:AceStepApi = Join-Path $script:AceStepRoot ".venv\Scripts\acestep-api.exe"

function Initialize-BgmFactoryDirectories {
    $directories = @(
        (Join-Path $script:DataRoot "db"),
        (Join-Path $script:DataRoot "generated\rejected"),
        (Join-Path $script:DataRoot "assets"),
        (Join-Path $script:DataRoot "shorts"),
        (Join-Path $script:DataRoot "longmix"),
        (Join-Path $script:DataRoot "temp"),
        (Join-Path $script:DataRoot "cache\uv"),
        (Join-Path $script:DataRoot "cache\huggingface"),
        (Join-Path $script:DataRoot "engines"),
        (Join-Path $script:ConfigRoot "secrets"),
        $script:LogRoot,
        (Join-Path $script:ToolsRoot "uv"),
        (Join-Path $script:ToolsRoot "python")
    )
    foreach ($directory in $directories) {
        if (-not (Test-Path -LiteralPath $directory)) {
            New-Item -ItemType Directory -Path $directory -Force | Out-Null
        }
    }
}

function Import-DotEnv {
    $envFile = Join-Path $script:ConfigRoot ".env"
    if (-not (Test-Path -LiteralPath $envFile)) {
        return
    }
    foreach ($line in Get-Content -LiteralPath $envFile -Encoding utf8) {
        if ($line -match '^\s*#' -or $line -notmatch '=') {
            continue
        }
        $name, $value = $line -split '=', 2
        $name = $name.Trim()
        if ($name) {
            [Environment]::SetEnvironmentVariable($name, $value.Trim(), "Process")
        }
    }
}

function Set-BgmFactoryEnvironment {
    $env:BGM_FACTORY_HOME = $script:ServerRoot
    $env:BGM_FACTORY_DATA_DIR = $script:DataRoot
    $env:BGM_FACTORY_CONFIG_DIR = $script:ConfigRoot
    $env:BGM_FACTORY_LOG_DIR = $script:LogRoot
    $env:ACESTEP_HOME = $script:AceStepRoot
    $env:UV_CACHE_DIR = Join-Path $script:DataRoot "cache\uv"
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $script:ToolsRoot "python"
    $env:HF_HOME = Join-Path $script:DataRoot "cache\huggingface"
    $env:HUGGINGFACE_HUB_CACHE = Join-Path $env:HF_HOME "hub"
    $env:PATH = "$script:FfmpegBin;$env:PATH"
    Import-DotEnv
}

function Assert-UvInstalled {
    if (-not (Test-Path -LiteralPath $script:UvPath)) {
        throw "uv is not installed. Run scripts\install.ps1 first."
    }
}

function Assert-AppEnvironmentInstalled {
    if (-not (Test-Path -LiteralPath $script:AppPython)) {
        throw "The BGM Factory Python environment is not installed. Run scripts\install.ps1 first."
    }
}

function Test-ProcessFromPidFile {
    param([Parameter(Mandatory = $true)][string]$PidFile)

    if (-not (Test-Path -LiteralPath $PidFile)) {
        return $false
    }
    $processId = (Get-Content -LiteralPath $PidFile -Raw).Trim()
    if ($processId -notmatch '^\d+$') {
        return $false
    }
    return $null -ne (Get-Process -Id ([int]$processId) -ErrorAction SilentlyContinue)
}

function Stop-ProcessFromPidFile {
    param([Parameter(Mandatory = $true)][string]$PidFile)

    if (-not (Test-Path -LiteralPath $PidFile)) {
        return
    }
    $processId = (Get-Content -LiteralPath $PidFile -Raw).Trim()
    if ($processId -match '^\d+$') {
        $process = Get-Process -Id ([int]$processId) -ErrorAction SilentlyContinue
        if ($process) {
            Stop-Process -Id $process.Id -ErrorAction SilentlyContinue
            $null = $process.WaitForExit(15000)
            if (-not $process.HasExited) {
                Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            }
        }
    }
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
}

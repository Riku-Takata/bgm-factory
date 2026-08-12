[CmdletBinding()]
param(
    [switch]$SkipAceStep,
    [switch]$SkipFfmpeg,
    [switch]$SkipAppDependencies
)

. (Join-Path $PSScriptRoot "Common.ps1")
Initialize-BgmFactoryDirectories
Set-BgmFactoryEnvironment

function Install-Uv {
    if (Test-Path -LiteralPath $script:UvPath) {
        return
    }
    $version = "0.11.32"
    $archive = Join-Path $script:DataRoot "temp\uv.zip"
    $checksumFile = "$archive.sha256"
    $baseUrl = "https://github.com/astral-sh/uv/releases/download/$version/uv-x86_64-pc-windows-msvc.zip"
    Write-Host "Downloading uv $version..."
    Invoke-WebRequest -Uri $baseUrl -OutFile $archive
    Invoke-WebRequest -Uri "$baseUrl.sha256" -OutFile $checksumFile
    $expected = ((Get-Content -LiteralPath $checksumFile -Raw) -split '\s+')[0].ToLowerInvariant()
    $actual = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $expected) {
        throw "uv archive checksum mismatch."
    }
    Expand-Archive -LiteralPath $archive -DestinationPath (Split-Path -Parent $script:UvPath) -Force
    Remove-Item -LiteralPath $archive, $checksumFile -Force
}

function Install-Ffmpeg {
    $ffmpeg = Join-Path $script:FfmpegBin "ffmpeg.exe"
    if (Test-Path -LiteralPath $ffmpeg) {
        return
    }
    $archive = Join-Path $script:DataRoot "temp\ffmpeg.zip"
    $extractRoot = Join-Path $script:DataRoot "temp\ffmpeg-extract"
    $url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    Write-Host "Downloading FFmpeg essentials build..."
    Invoke-WebRequest -Uri $url -OutFile $archive
    if (Test-Path -LiteralPath $extractRoot) {
        Remove-Item -LiteralPath $extractRoot -Recurse -Force
    }
    Expand-Archive -LiteralPath $archive -DestinationPath $extractRoot -Force
    $source = Get-ChildItem -LiteralPath $extractRoot -Directory | Select-Object -First 1
    if (-not $source -or -not (Test-Path -LiteralPath (Join-Path $source.FullName "bin\ffmpeg.exe"))) {
        throw "FFmpeg archive layout was not recognized."
    }
    $destination = Join-Path $script:ToolsRoot "ffmpeg"
    if (Test-Path -LiteralPath $destination) {
        Remove-Item -LiteralPath $destination -Recurse -Force
    }
    Move-Item -LiteralPath $source.FullName -Destination $destination
    Remove-Item -LiteralPath $archive -Force
    Remove-Item -LiteralPath $extractRoot -Recurse -Force
}

function Initialize-Configuration {
    $envFile = Join-Path $script:ConfigRoot ".env"
    if (-not (Test-Path -LiteralPath $envFile)) {
        Copy-Item -LiteralPath (Join-Path $script:AppRoot ".env.example") -Destination $envFile
        $bytes = New-Object byte[] 32
        $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        try { $generator.GetBytes($bytes) } finally { $generator.Dispose() }
        $apiKey = ([BitConverter]::ToString($bytes)).Replace("-", "").ToLowerInvariant()
        $contents = Get-Content -LiteralPath $envFile -Raw -Encoding utf8
        $contents = $contents.Replace("ACESTEP_API_KEY=CHANGE_ME", "ACESTEP_API_KEY=$apiKey")
        [System.IO.File]::WriteAllText($envFile, $contents, (New-Object System.Text.UTF8Encoding($false)))
        Write-Host "Created $envFile"
    }
    foreach ($name in @("app.yaml", "themes.yaml", "naming_words.yaml")) {
        $source = Join-Path $script:AppRoot "config\$name"
        $destination = Join-Path $script:ConfigRoot $name
        if (-not (Test-Path -LiteralPath $destination)) {
            Copy-Item -LiteralPath $source -Destination $destination
        }
    }
}

function Install-AppEnvironment {
    Assert-UvInstalled
    & $script:UvPath python install 3.12
    if ($LASTEXITCODE -ne 0) { throw "Python installation failed." }
    if (-not $SkipAppDependencies) {
        & $script:UvPath sync --project $script:AppRoot --extra audio --extra youtube --extra dev
        if ($LASTEXITCODE -ne 0) { throw "BGM Factory dependency installation failed." }
    }
}

function Install-AceStep {
    if (-not (Test-Path -LiteralPath (Join-Path $script:AceStepRoot ".git"))) {
        Write-Host "Cloning ACE-Step 1.5..."
        & git clone --depth 1 https://github.com/ace-step/ACE-Step-1.5.git $script:AceStepRoot
        if ($LASTEXITCODE -ne 0) { throw "ACE-Step clone failed." }
    }
    & $script:UvPath sync --project $script:AceStepRoot
    if ($LASTEXITCODE -ne 0) { throw "ACE-Step dependency installation failed." }
}

Install-Uv
Set-BgmFactoryEnvironment
if (-not $SkipFfmpeg) { Install-Ffmpeg }
Initialize-Configuration
Set-BgmFactoryEnvironment
Install-AppEnvironment
if (-not $SkipAceStep) { Install-AceStep }

Write-Host ""
Write-Host "BGM Factory environment installation completed."
Write-Host "Next: edit $script:ConfigRoot\.env, then run scripts\start.ps1"

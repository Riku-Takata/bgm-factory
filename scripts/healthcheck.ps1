[CmdletBinding()]
param([switch]$Json)

. (Join-Path $PSScriptRoot "Common.ps1")
Initialize-BgmFactoryDirectories
Set-BgmFactoryEnvironment
Assert-AppEnvironmentInstalled

$arguments = @()
if ($Json) { $arguments += "--json" }
& $script:AppHealth @arguments
exit $LASTEXITCODE

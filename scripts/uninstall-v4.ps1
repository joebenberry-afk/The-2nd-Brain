<#
.SYNOPSIS
  Remove the Second Brain V4 OMP extension; with -Restore, bring back the most recently parked
  older extension (second-brain or second-brain-v3). -RemovePath takes brain\bin (and the checkout,
  where earlier versions put brain.cmd) off the user PATH, keeping every other entry as stored, and
  deletes the generated brain\bin\brain.cmd and brain.ps1.
  Notes and working state are untouched. Works with Windows PowerShell 5.1 and 7.
#>
[CmdletBinding()]
param(
    [string]$ExtensionsDir,
    [string]$SourceRoot,
    [switch]$Restore,
    [switch]$RemovePath
)
$ErrorActionPreference = "Stop"

if (-not $SourceRoot) { $SourceRoot = Split-Path $PSScriptRoot -Parent }
$SourceRoot = [System.IO.Path]::GetFullPath($SourceRoot)
if (-not $ExtensionsDir) { $ExtensionsDir = Join-Path (Join-Path $HOME ".omp") "agent/extensions" }
$ExtensionsDir = [System.IO.Path]::GetFullPath($ExtensionsDir)

$Target = Join-Path $ExtensionsDir "second-brain-v4"
if (Test-Path $Target) { Remove-Item -Recurse -Force $Target; Write-Host "Removed $Target" }

if ($Restore) {
    # Everything the last install parked shares its timestamp: restore all of it.
    $Disabled = Join-Path (Split-Path $ExtensionsDir -Parent) "extensions-disabled"
    $parked = @(Get-ChildItem $Disabled -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^second-brain(-v3)?-\d{8}-\d{6}$' })
    if ($parked.Count -gt 0) {
        $stamp = ($parked | ForEach-Object { $_.Name.Substring($_.Name.Length - 15) } | Sort-Object | Select-Object -Last 1)
        foreach ($dir in ($parked | Where-Object { $_.Name.EndsWith($stamp) })) {
            $name = $dir.Name.Substring(0, $dir.Name.Length - 16)
            $dest = Join-Path $ExtensionsDir $name
            if (Test-Path $dest) { throw "$dest already exists; not overwriting it." }
            Move-Item $dir.FullName $dest
            Write-Host "Restored $name"
        }
    } else {
        Write-Warning "No parked extension found in $Disabled"
    }
}

if ($RemovePath) {
    # Edited as stored (REG_EXPAND_SZ), so entries like %USERPROFILE%\... keep expanding.
    $BinDir = Join-Path (Join-Path $SourceRoot "brain") "bin"
    $raw = (Get-Item "HKCU:\Environment").GetValue("Path", "", [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
    $parts = @(($raw -split ";") | Where-Object { $_ -and $_.TrimEnd("\") -ne $SourceRoot -and $_.TrimEnd("\") -ne $BinDir })
    Set-ItemProperty -Path "HKCU:\Environment" -Name Path -Value ($parts -join ";") -Type ExpandString
    [Environment]::SetEnvironmentVariable("SECOND_BRAIN_PATH_CHANGED", "1", "User")
    [Environment]::SetEnvironmentVariable("SECOND_BRAIN_PATH_CHANGED", $null, "User")
    # The shims the installer generated; the committed sh shim stays.
    Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $BinDir "brain.cmd"), (Join-Path $BinDir "brain.ps1")
    Write-Host "Removed $BinDir from the user PATH, and its brain.cmd and brain.ps1"
}
Write-Host "Restart OMP."

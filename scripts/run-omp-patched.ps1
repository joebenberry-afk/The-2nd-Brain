<#
.SYNOPSIS
    Start the qualified patched OMP host for The Second Brain.

.DESCRIPTION
    The package's own `omp` command maps to dist/cli.js, a bundle that does not carry the
    worker-cleanup patch, so typing `omp` is not the qualified route. This launcher starts the
    qualified source entrypoint (`bun <package>/src/cli.ts`) after verifying that every installed
    host and extension file matches docs/integrations/omp-host-patch-2026-09-19/DEPLOYMENT-MANIFEST.json.

    It is a launcher, not a repair tool: a mismatch is a refusal with the failing paths listed, and
    nothing is installed, overwritten or reconfigured. Set OMP_RETAIL_ROOT to verify and launch a
    different copy of the package (for example a rehearsal copy); the manifest hashes still apply.

.PARAMETER SkipIdentityCheck
    Start without verifying the installed bytes. Use only to diagnose why a verified launch is
    refused; the unpatched-bundle risk the check exists for is not covered then.

.PARAMETER ManifestPath
    Verify and launch from a different deployment manifest (or set OMP_DEPLOYMENT_MANIFEST), so a
    successor candidate can be qualified in a staged layout without touching the sealed record or
    the production installation. The manifest's host and extension roots decide what is verified.

.EXAMPLE
    powershell -NoProfile -File scripts/run-omp-patched.ps1 --version

.EXAMPLE
    powershell -NoProfile -File scripts/run-omp-patched.ps1 -p "summarise the open work"
#>
[CmdletBinding()]
param(
    [switch] $SkipIdentityCheck,
    [string] $ManifestPath,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $Rest
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not $ManifestPath) {
    $ManifestPath = Join-Path $repoRoot 'docs\integrations\omp-host-patch-2026-09-19\DEPLOYMENT-MANIFEST.json'
    if ($env:OMP_DEPLOYMENT_MANIFEST) { $ManifestPath = $env:OMP_DEPLOYMENT_MANIFEST }
}
$manifestPath = $ManifestPath

if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    Write-Host "second-brain: deployment manifest missing: $manifestPath" -ForegroundColor Red
    exit 2
}
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json

function Get-FileSha256([string] $Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

$hostRoot = $manifest.host.installed_package
if ($env:OMP_RETAIL_ROOT) { $hostRoot = $env:OMP_RETAIL_ROOT }
$extensionRoot = $manifest.extension.installed_root

if (-not $SkipIdentityCheck) {
    $failures = New-Object System.Collections.Generic.List[string]
    foreach ($file in $manifest.host.files) {
        $path = Join-Path $hostRoot ($file.path.Replace('/', '\'))
        $actual = Get-FileSha256 $path
        if ($null -eq $actual) {
            $failures.Add("host file missing: $($file.path)")
            continue
        }
        if ($file.sealed_sha256 -and $actual -ne $file.sealed_sha256) {
            $failures.Add("host file differs from the sealed bytes: $($file.path)")
        }
        if ($file.bound_sha256 -and $actual -ne $file.bound_sha256) {
            $failures.Add("host file differs from its bound hash: $($file.path)")
        }
    }
    foreach ($file in $manifest.extension.files) {
        $path = Join-Path $extensionRoot ($file.path.Replace('/', '\'))
        $actual = Get-FileSha256 $path
        if ($null -eq $actual) {
            $failures.Add("extension file missing: $($file.path)")
            continue
        }
        if ($actual -ne $file.sealed_sha256) {
            $failures.Add("extension file differs from its sealed source: $($file.path)")
        }
    }
    if ($failures.Count -gt 0) {
        Write-Host "second-brain: refusing to start - installed bytes do not match the deployment manifest." -ForegroundColor Red
        foreach ($failure in ($failures | Select-Object -First 10)) {
            Write-Host "  $failure" -ForegroundColor Red
        }
        if ($failures.Count -gt 10) {
            Write-Host "  ... $($failures.Count - 10) more" -ForegroundColor Red
        }
        Write-Host "  Inspect with: python scripts/generate_omp_deployment_manifest.py --check" -ForegroundColor DarkGray
        exit 2
    }
    Write-Host ("second-brain: patched OMP host verified ({0} host files, {1} extension files)" -f `
        $manifest.host.file_count, $manifest.extension.file_count) -ForegroundColor DarkGray
}

$bun = $manifest.launcher.bun
if (-not (Test-Path -LiteralPath $bun -PathType Leaf)) {
    $bunCommand = Get-Command bun -ErrorAction SilentlyContinue
    if ($bunCommand) { $bun = $bunCommand.Source }
}
if (-not $bun) {
    Write-Host 'second-brain: bun not found; install bun or fix launcher.bun in the manifest' -ForegroundColor Red
    exit 2
}

$entry = Join-Path $hostRoot ($manifest.host.entrypoint.Replace('/', '\'))
& $bun $entry @Rest
exit $LASTEXITCODE

# Installs the Second Brain P0 SHADOW Codex hooks into Codex config.
#
# Target: $env:CODEX_HOME/config.toml, else ~/.codex/config.toml.
# Merges ONLY the [hooks] event keys (SessionStart/UserPromptSubmit/
# SubagentStart/Stop/SessionEnd); never touches [hooks.state], [agents], or
# any other table. Idempotent (marker-guarded); prints the inserted block;
# keeps a timestamped backup for uninstall-codex-hooks.ps1 -RestoreBackup.
param(
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$CodexHome = ""
)
$ErrorActionPreference = "Stop"
$RepoRoot = [System.IO.Path]::GetFullPath($RepoRoot)

if (-not $CodexHome) {
    $CodexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME ".codex" }
}
$configPath = Join-Path $CodexHome "config.toml"
$runPs1 = Join-Path $RepoRoot "brainstem\codex-hooks\run.ps1"
if (-not (Test-Path $runPs1)) { throw "run.ps1 not found at $runPs1" }
$systemDir = [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::System)
$powerShell = Join-Path $systemDir "WindowsPowerShell\v1.0\powershell.exe"
if (-not (Test-Path $powerShell -PathType Leaf)) { throw "Trusted Windows PowerShell not found at $powerShell" }
New-Item -ItemType Directory -Force -Path $CodexHome | Out-Null

$begin = "# BEGIN second-brain-codex-hooks (Phase 0C SHADOW; managed by install-codex-hooks.ps1)"
$end = "# END second-brain-codex-hooks"
$content = if (Test-Path $configPath) { Get-Content -Raw -Encoding UTF8 $configPath } else { "" }


$cmd = "`"$powerShell`" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$runPs1`"" | ConvertTo-Json -Compress
$block = @"
$begin
SessionStart = [{ hooks = [{ type = "command", command = $cmd, async = false }] }]
UserPromptSubmit = [{ hooks = [{ type = "command", command = $cmd, async = false }] }]
SubagentStart = [{ hooks = [{ type = "command", command = $cmd, async = false }] }]
Stop = [{ hooks = [{ type = "command", command = $cmd, async = false }] }]
SessionEnd = [{ hooks = [{ type = "command", command = $cmd, async = false }] }]
$end
"@


$managedPattern = "(?ms)^" + [regex]::Escape($begin) + "`r?`n.*?^" + [regex]::Escape($end) + "(?=`r?$)"
$managed = [regex]::Matches($content, $managedPattern)
if ($content.Contains($begin) -or $content.Contains($end)) {
    if ($managed.Count -ne 1 -or [regex]::Matches($content, [regex]::Escape($begin)).Count -ne 1 -or
        [regex]::Matches($content, [regex]::Escape($end)).Count -ne 1) {
        throw "Managed Codex hooks block is incomplete or duplicated; refusing to rewrite"
    }
    $match = $managed[0]
    $newContent = $content.Substring(0, $match.Index) + $block + $content.Substring($match.Index + $match.Length)
} else {
    # Insert just after the top-level table, before any [hooks.*] subtable.
    $lines = $content -split "`r?`n"
    $out = New-Object System.Collections.Generic.List[string]
    $inserted = $false
    foreach ($line in $lines) {
        $out.Add($line)
        if (-not $inserted -and $line -match '^\[hooks\]\s*$') {
            foreach ($b in ($block -split "`r?`n")) { $out.Add($b) }
            $inserted = $true
        }
    }
    if (-not $inserted) {
        if ($content.Trim()) { $out.Add("") }
        $out.Add("[hooks]")
        foreach ($b in ($block -split "`r?`n")) { $out.Add($b) }
    }
    $newContent = ($out -join "`r`n") + "`r`n"
}
if ($newContent -eq $content) {
    Write-Host "already installed with trusted executable; no changes made."
    exit 0
}
$backup = "$configPath.sb-hooks-backup-$(Get-Date -Format yyyyMMdd-HHmmss)"
if (Test-Path $configPath) { Copy-Item $configPath $backup }
Write-Host "backup: $backup"
[System.IO.File]::WriteAllText($configPath, $newContent, (New-Object System.Text.UTF8Encoding $false))

Write-Host "--- installed into $configPath ---"
Write-Host ($block -replace "`r`n", "`n")
Write-Host "SHADOW: hooks print '{}' (no additionalContext). Reversible via uninstall-codex-hooks.ps1."

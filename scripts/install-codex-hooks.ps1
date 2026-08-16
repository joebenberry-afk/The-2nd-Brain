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

if (-not $CodexHome) {
    $CodexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME ".codex" }
}
$configPath = Join-Path $CodexHome "config.toml"
$runPs1 = Join-Path $RepoRoot "brainstem\codex-hooks\run.ps1"
if (-not (Test-Path $runPs1)) { throw "run.ps1 not found at $runPs1" }
New-Item -ItemType Directory -Force -Path $CodexHome | Out-Null

$begin = "# BEGIN second-brain-codex-hooks (Phase 0C SHADOW; managed by install-codex-hooks.ps1)"
$end = "# END second-brain-codex-hooks"
$content = if (Test-Path $configPath) { Get-Content -Raw $configPath } else { "" }

if ($content -match [regex]::Escape($begin)) {
    Write-Host "already installed (marker present); no changes made."
    exit 0
}

$cmd = "powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File '$runPs1'"
$block = @"
$begin
SessionStart = [{ hooks = [{ type = "command", command = "$cmd", async = false }] }]
UserPromptSubmit = [{ hooks = [{ type = "command", command = "$cmd", async = false }] }]
SubagentStart = [{ hooks = [{ type = "command", command = "$cmd", async = false }] }]
Stop = [{ hooks = [{ type = "command", command = "$cmd", async = false }] }]
SessionEnd = [{ hooks = [{ type = "command", command = "$cmd", async = false }] }]
$end
"@

$backup = "$configPath.sb-hooks-backup-$(Get-Date -Format yyyyMMdd-HHmmss)"
if (Test-Path $configPath) { Copy-Item $configPath $backup }
Write-Host "backup: $backup"

# Insert the block right after an existing top-level [hooks] table header
# (before any [hooks.*] sub-tables), or append a new table at the end.
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
    foreach ($b in ($block -split "`r?`n")) { $out.Add($b) }
}
$newContent = ($out -join "`r`n") + "`r`n"
[System.IO.File]::WriteAllText($configPath, $newContent, (New-Object System.Text.UTF8Encoding $false))

Write-Host "--- installed into $configPath ---"
Write-Host ($block -replace "`r`n", "`n")
Write-Host "SHADOW: hooks print '{}' (no additionalContext). Reversible via uninstall-codex-hooks.ps1."

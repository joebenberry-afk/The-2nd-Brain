# Pester 3.4 regressions for user-owned configuration preservation.
$repo = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))

Describe "Harness hook configuration preservation" {
    It "preserves Unicode settings from BOM-free UTF-8 in Claude Code" {
        $homeDir = Join-Path $env:TEMP ("sb-claude-settings-" + [guid]::NewGuid().ToString("N"))
        $previousHome = $env:CLAUDE_CONFIG_DIR
        New-Item -ItemType Directory -Path $homeDir | Out-Null
        $settingsFile = Join-Path $homeDir "settings.json"
        $description = "Repository " + [char]0x2014 + " " + [char]0x03BB
        $initial = @{ mcpServers = @{ existing = @{ description = $description } }; permissions = @{ allow = @("Read") } }
        [IO.File]::WriteAllText($settingsFile, ($initial | ConvertTo-Json -Depth 10), (New-Object Text.UTF8Encoding $false))
        try {
            $env:CLAUDE_CONFIG_DIR = $homeDir
            & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repo "scripts\install-claude-code-hooks.ps1") -RepoRoot $repo
            $LASTEXITCODE | Should Be 0
            $actual = Get-Content $settingsFile -Raw -Encoding UTF8 | ConvertFrom-Json
            $actual.mcpServers.existing.description | Should Be $description
            ($actual.permissions.allow -join ",") | Should Be "Read"
        } finally {
            $env:CLAUDE_CONFIG_DIR = $previousHome
            Remove-Item -Recurse -Force $homeDir
        }
    }

    It "creates a valid Codex hooks table with a callable Windows command" {
        $homeDir = Join-Path $env:TEMP ("sb-codex-settings-" + [guid]::NewGuid().ToString("N"))
        $sourceDir = Join-Path $homeDir "Brain Source"
        $hookDir = Join-Path $sourceDir "brainstem\codex-hooks"
        New-Item -ItemType Directory -Path $hookDir -Force | Out-Null
        Copy-Item (Join-Path $repo "brainstem\codex-hooks\run.ps1") $hookDir
        $configFile = Join-Path $homeDir "config.toml"
        $description = "Repository " + [char]0x2014 + " " + [char]0x03BB
        $initial = 'display_name = "' + $description + '"' + "`n[sandbox]`nworkspace_write = false`n"
        [IO.File]::WriteAllText($configFile, $initial, (New-Object Text.UTF8Encoding $false))
        $validator = Join-Path $homeDir "validate.py"
        $code = @'
import ctypes
import sys
import tomllib
from pathlib import Path

config = tomllib.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert config["display_name"] == "Repository \u2014 \u03bb"
assert config["sandbox"]["workspace_write"] is False
assert "SessionStart" not in config["sandbox"]
command = config["hooks"]["SessionStart"][0]["hooks"][0]["command"]
split = ctypes.windll.shell32.CommandLineToArgvW
split.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
split.restype = ctypes.POINTER(ctypes.c_wchar_p)
count = ctypes.c_int()
argv = split(command, ctypes.byref(count))
try:
    assert Path(argv[count.value - 1]).is_file()
finally:
    free = ctypes.windll.kernel32.LocalFree
    free.argtypes = [ctypes.c_void_p]
    free.restype = ctypes.c_void_p
    free(argv)
'@
        [IO.File]::WriteAllText($validator, $code, (New-Object Text.UTF8Encoding $false))
        try {
            & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repo "scripts\install-codex-hooks.ps1") -RepoRoot $sourceDir -CodexHome $homeDir
            $LASTEXITCODE | Should Be 0
            & (Join-Path $repo ".venv\Scripts\python.exe") $validator $configFile
            $LASTEXITCODE | Should Be 0
        } finally {
            Remove-Item -Recurse -Force $homeDir
        }
    }
}

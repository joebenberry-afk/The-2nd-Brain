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
            Push-Location $repo
            try {
                & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repo "scripts\install-claude-code-hooks.ps1") -RepoRoot "."
            } finally {
                Pop-Location
            }
            $LASTEXITCODE | Should Be 0
            $actual = Get-Content $settingsFile -Raw -Encoding UTF8 | ConvertFrom-Json
            $actual.mcpServers.existing.description | Should Be $description
            $command = $actual.hooks.SessionStart[0].hooks[0].command
            $command -match '^"([^"]+)" -NoProfile ' | Should Be $true
            $trusted = Join-Path ([System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::System)) "WindowsPowerShell\v1.0\powershell.exe"
            $matches[1] | Should Be $trusted
            $command -match ' -File "([^"]+)"$' | Should Be $true
            $matches[1] | Should Be (Join-Path $repo "brainstem\adapters\claude-code\scripts\run-hook.ps1")
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
    system_dir = ctypes.create_unicode_buffer(32768)
    assert ctypes.windll.kernel32.GetSystemDirectoryW(system_dir, len(system_dir))
    assert argv[0].casefold() == str(Path(system_dir.value) / "WindowsPowerShell" / "v1.0" / "powershell.exe").casefold()
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
    It "upgrades a managed Codex block without changing other tables" {
        $homeDir = Join-Path $env:TEMP ("sb-codex-upgrade-" + [guid]::NewGuid().ToString("N"))
        $sourceDir = Join-Path $homeDir "Brain Source"
        $hookDir = Join-Path $sourceDir "brainstem\codex-hooks"
        New-Item -ItemType Directory -Path $hookDir -Force | Out-Null
        Copy-Item (Join-Path $repo "brainstem\codex-hooks\run.ps1") $hookDir
        $configFile = Join-Path $homeDir "config.toml"
        $legacy = @'
display_name = "preserve"
[hooks]
# BEGIN second-brain-codex-hooks (Phase 0C SHADOW; managed by install-codex-hooks.ps1)
SessionStart = [{ hooks = [{ type = "command", command = "powershell -File legacy.ps1", async = false }] }]
# END second-brain-codex-hooks
[hooks.state]
enabled = false
'@
        [IO.File]::WriteAllText($configFile, $legacy, (New-Object Text.UTF8Encoding $false))
        try {
            Push-Location $sourceDir
            try {
                & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repo "scripts\install-codex-hooks.ps1") -RepoRoot "." -CodexHome $homeDir | Out-Null
            } finally {
                Pop-Location
            }
            $LASTEXITCODE | Should Be 0
            $updated = [IO.File]::ReadAllText($configFile)
            $updated | Should Match '\[hooks\.state\]\s*enabled = false'
            $updated | Should Not Match 'command = "powershell '
            $updated -match 'command = ("(?:\\.|[^"\\])*")' | Should Be $true
            $command = $matches[1] | ConvertFrom-Json
            $command -match ' -File "([^"]+)"$' | Should Be $true
            $matches[1] | Should Be (Join-Path $sourceDir "brainstem\codex-hooks\run.ps1")
            & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repo "scripts\install-codex-hooks.ps1") -RepoRoot $sourceDir -CodexHome $homeDir | Out-Null
            $LASTEXITCODE | Should Be 0
            [IO.File]::ReadAllText($configFile) | Should Be $updated
        } finally {
            Remove-Item -Recurse -Force $homeDir
        }
    }
    It "installs rendered Antigravity hooks without PATH executable lookup" {
        $fixture = Join-Path $env:TEMP ("sb-agy-settings-" + [guid]::NewGuid().ToString("N"))
        $source = Join-Path $fixture "Brain Source\brainstem\adapters\antigravity"
        $plugins = Join-Path $fixture "plugins"
        $previousHome = $env:SECOND_BRAIN_HOME
        New-Item -ItemType Directory -Path $source -Force | Out-Null
        Copy-Item (Join-Path $repo "brainstem\adapters\antigravity\*") $source -Recurse
        try {
            $env:SECOND_BRAIN_HOME = Join-Path $fixture "Brain Source"
            & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repo "scripts\install-antigravity-adapter.ps1") -Target App -PluginsDir $plugins | Out-Null
            $LASTEXITCODE | Should Be 0
            $installed = Join-Path $plugins "second-brain-adapter"
            $hooksFile = Join-Path $installed "hooks.json"
            $hooks = (Get-Content $hooksFile -Raw -Encoding UTF8 | ConvertFrom-Json).'second-brain'
            $trusted = Join-Path ([System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::System)) "WindowsPowerShell\v1.0\powershell.exe"
            $commands = @($hooks.PreInvocation[0].command, $hooks.PostInvocation[0].command,
                $hooks.PostToolUse[0].hooks[0].command, $hooks.Stop[0].command)
            foreach ($command in $commands) {
                $command.StartsWith("`"$trusted`" -ExecutionPolicy Bypass -File `"$(Join-Path $installed 'scripts\run-hook.ps1')`" -Event ") | Should Be $true
            }
            (Test-Path (Join-Path $installed "scripts\run-hook.ps1")) | Should Be $true
            $hash = (Get-FileHash $hooksFile).Hash
            & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repo "scripts\install-antigravity-adapter.ps1") -Target App -PluginsDir $plugins | Out-Null
            $LASTEXITCODE | Should Be 0
            (Get-FileHash $hooksFile).Hash | Should Be $hash
        } finally {
            $env:SECOND_BRAIN_HOME = $previousHome
            Remove-Item -Recurse -Force $fixture
        }
    }
}

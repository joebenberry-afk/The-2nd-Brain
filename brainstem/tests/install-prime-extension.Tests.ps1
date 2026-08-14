# Pester tests for scripts/install-prime-extension.ps1 + uninstall (Pester 3.4 syntax).
# Run: powershell -NoProfile -Command "Invoke-Pester -Script brainstem\tests\install-prime-extension.Tests.ps1 -PassThru"

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Split-Path -Parent (Split-Path -Parent $here)

Describe "prime extension install/uninstall scripts" {

    BeforeEach {
        $testRoot = Join-Path $env:TEMP ("sb-ext-test-" + [guid]::NewGuid().ToString("N"))
        $brain = Join-Path $testRoot "brain"
        $extRoot = Join-Path $testRoot "extensions"
        $settings = Join-Path $testRoot "settings.json"
        $src = Join-Path $brain "brainstem\prime-extension\src"
        New-Item -ItemType Directory -Force -Path $src | Out-Null
        Set-Content -Path (Join-Path $src "index.ts") -Value "export default function (pi) {}"
        Set-Content -Path (Join-Path $src "storage.ts") -Value "export const x = 1"
        New-Item -ItemType Directory -Force -Path (Join-Path $src "types") | Out-Null
        Set-Content -Path (Join-Path $src "types\prime.d.ts") -Value "declare const pi: unknown"
        New-Item -ItemType Directory -Force -Path (Join-Path $brain "backups") | Out-Null
        $env:SECOND_BRAIN_HOME = $brain
        $script:repo = $repo
        $script:brain = $brain
        $script:extRoot = $extRoot
        $script:settings = $settings
    }

    AfterEach {
        Remove-Item -Recurse -Force $testRoot -ErrorAction SilentlyContinue
        Remove-Item Env:SECOND_BRAIN_HOME -ErrorAction SilentlyContinue
    }

    It "installs into a fresh extensions dir" {
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $script:repo "scripts\install-prime-extension.ps1") -ExtensionsDir $script:extRoot -SettingsFile $script:settings
        $LASTEXITCODE | Should Be 0
        (Test-Path (Join-Path $script:extRoot "second-brain\index.ts")) | Should Be $true
        (Test-Path (Join-Path $script:extRoot "second-brain\types\prime.d.ts")) | Should Be $true
    }

    It "is idempotent and backs up the previous target" {
        New-Item -ItemType Directory -Force -Path (Join-Path $script:extRoot "second-brain") | Out-Null
        Set-Content -Path (Join-Path $script:extRoot "second-brain\previous-marker.txt") -Value "user content"
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $script:repo "scripts\install-prime-extension.ps1") -ExtensionsDir $script:extRoot -SettingsFile $script:settings
        $LASTEXITCODE | Should Be 0
        $backup = Get-ChildItem (Join-Path $script:brain "backups") -Directory -Filter "*-prime-extension-pre-install" | Sort-Object Name -Descending | Select-Object -First 1
        (Test-Path (Join-Path $backup.FullName "extensions\second-brain\previous-marker.txt")) | Should Be $true
        (Test-Path (Join-Path $script:extRoot "second-brain\previous-marker.txt")) | Should Be $false
    }

    It "uninstall restores the previous extension from the newest backup" {
        # install, then add a marker version of the extension, reinstall (backup has marker)
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $script:repo "scripts\install-prime-extension.ps1") -ExtensionsDir $script:extRoot -SettingsFile $script:settings | Out-Null
        Set-Content -Path (Join-Path $script:extRoot "second-brain\owned-marker.txt") -Value "mine"
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $script:repo "scripts\install-prime-extension.ps1") -ExtensionsDir $script:extRoot -SettingsFile $script:settings | Out-Null
        Remove-Item -Recurse -Force (Join-Path $script:extRoot "second-brain")
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $script:repo "scripts\uninstall-prime-extension.ps1") -ExtensionsDir $script:extRoot -SettingsFile $script:settings
        $LASTEXITCODE | Should Be 0
        (Test-Path (Join-Path $script:extRoot "second-brain\owned-marker.txt")) | Should Be $true
    }

    It "uninstall without backup succeeds and reports not installed" {
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $script:repo "scripts\uninstall-prime-extension.ps1") -ExtensionsDir $script:extRoot -SettingsFile $script:settings
        $LASTEXITCODE | Should Be 0
    }

    It "fails when source index.ts is missing" {
        Remove-Item -Recurse -Force (Join-Path $script:brain "brainstem\prime-extension\src")
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $script:repo "scripts\install-prime-extension.ps1") -ExtensionsDir $script:extRoot -SettingsFile $script:settings
        $LASTEXITCODE | Should Be 2
    }
}

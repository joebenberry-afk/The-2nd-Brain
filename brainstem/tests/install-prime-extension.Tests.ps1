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
        # types/ is a SIBLING of src/ in the real layout (types/prime.d.ts)
        $typesSrc = Join-Path $brain "brainstem\prime-extension\types"
        New-Item -ItemType Directory -Force -Path $typesSrc | Out-Null
        Set-Content -Path (Join-Path $typesSrc "prime.d.ts") -Value "declare const pi: unknown"
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

    It "install defaults ExtensionsDir/SettingsFile to the OMP auto-discovery path, not .prime" {
        $fakeHome = Join-Path $testRoot "userprofile-install"
        New-Item -ItemType Directory -Force -Path $fakeHome | Out-Null
        $oldUserProfile = $env:USERPROFILE
        $env:USERPROFILE = $fakeHome
        try {
            & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $script:repo "scripts\install-prime-extension.ps1") -SourceRoot $script:brain
            $LASTEXITCODE | Should Be 0
        } finally {
            $env:USERPROFILE = $oldUserProfile
        }
        (Test-Path (Join-Path $fakeHome ".omp\agent\extensions\second-brain\index.ts")) | Should Be $true
        (Test-Path (Join-Path $fakeHome ".prime\agent\extensions\second-brain\index.ts")) | Should Be $false
        (Test-Path (Join-Path $fakeHome ".prime")) | Should Be $false
    }

    It "uninstall defaults ExtensionsDir/SettingsFile to the OMP auto-discovery path, not .prime" {
        $fakeHome = Join-Path $testRoot "userprofile-uninstall"
        $extDir = Join-Path $fakeHome ".omp\agent\extensions"
        New-Item -ItemType Directory -Force -Path (Join-Path $extDir "second-brain") | Out-Null
        Set-Content -Path (Join-Path $extDir "second-brain\marker.txt") -Value "present"
        $oldUserProfile = $env:USERPROFILE
        $env:USERPROFILE = $fakeHome
        try {
            & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $script:repo "scripts\uninstall-prime-extension.ps1") -SourceRoot $script:brain
            $LASTEXITCODE | Should Be 0
        } finally {
            $env:USERPROFILE = $oldUserProfile
        }
        (Test-Path (Join-Path $extDir "second-brain\marker.txt")) | Should Be $false
        (Test-Path (Join-Path $fakeHome ".prime")) | Should Be $false
    }

    It "fails when source index.ts is missing" {
        Remove-Item -Recurse -Force (Join-Path $script:brain "brainstem\prime-extension\src")
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $script:repo "scripts\install-prime-extension.ps1") -ExtensionsDir $script:extRoot -SettingsFile $script:settings
        $LASTEXITCODE | Should Be 2
    }
}

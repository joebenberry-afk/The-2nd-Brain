# Pester tests for the OMP extension installer and rollback (Pester 3.4 syntax).
# Run from the repository root with the command recorded in the closeout report.

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Split-Path -Parent (Split-Path -Parent $here)

function Get-TestManifest([string]$Root) {
    if (-not (Test-Path $Root -PathType Container)) { return @() }
    return @(Get-ChildItem -Path $Root -File -Recurse |
        Sort-Object FullName |
        ForEach-Object {
            $relative = $_.FullName.Substring($Root.Length).TrimStart("\", "/").Replace("\", "/")
            "$relative`t$((Get-FileHash -Algorithm SHA256 -Path $_.FullName).Hash.ToLowerInvariant())"
        })
}

function Invoke-InjectedFailure(
    [string]$Root,
    [string]$ScriptPath,
    [string]$FailureCommand,
    [string]$FailureSide,
    [string]$FailureLeaf,
    [string[]]$ScriptArguments
) {
    $wrapper = Join-Path $Root ("failure-wrapper-" + [guid]::NewGuid().ToString("N") + ".ps1")
    @'
param(
    [string]$ScriptPath,
    [string]$FailureCommand,
    [string]$FailureSide,
    [string]$FailureLeaf
)
$realCommand = Get-Command $FailureCommand -CommandType Cmdlet
$failure = {
    param(
        [object]$Path,
        [object]$Destination,
        [string]$ItemType,
        [switch]$Recurse,
        [switch]$Force
    )
    $candidate = if ($FailureSide -eq "Destination") { $Destination } else { $Path }
    if ([System.IO.Path]::GetFileName([string]$candidate) -like $FailureLeaf) {
        throw "Injected $FailureCommand failure for $candidate"
    }
    & $realCommand @PSBoundParameters
}.GetNewClosure()
Set-Item -Path ("Function:\global:{0}" -f $FailureCommand) -Value $failure
& $ScriptPath @args
'@ | Set-Content -Path $wrapper
    $output = & powershell -NoProfile -ExecutionPolicy Bypass -File $wrapper `
        $ScriptPath $FailureCommand $FailureSide $FailureLeaf @ScriptArguments 2>&1
    return [pscustomobject]@{
        ExitCode = $LASTEXITCODE
        Output = @($output)
    }
}

function Invoke-PhantomAfterSwapInstall(
    [string]$Root,
    [string]$ScriptPath,
    [string]$StageLeaf,
    [string]$PhantomName,
    [string[]]$ScriptArguments
) {
    # Moves the stage into place for real, then drops an extra file into the
    # installed tree. That reproduces "the swap did not land as verified" without
    # pretending the filesystem failed.
    $wrapper = Join-Path $Root ("phantom-wrapper-" + [guid]::NewGuid().ToString("N") + ".ps1")
    @'
param(
    [string]$ScriptPath,
    [string]$StageLeaf,
    [string]$PhantomName
)
$realCommand = Get-Command Move-Item -CommandType Cmdlet
$override = {
    param(
        [object]$Path,
        [object]$Destination,
        [object]$LiteralPath,
        [switch]$Force,
        [switch]$Recurse
    )
    $moved = & $realCommand @PSBoundParameters
    $leaf = [System.IO.Path]::GetFileName([string]$Path)
    if ($leaf -like $StageLeaf) {
        [System.IO.File]::WriteAllText(
            (Join-Path ([string]$Destination) $PhantomName), "unverified extra file")
    }
    return $moved
}.GetNewClosure()
Set-Item -Path ("Function:\global:{0}" -f "Move-Item") -Value $override
& $ScriptPath @args
'@ | Set-Content -Path $wrapper
    $output = & powershell -NoProfile -ExecutionPolicy Bypass -File $wrapper `
        $ScriptPath $StageLeaf $PhantomName @ScriptArguments 2>&1
    return [pscustomobject]@{
        ExitCode = $LASTEXITCODE
        Output = @($output)
    }
}

Describe "OMP extension install and rollback" {
    BeforeEach {
        $testRoot = Join-Path $env:TEMP ("sb-ext-test-" + [guid]::NewGuid().ToString("N"))
        $brain = Join-Path $testRoot "brain"
        $extRoot = Join-Path $testRoot "extensions"
        $settings = Join-Path $testRoot "settings.json"
        $src = Join-Path $brain "brainstem\prime-extension\src"
        $typesSrc = Join-Path $brain "brainstem\prime-extension\types"
        New-Item -ItemType Directory -Force -Path $src | Out-Null
        New-Item -ItemType Directory -Force -Path $typesSrc | Out-Null
        Set-Content -Path (Join-Path $src "index.ts") -Value "export default function (pi) {}"
        Set-Content -Path (Join-Path $src "storage.ts") -Value "export const x = 1"
        Set-Content -Path (Join-Path $typesSrc "prime.d.ts") -Value "declare const pi: unknown"

        # These source-tree files are intentionally outside the deployed layout.
        New-Item -ItemType Directory -Force -Path (Join-Path $src "nested") | Out-Null
        Set-Content -Path (Join-Path $src "nested\ignored.ts") -Value "export const ignored = true"
        New-Item -ItemType Directory -Force -Path (Join-Path $typesSrc "nested") | Out-Null
        Set-Content -Path (Join-Path $typesSrc "nested\ignored.d.ts") -Value "declare const ignored: true"
        New-Item -ItemType Directory -Force -Path (Join-Path $brain "brainstem\prime-extension\tests") | Out-Null
        Set-Content -Path (Join-Path $brain "brainstem\prime-extension\tests\wiring.test.ts") -Value "throw new Error('not deployed')"
        New-Item -ItemType Directory -Force -Path (Join-Path $brain "brainstem\prime-extension\node_modules\fixture") | Out-Null
        Set-Content -Path (Join-Path $brain "brainstem\prime-extension\node_modules\fixture\index.ts") -Value "not deployed"
        Set-Content -Path (Join-Path $brain "brainstem\prime-extension\package.json") -Value "{}"
        New-Item -ItemType Directory -Force -Path (Join-Path $brain "backups") | Out-Null

        $script:oldSecondBrainHome = $env:SECOND_BRAIN_HOME
        $script:oldUserProfile = $env:USERPROFILE
        $env:SECOND_BRAIN_HOME = Join-Path $testRoot "unrelated-state-home"
        $script:repo = $repo
        $script:testRoot = $testRoot
        $script:brain = $brain
        $script:extRoot = $extRoot
        $script:settings = $settings
        $script:target = Join-Path $extRoot "second-brain"
        $script:installer = Join-Path $repo "scripts\install-prime-extension.ps1"
        $script:uninstaller = Join-Path $repo "scripts\uninstall-prime-extension.ps1"
    }

    AfterEach {
        $env:USERPROFILE = $script:oldUserProfile
        if ($null -eq $script:oldSecondBrainHome) {
            Remove-Item Env:SECOND_BRAIN_HOME -ErrorAction SilentlyContinue
        } else {
            $env:SECOND_BRAIN_HOME = $script:oldSecondBrainHome
        }
        Remove-Item -Recurse -Force $script:testRoot -ErrorAction SilentlyContinue
    }

    It "uses explicit destination and deploys only flattened src plus types" {
        $env:USERPROFILE = Join-Path $testRoot "alternate-profile"
        & powershell -NoProfile -ExecutionPolicy Bypass -File $script:installer `
            -SourceRoot $script:brain -ExtensionsDir $script:extRoot -SettingsFile $script:settings
        $LASTEXITCODE | Should Be 0

        $paths = @(Get-ChildItem -Path $script:target -File -Recurse | ForEach-Object {
            $_.FullName.Substring($script:target.Length).TrimStart("\", "/").Replace("\", "/")
        } | Sort-Object)
        ($paths -join ",") | Should Be "index.ts,storage.ts,types/prime.d.ts"
        (Test-Path (Join-Path $env:USERPROFILE ".omp")) | Should Be $false
    }

    It "is idempotent and backs up the previous target" {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $script:installer `
            -SourceRoot $script:brain -ExtensionsDir $script:extRoot | Out-Null
        $LASTEXITCODE | Should Be 0
        Set-Content -Path (Join-Path $script:target "previous-marker.txt") -Value "user content"

        & powershell -NoProfile -ExecutionPolicy Bypass -File $script:installer `
            -SourceRoot $script:brain -ExtensionsDir $script:extRoot | Out-Null
        $LASTEXITCODE | Should Be 0
        $backups = @(Get-ChildItem (Join-Path $script:brain "backups") -Directory |
            Sort-Object Name -Descending)
        $backups.Count | Should Be 2
        (Test-Path (Join-Path $backups[0].FullName "extensions\second-brain\previous-marker.txt")) | Should Be $true
        (Test-Path (Join-Path $script:target "previous-marker.txt")) | Should Be $false
    }

    It "selects source independently of SECOND_BRAIN_HOME" {
        $decoy = Join-Path $env:SECOND_BRAIN_HOME "brainstem\prime-extension\src"
        New-Item -ItemType Directory -Force -Path $decoy | Out-Null
        Set-Content -Path (Join-Path $decoy "index.ts") -Value "decoy state source"

        & powershell -NoProfile -ExecutionPolicy Bypass -File $script:installer `
            -SourceRoot $script:brain -ExtensionsDir $script:extRoot
        $LASTEXITCODE | Should Be 0
        (Get-Content -Raw (Join-Path $script:target "index.ts")) | Should Match "export default"
        (Get-Content -Raw (Join-Path $script:target "index.ts")) | Should Not Match "decoy"
    }

    It "defaults install to an alternate USERPROFILE OMP root without claiming settings" {
        $fakeHome = Join-Path $testRoot "userprofile-install"
        $defaultSettings = Join-Path $fakeHome ".omp\agent\settings.json"
        New-Item -ItemType Directory -Force -Path (Split-Path $defaultSettings) | Out-Null
        Set-Content -Path $defaultSettings -Value '{"owner":"user"}'
        $before = (Get-FileHash -Algorithm SHA256 $defaultSettings).Hash
        $env:USERPROFILE = $fakeHome

        & powershell -NoProfile -ExecutionPolicy Bypass -File $script:installer -SourceRoot $script:brain
        $LASTEXITCODE | Should Be 0

        (Test-Path (Join-Path $fakeHome ".omp\agent\extensions\second-brain\index.ts")) | Should Be $true
        (Test-Path (Join-Path $fakeHome ".prime")) | Should Be $false
        (Get-FileHash -Algorithm SHA256 $defaultSettings).Hash | Should Be $before
        $backup = Get-ChildItem (Join-Path $script:brain "backups") -Directory |
            Sort-Object Name -Descending | Select-Object -First 1
        (Test-Path (Join-Path $backup.FullName "settings")) | Should Be $false
    }

    It "defaults uninstall to an alternate USERPROFILE OMP root" {
        $fakeHome = Join-Path $testRoot "userprofile-uninstall"
        $defaultTarget = Join-Path $fakeHome ".omp\agent\extensions\second-brain"
        New-Item -ItemType Directory -Force -Path $defaultTarget | Out-Null
        Set-Content -Path (Join-Path $defaultTarget "marker.txt") -Value "present"
        $env:USERPROFILE = $fakeHome

        & powershell -NoProfile -ExecutionPolicy Bypass -File $script:uninstaller
        $LASTEXITCODE | Should Be 0
        (Test-Path $defaultTarget) | Should Be $false
        (Test-Path (Join-Path $fakeHome ".prime")) | Should Be $false
    }

    It "backs up and restores the previous extension byte exactly" {
        New-Item -ItemType Directory -Force -Path (Join-Path $script:target "nested") | Out-Null
        [System.IO.File]::WriteAllBytes((Join-Path $script:target "index.ts"), [byte[]](0, 13, 10, 255))
        [System.IO.File]::WriteAllBytes((Join-Path $script:target "nested\payload.bin"), [byte[]](1, 2, 3, 4, 5))
        $before = (Get-TestManifest $script:target) -join "`n"

        & powershell -NoProfile -ExecutionPolicy Bypass -File $script:installer `
            -SourceRoot $script:brain -ExtensionsDir $script:extRoot
        $LASTEXITCODE | Should Be 0
        $backups = @(Get-ChildItem (Join-Path $script:brain "backups") -Directory)
        $backups.Count | Should Be 1
        (Test-Path (Join-Path $backups[0].FullName "install.json")) | Should Be $true

        & powershell -NoProfile -ExecutionPolicy Bypass -File $script:uninstaller `
            -ExtensionsDir $script:extRoot -BackupDir $backups[0].FullName
        $LASTEXITCODE | Should Be 0
        ((Get-TestManifest $script:target) -join "`n") | Should Be $before
    }

    It "preserves the current extension when staging cannot start" {
        New-Item -ItemType Directory -Force -Path $script:target | Out-Null
        Set-Content -Path (Join-Path $script:target "keep.txt") -Value "keep"
        $before = (Get-TestManifest $script:target) -join "`n"
        $result = Invoke-InjectedFailure $testRoot $script:installer "New-Item" "Path" `
            ".second-brain-install-*" @("-SourceRoot", $script:brain, "-ExtensionsDir", $script:extRoot)

        $result.ExitCode | Should Not Be 0
        ((Get-TestManifest $script:target) -join "`n") | Should Be $before
    }

    It "preserves the current extension when staging copy fails" {
        New-Item -ItemType Directory -Force -Path $script:target | Out-Null
        Set-Content -Path (Join-Path $script:target "keep.txt") -Value "keep"
        $before = (Get-TestManifest $script:target) -join "`n"
        $result = Invoke-InjectedFailure $testRoot $script:installer "Copy-Item" "Destination" `
            ".second-brain-install-*" @("-SourceRoot", $script:brain, "-ExtensionsDir", $script:extRoot)

        $result.ExitCode | Should Not Be 0
        ((Get-TestManifest $script:target) -join "`n") | Should Be $before
        @(Get-ChildItem $script:extRoot -Directory -Filter ".second-brain-install-*").Count | Should Be 0
    }

    It "restores the current extension when replacement move fails" {
        New-Item -ItemType Directory -Force -Path $script:target | Out-Null
        Set-Content -Path (Join-Path $script:target "keep.txt") -Value "keep"
        $before = (Get-TestManifest $script:target) -join "`n"
        $result = Invoke-InjectedFailure $testRoot $script:installer "Move-Item" "Path" `
            ".second-brain-install-*" @("-SourceRoot", $script:brain, "-ExtensionsDir", $script:extRoot)

        $result.ExitCode | Should Not Be 0
        ((Get-TestManifest $script:target) -join "`n") | Should Be $before
        @(Get-ChildItem $script:extRoot -Directory -Filter ".second-brain-*").Count | Should Be 0
    }

    It "rejects a missing explicit backup before touching the current extension" {
        New-Item -ItemType Directory -Force -Path $script:target | Out-Null
        Set-Content -Path (Join-Path $script:target "keep.txt") -Value "keep"
        $before = (Get-TestManifest $script:target) -join "`n"

        & powershell -NoProfile -ExecutionPolicy Bypass -File $script:uninstaller `
            -ExtensionsDir $script:extRoot -BackupDir (Join-Path $testRoot "missing-backup") 2>&1 | Out-Null
        $LASTEXITCODE | Should Not Be 0
        ((Get-TestManifest $script:target) -join "`n") | Should Be $before
    }

    It "rejects a wrong explicit backup before touching the current extension" {
        New-Item -ItemType Directory -Force -Path $script:target | Out-Null
        Set-Content -Path (Join-Path $script:target "keep.txt") -Value "keep"
        $wrongBackup = Join-Path $testRoot "wrong-backup"
        New-Item -ItemType Directory -Force -Path (Join-Path $wrongBackup "extensions\second-brain") | Out-Null
        Set-Content -Path (Join-Path $wrongBackup "extensions\second-brain\wrong.txt") -Value "wrong"
        [ordered]@{ schema_version = 1; target = $script:target } |
            ConvertTo-Json | Set-Content -Path (Join-Path $wrongBackup "install.json")
        $before = (Get-TestManifest $script:target) -join "`n"

        & powershell -NoProfile -ExecutionPolicy Bypass -File $script:uninstaller `
            -ExtensionsDir $script:extRoot -BackupDir $wrongBackup 2>&1 | Out-Null
        $LASTEXITCODE | Should Not Be 0
        ((Get-TestManifest $script:target) -join "`n") | Should Be $before
    }

    It "rejects a tampered installer backup before touching the current extension" {
        New-Item -ItemType Directory -Force -Path $script:target | Out-Null
        Set-Content -Path (Join-Path $script:target "old.txt") -Value "old"
        & powershell -NoProfile -ExecutionPolicy Bypass -File $script:installer `
            -SourceRoot $script:brain -ExtensionsDir $script:extRoot | Out-Null
        $LASTEXITCODE | Should Be 0
        $backup = Get-ChildItem (Join-Path $script:brain "backups") -Directory | Select-Object -First 1
        Set-Content -Path (Join-Path $backup.FullName "extensions\second-brain\old.txt") -Value "tampered"
        Set-Content -Path (Join-Path $script:target "current.txt") -Value "current"
        $before = (Get-TestManifest $script:target) -join "`n"

        & powershell -NoProfile -ExecutionPolicy Bypass -File $script:uninstaller `
            -ExtensionsDir $script:extRoot -BackupDir $backup.FullName 2>&1 | Out-Null
        $LASTEXITCODE | Should Not Be 0
        ((Get-TestManifest $script:target) -join "`n") | Should Be $before
    }

    It "rejects an installer backup recorded for another destination" {
        New-Item -ItemType Directory -Force -Path $script:target | Out-Null
        Set-Content -Path (Join-Path $script:target "old.txt") -Value "old"
        & powershell -NoProfile -ExecutionPolicy Bypass -File $script:installer `
            -SourceRoot $script:brain -ExtensionsDir $script:extRoot | Out-Null
        $LASTEXITCODE | Should Be 0
        $backup = Get-ChildItem (Join-Path $script:brain "backups") -Directory | Select-Object -First 1

        $otherRoot = Join-Path $testRoot "other-extensions"
        $otherTarget = Join-Path $otherRoot "second-brain"
        New-Item -ItemType Directory -Force -Path $otherTarget | Out-Null
        Set-Content -Path (Join-Path $otherTarget "keep.txt") -Value "keep"
        $before = (Get-TestManifest $otherTarget) -join "`n"
        & powershell -NoProfile -ExecutionPolicy Bypass -File $script:uninstaller `
            -ExtensionsDir $otherRoot -BackupDir $backup.FullName 2>&1 | Out-Null

        $LASTEXITCODE | Should Not Be 0
        ((Get-TestManifest $otherTarget) -join "`n") | Should Be $before
    }

    It "does not choose an unrelated latest backup when none is explicit" {
        New-Item -ItemType Directory -Force -Path $script:target | Out-Null
        Set-Content -Path (Join-Path $script:target "current.txt") -Value "current"
        $unrelated = Join-Path $script:brain "backups\99999999-999999-999-prime-extension-pre-install"
        New-Item -ItemType Directory -Force -Path (Join-Path $unrelated "extensions\second-brain") | Out-Null
        Set-Content -Path (Join-Path $unrelated "extensions\second-brain\unrelated.txt") -Value "unrelated"

        & powershell -NoProfile -ExecutionPolicy Bypass -File $script:uninstaller `
            -SourceRoot $script:brain -ExtensionsDir $script:extRoot
        $LASTEXITCODE | Should Be 0
        (Test-Path $script:target) | Should Be $false
        (Test-Path $unrelated) | Should Be $true
    }

    It "never restores or changes configuration it does not own" {
        Set-Content -Path $script:settings -Value '{"version":"before"}'
        & powershell -NoProfile -ExecutionPolicy Bypass -File $script:installer `
            -SourceRoot $script:brain -ExtensionsDir $script:extRoot -SettingsFile $script:settings | Out-Null
        $LASTEXITCODE | Should Be 0
        $backup = Get-ChildItem (Join-Path $script:brain "backups") -Directory | Select-Object -First 1
        (Get-Content -Raw (Join-Path $backup.FullName "settings\settings.json")) | Should Match '"before"'

        Set-Content -Path $script:settings -Value '{"version":"after"}'
        & powershell -NoProfile -ExecutionPolicy Bypass -File $script:uninstaller `
            -ExtensionsDir $script:extRoot -SettingsFile $script:settings -BackupDir $backup.FullName | Out-Null
        $LASTEXITCODE | Should Be 0
        (Test-Path $script:target) | Should Be $false
        (Get-Content -Raw $script:settings) | Should Match '"after"'
    }

    It "leaves the current extension intact when restore staging copy fails" {
        New-Item -ItemType Directory -Force -Path $script:target | Out-Null
        Set-Content -Path (Join-Path $script:target "old.txt") -Value "old"
        & powershell -NoProfile -ExecutionPolicy Bypass -File $script:installer `
            -SourceRoot $script:brain -ExtensionsDir $script:extRoot | Out-Null
        $backup = Get-ChildItem (Join-Path $script:brain "backups") -Directory | Select-Object -First 1
        Set-Content -Path (Join-Path $script:target "current.txt") -Value "current"
        $before = (Get-TestManifest $script:target) -join "`n"

        $result = Invoke-InjectedFailure $testRoot $script:uninstaller "Copy-Item" "Destination" `
            ".second-brain-restore-*" @("-ExtensionsDir", $script:extRoot, "-BackupDir", $backup.FullName)
        $result.ExitCode | Should Not Be 0
        ((Get-TestManifest $script:target) -join "`n") | Should Be $before
    }

    It "restores the current extension when restore replacement move fails" {
        New-Item -ItemType Directory -Force -Path $script:target | Out-Null
        Set-Content -Path (Join-Path $script:target "old.txt") -Value "old"
        & powershell -NoProfile -ExecutionPolicy Bypass -File $script:installer `
            -SourceRoot $script:brain -ExtensionsDir $script:extRoot | Out-Null
        $backup = Get-ChildItem (Join-Path $script:brain "backups") -Directory | Select-Object -First 1
        Set-Content -Path (Join-Path $script:target "current.txt") -Value "current"
        $before = (Get-TestManifest $script:target) -join "`n"

        $result = Invoke-InjectedFailure $testRoot $script:uninstaller "Move-Item" "Path" `
            ".second-brain-restore-*" @("-ExtensionsDir", $script:extRoot, "-BackupDir", $backup.FullName)
        $result.ExitCode | Should Not Be 0
        ((Get-TestManifest $script:target) -join "`n") | Should Be $before
        @(Get-ChildItem $script:extRoot -Directory -Filter ".second-brain-*").Count | Should Be 0
    }

    It "fails on missing source without deleting the current extension" {
        New-Item -ItemType Directory -Force -Path $script:target | Out-Null
        Set-Content -Path (Join-Path $script:target "keep.txt") -Value "keep"
        $before = (Get-TestManifest $script:target) -join "`n"
        Remove-Item -Recurse -Force (Join-Path $script:brain "brainstem\prime-extension\src")

        & powershell -NoProfile -ExecutionPolicy Bypass -File $script:installer `
            -SourceRoot $script:brain -ExtensionsDir $script:extRoot 2>&1 | Out-Null
        $LASTEXITCODE | Should Not Be 0
        ((Get-TestManifest $script:target) -join "`n") | Should Be $before
    }

    It "removes a freshly installed extension that does not match source" {
        New-Item -ItemType Directory -Force -Path $script:extRoot | Out-Null
        $result = Invoke-PhantomAfterSwapInstall $testRoot $script:installer `
            ".second-brain-install-*" "phantom-after-swap.ts" `
            @("-SourceRoot", $script:brain, "-ExtensionsDir", $script:extRoot)

        $result.ExitCode | Should Not Be 0
        (Test-Path $script:target) | Should Be $false
        @(Get-ChildItem $script:extRoot -Directory -Filter ".second-brain-*").Count | Should Be 0
    }

    It "restores the previous extension when the installed tree does not match source" {
        New-Item -ItemType Directory -Force -Path $script:target | Out-Null
        Set-Content -Path (Join-Path $script:target "keep.txt") -Value "keep"
        $before = (Get-TestManifest $script:target) -join "`n"

        $result = Invoke-PhantomAfterSwapInstall $testRoot $script:installer `
            ".second-brain-install-*" "phantom-after-swap.ts" `
            @("-SourceRoot", $script:brain, "-ExtensionsDir", $script:extRoot)

        $result.ExitCode | Should Not Be 0
        ((Get-TestManifest $script:target) -join "`n") | Should Be $before
        @(Get-ChildItem $script:extRoot -Directory -Filter ".second-brain-*").Count | Should Be 0
    }
}

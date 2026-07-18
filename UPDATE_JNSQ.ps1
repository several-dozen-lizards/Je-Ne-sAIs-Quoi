[CmdletBinding()]
param(
    [switch]$CheckOnly,
    [switch]$NonInteractive,
    [string]$ManifestUrl = "https://raw.githubusercontent.com/several-dozen-lizards/Je-Ne-sAIs-Quoi/main/DISTRIBUTION_MANIFEST.json",
    [string]$ArchiveUrl = "https://github.com/several-dozen-lizards/Je-Ne-sAIs-Quoi/archive/refs/heads/main.zip"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Root = $PSScriptRoot
$LocalManifestPath = Join-Path $Root "DISTRIBUTION_MANIFEST.json"
$Runfile = Join-Path $Root "jnsq_running.json"
$UpdateLog = Join-Path $Root "logs\update.log"
$TempRoot = $null
$RollbackRoot = $null
$RollbackRecords = @()
$PatchStarted = $false
$ManifestExisted = $false

function Write-Step([string]$Text) {
    Write-Host "  > $Text" -ForegroundColor Cyan
}

function Read-YesNo([string]$Prompt, [bool]$DefaultYes = $true) {
    if ($NonInteractive) { return $DefaultYes }
    $suffix = if ($DefaultYes) { "[Y/n]" } else { "[y/N]" }
    $answer = (Read-Host "$Prompt $suffix").Trim().ToLowerInvariant()
    if (-not $answer) { return $DefaultYes }
    return $answer -in @("y", "yes")
}

function Read-Json([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Managed-Properties($Manifest) {
    if ($null -eq $Manifest -or $null -eq $Manifest.managed_files) {
        return @()
    }
    return @($Manifest.managed_files.PSObject.Properties)
}

function Resolve-ManagedPath([string]$Base, [string]$Relative) {
    if ([string]::IsNullOrWhiteSpace($Relative)) {
        throw "The update manifest contains an empty path."
    }
    $portable = $Relative.Replace("\", "/")
    $parts = @($portable.Split("/") | Where-Object { $_ -ne "" })
    if ([IO.Path]::IsPathRooted($Relative) -or $parts -contains "..") {
        throw "The update manifest contains an unsafe path: $Relative"
    }
    $localRoots = @("users", "personas", "people", "logs", "exports", ".venv", ".git")
    if ($parts.Count -and $parts[0].ToLowerInvariant() -in $localRoots) {
        throw "The update manifest tried to manage local-life data: $Relative"
    }
    $privateNames = @(".env", ".jnsq_local.json", "jnsq_running.json", "room_world.json")
    if ($parts.Count -and $parts[-1].ToLowerInvariant() -in $privateNames) {
        throw "The update manifest tried to manage a private runtime file: $Relative"
    }
    $baseFull = [IO.Path]::GetFullPath($Base).TrimEnd("\") + "\"
    $relativeWindows = $portable.Replace("/", "\")
    $full = [IO.Path]::GetFullPath((Join-Path $Base $relativeWindows))
    if (-not $full.StartsWith($baseFull, [StringComparison]::OrdinalIgnoreCase)) {
        throw "The update path escaped the JNSQ folder: $Relative"
    }
    return $full
}

function Write-FailureReceipt([string]$Message) {
    try {
        $directory = Split-Path -Parent $UpdateLog
        New-Item -ItemType Directory -Force -Path $directory | Out-Null
        $stamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"
        Add-Content -LiteralPath $UpdateLog -Encoding UTF8 -Value "$stamp update_failed: $Message"
    } catch {
        # The useful failure is already on screen.
    }
}

Write-Host ""
Write-Host "  Je Ne Sais Quoi updater" -ForegroundColor Magenta
Write-Host "  -----------------------" -ForegroundColor DarkGray

try {
    $localManifest = Read-Json $LocalManifestPath
    $localVersion = if ($null -ne $localManifest -and $localManifest.version) {
        [string]$localManifest.version
    } else { "pre-updater" }

    Write-Step "Checking GitHub (local version: $localVersion)"
    $headers = @{ "User-Agent" = "JNSQ-Updater"; "Cache-Control" = "no-cache" }
    $remoteManifest = Invoke-RestMethod -Uri $ManifestUrl -Headers $headers
    if (-not $remoteManifest.version) {
        throw "GitHub's manifest has no version. No files were changed."
    }
    if ((Managed-Properties $remoteManifest).Count -eq 0) {
        throw "GitHub's manifest has no managed-file fingerprints. No files were changed."
    }
    $remoteVersion = [string]$remoteManifest.version
    Write-Host "  GitHub version: $remoteVersion"

    if ($localVersion -eq $remoteVersion) {
        Write-Host ""
        Write-Host "  Already up to date." -ForegroundColor Green
        exit 0
    }
    Write-Host "  Update available: $localVersion -> $remoteVersion" -ForegroundColor Yellow
    if ($CheckOnly) { exit 0 }
    if (-not (Read-YesNo "Install this update now?" $true)) {
        Write-Host "  Update left untouched."
        exit 0
    }
    if (Test-Path -LiteralPath $Runfile) {
        throw "JNSQ is running. Use STOP_NEXUS.bat, then run UPDATE_JNSQ.bat again."
    }

    $TempRoot = Join-Path ([IO.Path]::GetTempPath()) ("jnsq-update-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $TempRoot | Out-Null
    $archive = Join-Path $TempRoot "jnsq.zip"
    $expanded = Join-Path $TempRoot "expanded"

    Write-Step "Downloading version $remoteVersion"
    Invoke-WebRequest -UseBasicParsing -Uri $ArchiveUrl -Headers $headers -OutFile $archive
    Expand-Archive -LiteralPath $archive -DestinationPath $expanded
    $packageRoot = Get-ChildItem -LiteralPath $expanded -Directory | Where-Object {
        Test-Path -LiteralPath (Join-Path $_.FullName "DISTRIBUTION_MANIFEST.json")
    } | Select-Object -First 1
    if ($null -eq $packageRoot) {
        throw "The downloaded archive does not contain a JNSQ public package."
    }
    $packageManifestPath = Join-Path $packageRoot.FullName "DISTRIBUTION_MANIFEST.json"
    $packageManifest = Read-Json $packageManifestPath
    if ([string]$packageManifest.version -ne $remoteVersion) {
        throw "The downloaded package version does not match GitHub's manifest."
    }

    Write-Step "Validating managed files"
    $remoteNames = @{}
    foreach ($property in Managed-Properties $packageManifest) {
        $relative = [string]$property.Name
        $remoteNames[$relative.ToLowerInvariant()] = $true
        $source = Resolve-ManagedPath $packageRoot.FullName $relative
        [void](Resolve-ManagedPath $Root $relative)
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            throw "The package is missing managed file: $relative"
        }
        $actual = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
        $expected = ([string]$property.Value).ToLowerInvariant()
        if ($actual -ne $expected) {
            throw "Fingerprint mismatch in downloaded file: $relative"
        }
    }

    $changePlan = @()
    $removalPlan = @()
    $requirementsChanged = $false
    foreach ($property in Managed-Properties $packageManifest) {
        $relative = [string]$property.Name
        $source = Resolve-ManagedPath $packageRoot.FullName $relative
        $destination = Resolve-ManagedPath $Root $relative
        $expected = ([string]$property.Value).ToLowerInvariant()
        $current = if (Test-Path -LiteralPath $destination -PathType Leaf) {
            (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()
        } else { "" }
        if ($current -eq $expected) { continue }
        $changePlan += [pscustomobject]@{
            Relative = $relative
            Source = $source
            Destination = $destination
        }
        if ($relative.Replace("\", "/").ToLowerInvariant() -eq "requirements.txt") {
            $requirementsChanged = $true
        }
    }

    foreach ($property in Managed-Properties $localManifest) {
        $relative = [string]$property.Name
        if ($remoteNames.ContainsKey($relative.ToLowerInvariant())) { continue }
        $obsolete = Resolve-ManagedPath $Root $relative
        if (Test-Path -LiteralPath $obsolete -PathType Leaf) {
            $removalPlan += [pscustomobject]@{
                Relative = $relative
                Destination = $obsolete
            }
        }
    }

    $venvPython = Join-Path $Root ".venv\Scripts\python.exe"
    if ((Test-Path -LiteralPath $venvPython) -and $requirementsChanged) {
        Write-Step "Installing newly required dependencies"
        & $venvPython -m pip install --requirement `
            (Join-Path $packageRoot.FullName "requirements.txt")
        if ($LASTEXITCODE -ne 0) {
            throw "Dependency update failed before patching."
        }
    }

    $RollbackRoot = Join-Path $TempRoot "rollback"
    New-Item -ItemType Directory -Path $RollbackRoot | Out-Null
    $planned = @($changePlan) + @($removalPlan)
    $seenRollback = @{}
    foreach ($item in $planned) {
        $key = $item.Relative.Replace("\", "/").ToLowerInvariant()
        if ($seenRollback.ContainsKey($key)) { continue }
        $seenRollback[$key] = $true
        $existed = Test-Path -LiteralPath $item.Destination -PathType Leaf
        if ($existed) {
            $backup = Resolve-ManagedPath $RollbackRoot $item.Relative
            $backupParent = Split-Path -Parent $backup
            New-Item -ItemType Directory -Force -Path $backupParent | Out-Null
            Copy-Item -LiteralPath $item.Destination -Destination $backup -Force
        }
        $RollbackRecords += [pscustomobject]@{
            Relative = $item.Relative
            Destination = $item.Destination
            Existed = $existed
        }
    }
    $ManifestExisted = Test-Path -LiteralPath $LocalManifestPath -PathType Leaf
    if ($ManifestExisted) {
        Copy-Item -LiteralPath $LocalManifestPath `
            -Destination (Join-Path $RollbackRoot "DISTRIBUTION_MANIFEST.json") `
            -Force
    }

    $PatchStarted = $true
    foreach ($item in $changePlan) {
        $parent = Split-Path -Parent $item.Destination
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
        Copy-Item -LiteralPath $item.Source -Destination $item.Destination -Force
    }
    foreach ($item in $removalPlan) {
        Remove-Item -LiteralPath $item.Destination -Force
    }

    if (-not (Test-Path -LiteralPath $venvPython)) {
        Write-Step "Creating the missing local environment"
        & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File `
            (Join-Path $Root "SETUP_JNSQ.ps1") -NoLaunch -SkipIdentity -NonInteractive
        if ($LASTEXITCODE -ne 0) {
            throw "Environment setup failed after patching."
        }
    }

    $changed = @($changePlan).Count
    $removed = @($removalPlan).Count
    if (($changed + $removed) -gt 0) {
        Write-Step "Checking patched source files"
        & $venvPython -m compileall -q (Join-Path $Root "adapters") `
            (Join-Path $Root "core") (Join-Path $Root "harness") `
            (Join-Path $Root "room") (Join-Path $Root "shell")
        if ($LASTEXITCODE -ne 0) { throw "Source validation failed after patching." }
    }

    Copy-Item -LiteralPath $packageManifestPath `
        -Destination $LocalManifestPath -Force
    $PatchStarted = $false

    Write-Host ""
    Write-Host "  UPDATE COMPLETE" -ForegroundColor Green
    Write-Host "  Version: $remoteVersion"
    Write-Host "  Changed managed files: $changed"
    Write-Host "  Retired managed files: $removed"
    Write-Host "  Local identities, personas, memories, histories, keys, and .venv were preserved."
    Write-Host "  Start JNSQ with START_NEXUS.bat."
    exit 0
} catch {
    $message = $_.Exception.Message
    if ($PatchStarted -and $null -ne $RollbackRoot -and
            (Test-Path -LiteralPath $RollbackRoot)) {
        try {
            Write-Step "Restoring the previous managed files"
            foreach ($record in $RollbackRecords) {
                if ($record.Existed) {
                    $backup = Resolve-ManagedPath $RollbackRoot $record.Relative
                    $parent = Split-Path -Parent $record.Destination
                    New-Item -ItemType Directory -Force -Path $parent | Out-Null
                    Copy-Item -LiteralPath $backup `
                        -Destination $record.Destination -Force
                } elseif (Test-Path -LiteralPath $record.Destination -PathType Leaf) {
                    Remove-Item -LiteralPath $record.Destination -Force
                }
            }
            $manifestBackup = Join-Path $RollbackRoot "DISTRIBUTION_MANIFEST.json"
            if ($ManifestExisted) {
                Copy-Item -LiteralPath $manifestBackup `
                    -Destination $LocalManifestPath -Force
            } elseif (Test-Path -LiteralPath $LocalManifestPath -PathType Leaf) {
                Remove-Item -LiteralPath $LocalManifestPath -Force
            }
            $message = "$message Previous managed files were restored."
        } catch {
            $message = "$message Rollback also failed: $($_.Exception.Message)"
        }
    }
    Write-FailureReceipt $message
    Write-Host ""
    Write-Host "  UPDATE STOPPED" -ForegroundColor Red
    Write-Host "  $message" -ForegroundColor Yellow
    Write-Host "  Existing local-life data was not intentionally managed or replaced."
    Write-Host "  If the problem repeats, see logs\update.log."
    exit 1
} finally {
    if ($null -ne $TempRoot -and (Test-Path -LiteralPath $TempRoot)) {
        $tempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd("\") + "\"
        $resolvedTemp = [IO.Path]::GetFullPath($TempRoot)
        if ($resolvedTemp.StartsWith($tempBase, [StringComparison]::OrdinalIgnoreCase) -and
                (Split-Path -Leaf $resolvedTemp).StartsWith("jnsq-update-")) {
            Remove-Item -LiteralPath $resolvedTemp -Recurse -Force
        }
    }
}

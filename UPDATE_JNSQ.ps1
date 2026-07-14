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

    $changed = 0
    $removed = 0
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
        $parent = Split-Path -Parent $destination
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
        Copy-Item -LiteralPath $source -Destination $destination -Force
        $changed += 1
        if ($relative.Replace("\", "/").ToLowerInvariant() -eq "requirements.txt") {
            $requirementsChanged = $true
        }
    }

    foreach ($property in Managed-Properties $localManifest) {
        $relative = [string]$property.Name
        if ($remoteNames.ContainsKey($relative.ToLowerInvariant())) { continue }
        $obsolete = Resolve-ManagedPath $Root $relative
        if (Test-Path -LiteralPath $obsolete -PathType Leaf) {
            Remove-Item -LiteralPath $obsolete -Force
            $removed += 1
        }
    }

    Copy-Item -LiteralPath $packageManifestPath -Destination $LocalManifestPath -Force

    $venvPython = Join-Path $Root ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $venvPython)) {
        Write-Step "Creating the missing local environment"
        & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File `
            (Join-Path $Root "SETUP_JNSQ.ps1") -NoLaunch -SkipIdentity -NonInteractive
        if ($LASTEXITCODE -ne 0) { throw "Environment setup failed after patching." }
    } elseif ($requirementsChanged) {
        Write-Step "Installing newly required dependencies"
        & $venvPython -m pip install --requirement (Join-Path $Root "requirements.txt")
        if ($LASTEXITCODE -ne 0) { throw "Dependency update failed after patching." }
    }

    if ($changed -gt 0) {
        Write-Step "Checking patched source files"
        & $venvPython -m compileall -q (Join-Path $Root "adapters") `
            (Join-Path $Root "core") (Join-Path $Root "harness") `
            (Join-Path $Root "room") (Join-Path $Root "shell")
        if ($LASTEXITCODE -ne 0) { throw "Source validation failed after patching." }
    }

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

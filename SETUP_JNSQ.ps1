[CmdletBinding()]
param(
    [switch]$NoLaunch,
    [switch]$SkipIdentity,
    [switch]$NonInteractive
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = $PSScriptRoot
$VenvPath = Join-Path $Root ".venv"
$VenvPython = Join-Path $VenvPath "Scripts\python.exe"
$Requirements = Join-Path $Root "requirements.txt"
$Identity = Join-Path $Root ".jnsq_local.json"
$SetupLog = Join-Path $Root "logs\setup.log"
$PythonDownload = "https://www.python.org/downloads/windows/"

function Write-Banner {
    Write-Host ""
    Write-Host "  Je Ne sAIs Quoi" -ForegroundColor Magenta
    Write-Host "  first-home setup" -ForegroundColor DarkCyan
    Write-Host "  ----------------" -ForegroundColor DarkGray
    Write-Host ""
}

function Write-Step([string]$Text) {
    Write-Host "  > $Text" -ForegroundColor Cyan
}

function Read-YesNo([string]$Prompt, [bool]$DefaultYes = $true) {
    if ($NonInteractive) {
        return $DefaultYes
    }
    $suffix = if ($DefaultYes) { "[Y/n]" } else { "[y/N]" }
    $answer = (Read-Host "$Prompt $suffix").Trim().ToLowerInvariant()
    if (-not $answer) {
        return $DefaultYes
    }
    return $answer -in @("y", "yes")
}

function Test-PythonCandidate([string]$Command, [string[]]$PrefixArgs) {
    try {
        $resolved = Get-Command $Command -ErrorAction Stop
        $versionText = & $resolved.Source @PrefixArgs -c `
            "import sys; print('.'.join(map(str, sys.version_info[:3])))" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $versionText) {
            return $null
        }
        $version = [version]($versionText | Select-Object -Last 1)
        if ($version -lt [version]"3.10") {
            return $null
        }
        return [pscustomobject]@{
            Command = $resolved.Source
            Prefix = $PrefixArgs
            Version = $version
        }
    } catch {
        return $null
    }
}

function Find-CompatiblePython {
    $candidates = @(
        @{ Command = "py.exe"; Prefix = @("-3") },
        @{ Command = "python.exe"; Prefix = @() },
        @{ Command = "python3.exe"; Prefix = @() },
        @{ Command = (Join-Path $env:LOCALAPPDATA `
            "Programs\Python\Python312\python.exe"); Prefix = @() },
        @{ Command = (Join-Path $env:LOCALAPPDATA `
            "Programs\Python\Python311\python.exe"); Prefix = @() },
        @{ Command = (Join-Path $env:LOCALAPPDATA `
            "Programs\Python\Python310\python.exe"); Prefix = @() }
    )
    foreach ($candidate in $candidates) {
        $found = Test-PythonCandidate $candidate.Command $candidate.Prefix
        if ($null -ne $found) {
            return $found
        }
    }
    return $null
}

function Invoke-Checked(
    [string]$Label,
    [string]$Command,
    [string[]]$Arguments
) {
    Write-Step $Label
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE."
    }
}

function Install-PythonWithWinget {
    $winget = Get-Command "winget.exe" -ErrorAction SilentlyContinue
    if ($null -eq $winget) {
        return $false
    }
    if (-not (Read-YesNo "Python 3.10+ is missing. Install Python 3.12 now?" $true)) {
        return $false
    }
    Invoke-Checked "Installing Python 3.12 for this Windows user" `
        $winget.Source @(
            "install", "--id", "Python.Python.3.12", "--exact",
            "--source", "winget", "--scope", "user",
            "--accept-package-agreements", "--accept-source-agreements"
        )
    return $true
}

function Write-FailureReceipt([string]$Message) {
    try {
        $logDirectory = Split-Path -Parent $SetupLog
        New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
        $stamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"
        Add-Content -LiteralPath $SetupLog -Encoding UTF8 `
            -Value "$stamp setup_failed: $Message"
    } catch {
        # The useful error is already on screen; a logging failure must not hide it.
    }
}

Write-Banner

try {
    if (-not (Test-Path -LiteralPath $Requirements)) {
        throw "requirements.txt is missing. Download or extract the complete repository, then run setup again."
    }

    $python = Find-CompatiblePython
    if ($null -eq $python) {
        if ($NonInteractive) {
            throw "Python 3.10 or newer is required. Install it from $PythonDownload and run setup again."
        }
        $installed = Install-PythonWithWinget
        if ($installed) {
            $python = Find-CompatiblePython
        }
        if ($null -eq $python) {
            Write-Host ""
            Write-Host "Python still needs to be installed." -ForegroundColor Yellow
            Write-Host "Opening the official Python download page..."
            Start-Process $PythonDownload
            throw "After Python is installed, double-click INSTALL_JNSQ.bat again."
        }
    }

    Write-Host "  Found Python $($python.Version)" -ForegroundColor Green

    if (-not (Test-Path -LiteralPath $VenvPython)) {
        if (Test-Path -LiteralPath $VenvPath) {
            Invoke-Checked "Repairing the incomplete local environment" `
                $python.Command ($python.Prefix + @("-m", "venv", "--clear", $VenvPath))
        } else {
            Invoke-Checked "Creating JNSQ's private Python environment" `
                $python.Command ($python.Prefix + @("-m", "venv", $VenvPath))
        }
    } else {
        Write-Host "  Reusing the existing .venv" -ForegroundColor DarkGreen
    }

    Invoke-Checked "Updating the environment installer" $VenvPython `
        @("-m", "pip", "install", "--upgrade", "pip")
    Invoke-Checked "Installing JNSQ dependencies" $VenvPython `
        @("-m", "pip", "install", "--requirement", $Requirements)
    Invoke-Checked "Checking required libraries" $VenvPython @(
        "-c",
        "import fastapi, pydantic, requests, uvicorn, yaml; print('  Required libraries: OK')"
    )
    Invoke-Checked "Checking JNSQ source files" $VenvPython @(
        "-m", "compileall", "-q", "adapters", "core", "harness", "room", "shell"
    )

    if ($SkipIdentity) {
        Write-Host "  Local owner setup skipped by request." -ForegroundColor DarkGray
    } elseif (Test-Path -LiteralPath $Identity) {
        Write-Host "  Existing local owner found; their account was left untouched." `
            -ForegroundColor Green
    } elseif ($NonInteractive) {
        Write-Host "  Local owner setup skipped in non-interactive mode." `
            -ForegroundColor DarkGray
    } else {
        Invoke-Checked "Creating this installation's local owner" $VenvPython `
            @("-X", "utf8", "shell\first_run.py")
    }

    Write-Host ""
    Write-Host "  SETUP COMPLETE" -ForegroundColor Green
    Write-Host "  Dependencies live only in .venv on this computer."
    Write-Host "  User accounts, personas, histories, and API keys stay local."
    Write-Host ""

    if (-not $NoLaunch -and -not $NonInteractive -and `
            (Read-YesNo "Start Je Ne sAIs Quoi now?" $true)) {
        Start-Process -FilePath (Join-Path $Root "START_NEXUS.bat") `
            -WorkingDirectory $Root
    } else {
        Write-Host "  Start later by double-clicking START_NEXUS.bat."
    }
    exit 0
} catch {
    $message = $_.Exception.Message
    Write-FailureReceipt $message
    Write-Host ""
    Write-Host "  SETUP STOPPED" -ForegroundColor Red
    Write-Host "  $message" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Nothing personal was uploaded. It is safe to run setup again."
    Write-Host "  If the problem repeats, see logs\setup.log."
    exit 1
}

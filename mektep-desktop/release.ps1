[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidatePattern('^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$')]
    [string]$Version,

    [string]$DeployTarget = $env:MEKTEP_DEPLOY_TARGET,
    [string]$RemoteUpdatesPath = $(if ($env:MEKTEP_REMOTE_UPDATES_PATH) {
        $env:MEKTEP_REMOTE_UPDATES_PATH
    } else {
        "~/pdf-to-excel-scraper-main/updates"
    }),
    [string]$PublicUpdatesUrl = $(if ($env:MEKTEP_PUBLIC_UPDATES_URL) {
        $env:MEKTEP_PUBLIC_UPDATES_URL
    } else {
        "https://mektep-analyzer.kz/updates"
    }),
    [string]$Notes = "",
    [switch]$Mandatory,
    [string]$MinimumApiVersion,
    [string]$IdentityFile = $env:MEKTEP_SSH_IDENTITY_FILE,
    [int]$SshPort = 22,
    [switch]$BuildOnly,
    [switch]$SkipTests,
    [switch]$AllowDirty
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$DesktopDir = $PSScriptRoot
$ProjectRoot = Split-Path -Parent $DesktopDir
$VersionFile = Join-Path $DesktopDir "version.py"
$ConstantsFile = Join-Path $ProjectRoot "webapp\constants.py"
$DistDir = Join-Path $DesktopDir "dist"
$InstallerName = "MektepDesktopSetup-$Version.exe"
$InstallerPath = Join-Path $DistDir $InstallerName
$ManifestPath = Join-Path $DistDir "latest.json"
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Invoke-NativeCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Command,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $Command"
    }
}

function Set-VersionInFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Pattern,
        [Parameter(Mandatory = $true)]
        [string]$Replacement,
        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    $content = [IO.File]::ReadAllText($Path)
    if (-not [regex]::IsMatch($content, $Pattern)) {
        throw "Could not find $Description in $Path"
    }
    $updated = [regex]::Replace($content, $Pattern, $Replacement)
    [IO.File]::WriteAllText($Path, $updated, $Utf8NoBom)
}

function Get-SshCommonArguments {
    $arguments = @()
    if ($IdentityFile) {
        $arguments += @("-i", $IdentityFile)
    }
    return $arguments
}

function Get-ScpArguments {
    $arguments = @()
    if ($SshPort -ne 22) {
        $arguments += @("-P", [string]$SshPort)
    }
    $arguments += Get-SshCommonArguments
    return $arguments
}

function Get-SshArguments {
    $arguments = @()
    if ($SshPort -ne 22) {
        $arguments += @("-p", [string]$SshPort)
    }
    $arguments += Get-SshCommonArguments
    return $arguments
}

if (-not $BuildOnly -and [string]::IsNullOrWhiteSpace($DeployTarget)) {
    throw "Set -DeployTarget user@server or MEKTEP_DEPLOY_TARGET. Use -BuildOnly to build without publishing."
}

if (-not $BuildOnly -and $DeployTarget -notmatch '^(?:[A-Za-z0-9_.-]+@)?[A-Za-z0-9_.-]+$') {
    throw "DeployTarget must have the user@server format."
}

if ($RemoteUpdatesPath -notmatch '^[A-Za-z0-9_./~-]+$') {
    throw "RemoteUpdatesPath contains unsupported characters."
}

if ($MinimumApiVersion -and $MinimumApiVersion -notmatch '^\d+\.\d+\.\d+$') {
    throw "MinimumApiVersion must have the X.Y.Z format."
}

foreach ($command in @("python")) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "Command '$command' was not found."
    }
}

if (-not $AllowDirty -and -not (Get-Command "git" -ErrorAction SilentlyContinue)) {
    throw "Command 'git' was not found. Use -AllowDirty to skip the working tree check."
}

if (-not $BuildOnly) {
    foreach ($command in @("ssh", "scp")) {
        if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
            throw "Command '$command' was not found. Install Windows OpenSSH Client."
        }
    }
}

if (-not $AllowDirty) {
    $gitStatus = & git -C $ProjectRoot status --porcelain
    if ($LASTEXITCODE -ne 0) {
        throw "Could not inspect the Git working tree."
    }
    if ($gitStatus) {
        throw "The Git working tree is dirty. Commit the changes or use -AllowDirty."
    }
}

$OriginalVersionFile = [IO.File]::ReadAllText($VersionFile)
$OriginalConstantsFile = [IO.File]::ReadAllText($ConstantsFile)
$ReleaseSucceeded = $false
$KeepVersionChanges = $false

try {
    Write-Host "[1/6] Synchronizing version $Version"
    Set-VersionInFile `
        -Path $VersionFile `
        -Pattern '(?m)^APP_VERSION\s*=\s*"[^"]+"\s*$' `
        -Replacement "APP_VERSION = `"$Version`"" `
        -Description "APP_VERSION"
    Set-VersionInFile `
        -Path $ConstantsFile `
        -Pattern '(?m)^DESKTOP_VERSION\s*=\s*"[^"]+"\s*$' `
        -Replacement "DESKTOP_VERSION = `"$Version`"" `
        -Description "DESKTOP_VERSION"

    if ($MinimumApiVersion) {
        $parts = $MinimumApiVersion.Split(".")
        $minimumTuple = "MIN_DESKTOP_VERSION = ($($parts[0]), $($parts[1]), $($parts[2]))"
        Set-VersionInFile `
            -Path $ConstantsFile `
            -Pattern '(?m)^MIN_DESKTOP_VERSION\s*=\s*\([^)]+\)\s*$' `
            -Replacement $minimumTuple `
            -Description "MIN_DESKTOP_VERSION"
    }

    if (-not $SkipTests) {
        Write-Host "[2/6] Running tests"
        Push-Location $ProjectRoot
        try {
            Invoke-NativeCommand -Command "python" -Arguments @("-m", "pytest", "-q")
        }
        finally {
            Pop-Location
        }
    } else {
        Write-Host "[2/6] Tests skipped"
    }

    Write-Host "[3/6] Building with PyInstaller and Inno Setup"
    Invoke-NativeCommand -Command "python" -Arguments @((Join-Path $DesktopDir "build.py"))

    if (-not (Test-Path -LiteralPath $InstallerPath)) {
        throw "Installer was not created: $InstallerPath"
    }
    if (-not (Test-Path -LiteralPath $ManifestPath)) {
        throw "Update manifest was not created: $ManifestPath"
    }

    Write-Host "[4/6] Preparing update manifest"
    $manifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $manifest.version = $Version
    $manifest.url = "$($PublicUpdatesUrl.TrimEnd('/'))/$InstallerName"
    $manifest.mandatory = [bool]$Mandatory
    $manifest.notes = $Notes
    $manifest | ConvertTo-Json -Depth 10 |
        ForEach-Object { [IO.File]::WriteAllText($ManifestPath, "$_`n", $Utf8NoBom) }

    $actualHash = (Get-FileHash -LiteralPath $InstallerPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($manifest.sha256 -ne $actualHash) {
        throw "The SHA-256 in latest.json does not match the installer."
    }

    if ($BuildOnly) {
        Write-Host "[5/6] Publishing skipped (-BuildOnly)"
        Write-Host "[6/6] Done: $InstallerPath"
        $KeepVersionChanges = $true
        $ReleaseSucceeded = $true
        return
    }

    Write-Host "[5/6] Publishing safely to $DeployTarget"
    $remoteInstaller = "$RemoteUpdatesPath/$InstallerName"
    $remoteInstallerTemp = "$remoteInstaller.uploading"
    $remoteManifest = "$RemoteUpdatesPath/latest.json"
    $remoteManifestTemp = "$remoteManifest.uploading"

    $sshArgs = Get-SshArguments
    Invoke-NativeCommand -Command "ssh" -Arguments (
        $sshArgs + @($DeployTarget, "mkdir -p '$RemoteUpdatesPath'")
    )

    $scpArgs = Get-ScpArguments
    Invoke-NativeCommand -Command "scp" -Arguments (
        $scpArgs + @($InstallerPath, "${DeployTarget}:$remoteInstallerTemp")
    )
    Invoke-NativeCommand -Command "ssh" -Arguments (
        $sshArgs + @($DeployTarget, "mv -f '$remoteInstallerTemp' '$remoteInstaller'")
    )

    Invoke-NativeCommand -Command "scp" -Arguments (
        $scpArgs + @($ManifestPath, "${DeployTarget}:$remoteManifestTemp")
    )
    Invoke-NativeCommand -Command "ssh" -Arguments (
        $sshArgs + @($DeployTarget, "mv -f '$remoteManifestTemp' '$remoteManifest'")
    )
    # The release is externally visible from this point. Keep source versions
    # even if the subsequent public verification detects a CDN or server issue.
    $KeepVersionChanges = $true

    Write-Host "[6/6] Verifying published release"
    $publicManifestUrl = "$($PublicUpdatesUrl.TrimEnd('/'))/latest.json?release=$([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())"
    $publishedManifest = Invoke-RestMethod -Uri $publicManifestUrl -Method Get
    if ($publishedManifest.version -ne $Version) {
        throw "Server returned version '$($publishedManifest.version)' instead of '$Version'."
    }
    if ($publishedManifest.sha256 -ne $actualHash) {
        throw "Server returned an incorrect SHA-256."
    }

    $installerResponse = Invoke-WebRequest -Uri $publishedManifest.url -Method Head
    if ($installerResponse.StatusCode -ne 200) {
        throw "Installer is unavailable: HTTP $($installerResponse.StatusCode)."
    }

    Write-Host "Release $Version published: $($publishedManifest.url)"
    if ($MinimumApiVersion) {
        Write-Warning "MIN_DESKTOP_VERSION changed locally. Deploy webapp to enforce it."
    }
    Write-Warning "DESKTOP_VERSION changed locally. Commit version changes to Git."
    $ReleaseSucceeded = $true
}
finally {
    if (-not $KeepVersionChanges) {
        [IO.File]::WriteAllText($VersionFile, $OriginalVersionFile, $Utf8NoBom)
        [IO.File]::WriteAllText($ConstantsFile, $OriginalConstantsFile, $Utf8NoBom)
        Write-Warning "Release failed: source version changes were reverted."
    } elseif (-not $ReleaseSucceeded) {
        Write-Warning "The manifest was published but public verification failed. Version changes were kept; check the server immediately."
    }
}

<#
.SYNOPSIS
    Export and verify predictions locally, then publish a build snapshot.
.DESCRIPTION
    Stores predictions.json.gz as an asset on the mutable prediction-data
    GitHub Release. Replaces the asset on each update without committing data.
    Cloudflare Pages (or Netlify) downloads it when running npm run build:site.
    An optional deploy hook rebuilds the site immediately after uploading.
.EXAMPLE
    ./scripts/publish-data.ps1 -PrepareOnly
    ./scripts/publish-data.ps1 -Seasons 2025,2026
    ./scripts/publish-data.ps1 -SkipExport
#>
param(
    [string]$Repo = 'AzaanKH/football',
    [int[]]$Seasons,
    [switch]$SkipExport,
    [switch]$PrepareOnly,
    [ValidateRange(0, 5000)][int]$VerifySamples = 200,
    [string]$BuildHook = $env:PREDICTIONS_BUILD_HOOK
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend/fantasy-football'
$python = Join-Path $backend 'venv/Scripts/python.exe'
$snapshot = Join-Path $backend 'snapshots/predictions.json.gz'
$tag = 'prediction-data'

function Invoke-Step([string]$name, [scriptblock]$action) {
    Write-Host "`n== $name" -ForegroundColor Cyan
    & $action
    if ($LASTEXITCODE -ne 0) { throw "$name failed (exit code $LASTEXITCODE)" }
}

if ($Repo -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') { throw 'Repo must be owner/repository.' }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw 'Node.js is required to package predictions.' }
if (-not $PrepareOnly -and -not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw 'Install the GitHub CLI and run gh auth login before publishing (or use -PrepareOnly).'
}
if ($BuildHook -and -not $PrepareOnly) {
    $hookUri = $null
    if (-not [Uri]::TryCreate($BuildHook, [UriKind]::Absolute, [ref]$hookUri) -or $hookUri.Scheme -ne 'https') {
        throw 'PREDICTIONS_BUILD_HOOK must be an HTTPS deploy-hook URL.'
    }
}

Push-Location $backend
try {
    if (-not $SkipExport) {
        $exportArgs = @('export_static.py')
        if ($Seasons) { $exportArgs += @('--seasons') + ($Seasons | ForEach-Object { "$_" }) }
        Invoke-Step 'Export predictions' { & $python @exportArgs }
    }
    # --verify only checks the existing export; it does not generate an export.
    if ($VerifySamples -gt 0) {
        Invoke-Step 'Verify predictions against /predict_week' {
            & $python export_static.py --verify --samples $VerifySamples
        }
    }
} finally {
    Pop-Location
}

Push-Location $frontend
try {
    Invoke-Step 'Package prediction snapshot' { npm run data:pack }
} finally {
    Pop-Location
}

if ($PrepareOnly) {
    Write-Host "Snapshot ready locally: $snapshot"
    return
}

# A separate data release must remain mutable so the stable download URL works.
# Never replace an asset on an immutable release or change the latest code release.
# Windows PowerShell turns native stderr into PowerShell errors. A missing
# first-time release is expected here, so inspect the exit code without letting
# that stderr terminate the script under ErrorActionPreference=Stop.
$previousPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = 'Continue'
    & gh release view $tag --repo $Repo --json tagName *> $null
    $releaseExists = $LASTEXITCODE -eq 0
} finally {
    $ErrorActionPreference = $previousPreference
}
$created = $false
if (-not $releaseExists) {
    $settingsJson = & gh api "repos/$Repo/immutable-releases"
    if ($LASTEXITCODE -ne 0) { throw 'Could not inspect repository release settings.' }
    if (($settingsJson | ConvertFrom-Json).enabled) {
        throw 'Repository release immutability is enabled. This workflow needs a mutable data release.'
    }
    Invoke-Step 'Create prediction data release' {
        & gh release create $tag $snapshot --repo $Repo --target main --latest=false `
            --title 'Prediction data snapshot' `
            --notes 'Precomputed public predictions for static website builds. Generated locally; replaced on each data publish. This data release must remain mutable.'
    }
    $created = $true
}
$releaseJson = & gh api "repos/$Repo/releases/tags/$tag"
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the prediction data release.' }
$release = $releaseJson | ConvertFrom-Json
if ($release.immutable) { throw 'The prediction-data release is immutable. Use a mutable data release before publishing.' }
if ($release.draft) { throw 'The prediction-data release is a draft. Hosted builds need a public release asset.' }

if (-not $created) {
    Invoke-Step 'Upload prediction snapshot' {
        & gh release upload $tag $snapshot --repo $Repo --clobber
    }
}
Write-Host "Snapshot URL: https://github.com/$Repo/releases/download/$tag/predictions.json.gz"

if ($BuildHook) {
    # Do not print the hook URL: possession of it permits deployment triggers.
    try {
        $null = Invoke-WebRequest -Uri $BuildHook -Method Post -TimeoutSec 30 -UseBasicParsing
        Write-Host 'Website rebuild requested. Check the hosting dashboard for completion.'
    } catch {
        throw 'Snapshot uploaded, but the deploy hook failed. Trigger a rebuild in the hosting dashboard.'
    }
} else {
    Write-Host 'Trigger a hosting rebuild (or push code) to put this snapshot on the website.'
}

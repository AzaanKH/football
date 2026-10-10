<#
.SYNOPSIS
    Export predictions, build the frontend, and deploy it to Netlify.

.DESCRIPTION
    The site is static: predictions are exported from the local database and
    model (backend/export_static.py) into frontend public/data/ (gitignored),
    built into frontend build/, and uploaded with the Netlify CLI. Python and
    PostgreSQL never leave this machine.

    By default this makes a draft deploy (a preview URL) so you can check it;
    add -Prod to publish to the live site.

.PARAMETER Site
    Netlify site name or ID. Defaults to $env:NETLIFY_SITE_ID.

.PARAMETER Prod
    Publish to the live URL instead of a draft.

.PARAMETER Seasons
    Only export these seasons (default: every season with features).

.PARAMETER SkipExport
    Reuse the existing public/data export.

.PARAMETER VerifySamples
    Requests compared with /predict_week after exporting (0 to skip).

.EXAMPLE
    ./scripts/deploy.ps1 -Site start-sit             # draft
    ./scripts/deploy.ps1 -Site start-sit -Prod       # live
    ./scripts/deploy.ps1 -Site start-sit -Seasons 2025,2026 -Prod
#>
param(
    [string]$Site = $env:NETLIFY_SITE_ID,
    [switch]$Prod,
    [int[]]$Seasons,
    [switch]$SkipExport,
    [int]$VerifySamples = 50
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend/fantasy-football'
$python = Join-Path $backend 'venv/Scripts/python.exe'

function Invoke-Step([string]$name, [scriptblock]$action) {
    Write-Host "`n== $name" -ForegroundColor Cyan
    & $action
    if ($LASTEXITCODE -ne 0) { throw "$name failed (exit code $LASTEXITCODE)" }
}

if (-not $Site) {
    throw 'No Netlify site: pass -Site <name or id> or set $env:NETLIFY_SITE_ID.'
}
if (-not (Get-Command netlify -ErrorAction SilentlyContinue)) {
    throw 'Netlify CLI not found. Install it with: npm install -g netlify-cli'
}

if (-not $SkipExport) {
    Push-Location $backend
    try {
        # Needs the database (docker-compose up -d) and models/weekly_predictor.pkl
        $exportArgs = @('export_static.py')
        if ($Seasons) { $exportArgs += @('--seasons') + ($Seasons | ForEach-Object { "$_" }) }
        Invoke-Step 'Export predictions' { & $python @exportArgs }
        if ($VerifySamples -gt 0) {
            Invoke-Step 'Verify export against /predict_week' {
                & $python export_static.py --verify --samples $VerifySamples
            }
        }
    } finally {
        Pop-Location
    }
}

if (-not (Test-Path (Join-Path $frontend 'public/data/index.json'))) {
    throw 'No exported predictions in public/data. Run without -SkipExport.'
}

Push-Location $frontend
try {
    Invoke-Step 'Test frontend' { npm test }
    Invoke-Step 'Build frontend with local predictions' { npm run build:local }

    $deployArgs = @('deploy', '--dir', 'build', '--site', $Site,
                    '--message', "Predictions exported $(Get-Date -Format 'yyyy-MM-dd HH:mm')")
    if ($Prod) { $deployArgs += '--prod' }
    Invoke-Step ($(if ($Prod) { 'Deploy (live)' } else { 'Deploy (draft)' })) { netlify @deployArgs }
} finally {
    Pop-Location
}

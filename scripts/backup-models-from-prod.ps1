<#
Downloads a zip of every production model artifact to this PC (the off-server copy),
checks each file against the sha256 values in the zip's manifest.json, and keeps only
the newest N zips.

One-time setup: set the API key as a USER environment variable (never put it in a file
in the repo). Open a new terminal afterwards so it is picked up:

    [Environment]::SetEnvironmentVariable("STML_API_KEY", "<paste key here>", "User")

Weekly scheduled task (Sundays 10:00, runs as you, only while you are logged in):

    schtasks /Create /TN "STML model backup" /SC WEEKLY /D SUN /ST 10:00 `
      /TR "powershell -NoProfile -ExecutionPolicy Bypass -File \"D:\machine learning\swing-trade-bot\scripts\backup-models-from-prod.ps1\""

Run it by hand any time:  powershell -NoProfile -File scripts\backup-models-from-prod.ps1
Exit code 0 = verified backup saved; anything else = failed (message says why).
#>
param(
    [string]$BackupDir = (Join-Path $env:USERPROFILE "stml-model-backups"),
    [int]$Keep = 8,
    [string]$BaseUrl = "https://swingtrademl.com/api/v1"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "MODEL BACKUP FAILED: $Message" -ForegroundColor Red
    exit 1
}

$key = [Environment]::GetEnvironmentVariable("STML_API_KEY")
if ([string]::IsNullOrWhiteSpace($key)) {
    Fail "STML_API_KEY is not set. Set it as a user environment variable (see the top of this script)."
}
if ($Keep -lt 1) { Fail "-Keep must be at least 1." }

$extractDir = $null
try {
    New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $zipPath = Join-Path $BackupDir "stml-models-$stamp.zip"
    $partPath = "$zipPath.part"

    # Key goes in a header only; it is never printed.
    try {
        Invoke-WebRequest -Uri "$BaseUrl/ml/backup/models.zip" -Headers @{ "X-API-Key" = $key } `
            -OutFile $partPath -UseBasicParsing -TimeoutSec 900 | Out-Null
    } catch {
        $code = $null
        if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode }
        if ($code -eq 401 -or $code -eq 403) { Fail "the server rejected STML_API_KEY (HTTP $code)." }
        Fail "download failed$(if ($code) { " (HTTP $code)" })."
    }
    if (-not (Test-Path $partPath) -or (Get-Item $partPath).Length -eq 0) { Fail "the download was empty." }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $extractDir = Join-Path ([IO.Path]::GetTempPath()) "stml-verify-$stamp"
    try {
        [IO.Compression.ZipFile]::ExtractToDirectory($partPath, $extractDir)
    } catch {
        Fail "the downloaded file is not a valid zip."
    }

    $manifestPath = Join-Path $extractDir "manifest.json"
    if (-not (Test-Path $manifestPath)) { Fail "the zip has no manifest.json." }
    $manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json

    $verified = 0
    $missing = @()
    $bad = @()
    foreach ($a in $manifest.artifacts) {
        if ($a.missing) { $missing += "$($a.model) $($a.version)"; continue }
        $file = Join-Path $extractDir ($a.file -replace "/", "\")
        if (-not (Test-Path $file)) { $bad += "$($a.model) $($a.version) (file absent from zip)"; continue }
        $hash = (Get-FileHash -Algorithm SHA256 -Path $file).Hash.ToLower()
        if ($hash -ne $a.sha256 -or (Get-Item $file).Length -ne $a.size) {
            $bad += "$($a.model) $($a.version) (checksum mismatch)"
        } else {
            $verified++
        }
    }
    if ($bad.Count -gt 0) { Fail "verification failed for: $($bad -join '; ')." }
    if ($verified -eq 0) { Fail "the zip contains no model files." }

    Move-Item -Force $partPath $zipPath

    # Keep only the newest $Keep zips (names sort by date).
    Get-ChildItem $BackupDir -Filter "stml-models-*.zip" | Sort-Object Name -Descending |
        Select-Object -Skip $Keep | Remove-Item -Force

    Write-Host "Model backup OK: $verified file(s) verified -> $zipPath"
    if ($missing.Count -gt 0) {
        # The backup itself is good, but the server lost files: that needs attention.
        Write-Host "WARNING: the server is missing artifact files for: $($missing -join '; ')." -ForegroundColor Yellow
    }
} catch {
    Fail $_.Exception.Message
} finally {
    if ($extractDir -and (Test-Path $extractDir)) { Remove-Item -Recurse -Force $extractDir }
    if ($partPath -and (Test-Path $partPath)) { Remove-Item -Force $partPath }
}

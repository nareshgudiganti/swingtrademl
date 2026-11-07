# Shared helpers for the December helper scripts (dot-sourced by 01..08). Not a signed or frozen file.
# These scripts only run checks and dry runs. They never push, tag, train or start anything live.
Set-StrictMode -Version Latest
# 'Continue' on purpose: Windows PowerShell 5.1 turns a native command's stderr into a terminating error under 'Stop'.
# Every native call below checks its exit code explicitly and stops on the first failure.
$ErrorActionPreference = 'Continue'

$script:RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path

# The data lives in the local Docker Postgres (port 5433, database swing_trade_ml). This is the same local-only
# credential the repo's test configuration already commits; it is not a secret. The app's own default is port 5432,
# which does NOT match the Docker setup, so every database step passes this DSN to the child explicitly.
# Override with STML_LOCAL_DSN (still must be localhost). These scripts never use a production address.
function Get-LocalDsn {
    $dsn = $env:STML_LOCAL_DSN
    if (-not $dsn) { $dsn = 'postgresql+psycopg://swingtrade:swingtrade_local_pw@localhost:5433/swing_trade_ml' }
    if ($dsn -notmatch '@(localhost|127\.0\.0\.1)(:\d+)?/') { Fail 'STML_LOCAL_DSN must point at localhost. These helpers never touch a non-local database.' }
    return $dsn
}

function Say([string]$Message = '') { Write-Host $Message }

function Fail([string]$Message) {
    Write-Host "STOP: $Message" -ForegroundColor Red
    exit 1
}

function Get-PythonExe {
    # 1) explicit override, 2) this checkout's venv, 3) the main checkout's venv (worktrees share it)
    $candidates = @()
    if ($env:STML_PYTHON) { $candidates += $env:STML_PYTHON }
    $candidates += (Join-Path $script:RepoRoot 'backend\.venv\Scripts\python.exe')
    $common = & git -C $script:RepoRoot rev-parse --git-common-dir 2>$null
    if ($LASTEXITCODE -eq 0 -and $common) {
        $gitDir = [System.IO.Path]::GetFullPath([System.IO.Path]::Combine($script:RepoRoot, [string]$common))
        $mainRoot = Split-Path -Parent $gitDir
        $candidates += (Join-Path $mainRoot 'backend\.venv\Scripts\python.exe')
    }
    foreach ($c in $candidates) { if (Test-Path -LiteralPath $c) { return $c } }
    Fail 'No Python found. Set STML_PYTHON to backend\.venv\Scripts\python.exe of the main checkout.'
}

function Invoke-CleanPython {
    # Runs python like the tests do: API_KEY, JWT_SECRET_KEY, TRADING_MODE and SECTOR_FEATURES_DSN are removed from
    # the child's environment (so research never points at production), and DATABASE_URL is set to the LOCAL
    # Docker database only. No secret value is read or printed. The environment is restored afterwards.
    param([string]$WorkingDirectory, [string]$PythonPath, [string[]]$PyArgs)
    $py = Get-PythonExe
    $names = @('API_KEY', 'DATABASE_URL', 'JWT_SECRET_KEY', 'TRADING_MODE', 'SECTOR_FEATURES_DSN', 'PYTHONPATH')
    $saved = @{}
    foreach ($n in $names) { $saved[$n] = [Environment]::GetEnvironmentVariable($n, 'Process') }
    try {
        foreach ($n in $names) { [Environment]::SetEnvironmentVariable($n, $null, 'Process') }
        [Environment]::SetEnvironmentVariable('PYTHONPATH', $PythonPath, 'Process')
        [Environment]::SetEnvironmentVariable('DATABASE_URL', (Get-LocalDsn), 'Process')
        Push-Location $WorkingDirectory
        $code = 1
        try {
            # Out-Host: show the child's output on screen instead of returning it, so the function returns ONLY the exit code.
            & $py @PyArgs | Out-Host
            $code = $LASTEXITCODE
        } finally { Pop-Location }
        return [int]$code
    } finally {
        foreach ($n in $names) { [Environment]::SetEnvironmentVariable($n, $saved[$n], 'Process') }
    }
}

function Get-IstNow {
    $tz = [TimeZoneInfo]::FindSystemTimeZoneById('India Standard Time')
    return [TimeZoneInfo]::ConvertTime([DateTimeOffset]::UtcNow, $tz)
}

function Assert-ExitZero([int]$Code, [string]$What) {
    if ($Code -ne 0) { Fail "$What ended with exit code $Code (see the lines above)." }
}

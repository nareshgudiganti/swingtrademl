# 07-h05-daily-check: read-only look at the 5-day (h05) evaluation on the server. One GET request, nothing is changed.
# The API key is read from .env INSIDE this script and is never printed, logged or written anywhere.
param(
    [string]$BaseUrl = 'https://swingtrademl.com',
    [string]$EnvFile = '',
    [string]$MockJson = ''   # test only: read this saved report instead of calling the server
)
. (Join-Path $PSScriptRoot '_common.ps1')

Say 'H05 DAILY CHECK (read-only). I ask the server for the h05 report with one GET and print: sessions recorded vs expected,'
Say 'missed sessions, events and the verdicts. I change nothing and I do not print the API key.'
Say ''

if ($MockJson) {
    $report = Get-Content -LiteralPath $MockJson -Raw -Encoding UTF8 | ConvertFrom-Json
    Say "(mock: reading $MockJson instead of the server)"
} else {
    if (-not $EnvFile) {
        $EnvFile = Join-Path $script:RepoRoot '.env'
        if (-not (Test-Path -LiteralPath $EnvFile)) {
            $common = & git -C $script:RepoRoot rev-parse --git-common-dir 2>$null
            if ($LASTEXITCODE -eq 0 -and $common) {
                $gitDir = [System.IO.Path]::GetFullPath([System.IO.Path]::Combine($script:RepoRoot, [string]$common))
                $EnvFile = Join-Path (Split-Path -Parent $gitDir) '.env'
            }
        }
    }
    if (-not (Test-Path -LiteralPath $EnvFile)) { Fail 'No .env found (looked in this checkout and the main checkout). Pass -EnvFile.' }
    $key = $null
    foreach ($line in Get-Content -LiteralPath $EnvFile -Encoding UTF8) {
        if ($line -match '^\s*API_KEY\s*=\s*(.*)$') { $key = $Matches[1].Trim().Trim('"').Trim("'"); break }
    }
    if (-not $key) { Fail 'API_KEY is not set in the .env file.' }
    $uri = ($BaseUrl.TrimEnd('/')) + '/api/v1/research/h05/report'
    try {
        $report = Invoke-RestMethod -Method Get -Uri $uri -Headers @{ 'X-API-Key' = $key } -TimeoutSec 30
    } catch {
        Fail ("The server did not answer the read-only request ({0})." -f $_.Exception.Message.Split("`n")[0])
    } finally { $key = $null }
}

Say ("Protocol {0}  accepted: {1}" -f $report.protocol_code, $report.protocol_accepted)
foreach ($r in $report.runs) {
    $missed = @($r.missed_sessions).Count
    $events = @($r.events).Count
    Say ("Run {0}: {1}, {2} to {3}" -f $r.run_no, $r.status, $r.start_day, $r.end_day)
    Say ("  sessions recorded: {0} of {1} in the window so far" -f $r.days_recorded, $r.sessions_in_window)
    Say ("  missed sessions: {0}    events: {1}" -f $missed, $events)
    if ($missed -gt 0) { Say '  ATTENTION: a session was missed. Do not backfill and do not change rules; note it (missed sessions are never made up).' }
    if ($events -gt 0) { Say '  ATTENTION: events were recorded. Read them in the report before trusting the next day.' }
    if ($r.days_recorded -lt $r.sessions_in_window) { Say '  ATTENTION: fewer sessions recorded than the window has had.' }
}
foreach ($g in 'large', 'mid', 'small') {
    $v = $report.verdict.$g.combined
    if ($v) { Say ("Verdict {0}: selection {1}, economic {2}" -f $g, $v.selection.verdict, $v.economic.verdict) }
}
Say 'INCONCLUSIVE is normal until about 40 matured days. Known and explained: TMCV is not scored until it has 252 bars (about 17-18 Nov);'
Say 'the production-path obv_slope parity failure is the known incident (the primary score is unaffected).'
exit 0

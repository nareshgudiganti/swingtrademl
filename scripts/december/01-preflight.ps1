# 01-preflight: read-only health check before any Phase B / lab / SX5 step.
# It changes nothing. Exit code 0 = every hard check passed; 1 = at least one FAIL.
. (Join-Path $PSScriptRoot '_common.ps1')

Say 'PREFLIGHT (read-only). I will check: the git branch and a clean tree, the signed tags, that phase_b.py is'
Say 'unchanged, that the reserved tags are not created early, that the local database answers a real query,'
Say 'and what today is in India time. I change nothing.'
Say ''

$fails = 0
function Check([string]$Name, [bool]$Ok, [string]$Detail = '') {
    if ($Ok) { Say ("PASS  {0} {1}" -f $Name, $Detail) } else { Say ("FAIL  {0} {1}" -f $Name, $Detail); $script:fails++ }
}
function Info([string]$Name, [string]$Detail) { Say ("INFO  {0} {1}" -f $Name, $Detail) }

Push-Location $script:RepoRoot
try {
    $branch = (& git branch --show-current)
    $head = (& git rev-parse --short HEAD)
    Info 'branch/commit' "$branch @ $head"

    $dirty = @(& git status --porcelain --untracked-files=all)
    Check 'clean tree' ($dirty.Count -eq 0) ("({0} changed or untracked files)" -f $dirty.Count)

    foreach ($t in 'evidence-defs-v1', 'evidence-defs-v2', 'phase-b-settings') {
        $type = (& git cat-file -t $t 2>$null)
        $isTag = ($LASTEXITCODE -eq 0 -and $type -eq 'tag')
        $anc = $false
        if ($isTag) { & git merge-base --is-ancestor $t HEAD 2>$null; $anc = ($LASTEXITCODE -eq 0) }
        Check "tag $t annotated + ancestor of HEAD" ($isTag -and $anc)
    }

    $signed = (& git cat-file -t phase-b-completion-v1 2>$null)
    if ($LASTEXITCODE -eq 0) { Check 'tag phase-b-completion-v1 annotated' ($signed -eq 'tag') } else { Info 'tag phase-b-completion-v1' 'not created yet (the owner creates it after signing and merging)' }

    & git diff --exit-code phase-b-settings HEAD -- backend/src/swing_trade_ml/brain/phase_b.py *> $null
    Check 'phase_b.py identical to tag phase-b-settings' ($LASTEXITCODE -eq 0)

    # read-only lookup of a tag by exact ref name (no listing command, nothing is created)
    $result = (& git rev-parse -q --verify refs/tags/phase-b-result 2>$null); $wf = (& git rev-parse -q --verify refs/tags/wf-protocol-v2 2>$null)
    Info 'tag phase-b-result' ($(if ($result) { 'exists' } else { 'absent (expected until the finish step)' }))
    Info 'tag wf-protocol-v2' ($(if ($wf) { 'exists' } else { 'absent (only ever created for a real survivor)' }))
    Check 'wf-protocol-v2 not created without phase-b-result' (-not ($wf -and -not $result))

    $ist = Get-IstNow
    $d = $ist.Date
    $inB = ($d -ge [datetime]'2026-11-09' -and $d -le [datetime]'2026-12-04')
    $labOk = ($d -ge [datetime]'2026-12-05')
    Info 'India date' ("{0:yyyy-MM-dd HH:mm} IST" -f $ist.DateTime)
    Info 'Phase B window 2026-11-09..2026-12-04' ($(if ($inB) { 'today is inside' } else { 'today is OUTSIDE (real Phase B runs are refused)' }))
    Info 'lab start (>= 2026-12-05)' ($(if ($labOk) { 'date allows' } else { 'too early' }))

    $dsn = Get-LocalDsn
    $where = ($dsn -replace '^.*@', '')
    Say "Real query on the local database $where (select 1, 25 second limit)..."
    $py = Get-PythonExe
    $job = Start-Job -ArgumentList $py, $script:RepoRoot, $dsn -ScriptBlock {
        param($py, $root, $dsn)
        foreach ($n in 'API_KEY', 'JWT_SECRET_KEY', 'TRADING_MODE') { [Environment]::SetEnvironmentVariable($n, $null, 'Process') }
        $env:DATABASE_URL = $dsn
        $env:PYTHONPATH = (Join-Path $root 'backend\src')
        & $py -c "from sqlalchemy import text; from swing_trade_ml.db.session import SessionLocal; db=SessionLocal(); print('DB_OK', db.execute(text('select 1')).scalar()); db.close()" 2>&1
    }
    $done = Wait-Job $job -Timeout 25
    if ($done) { $out = (Receive-Job $job) -join ' '; Check 'database answers a real query' ($out -match 'DB_OK 1') } else { Stop-Job $job; Check 'database answers a real query' $false '(no answer in 25 s: Docker Postgres is down or hung)' }
    Remove-Job $job -Force
} finally { Pop-Location }

Say ''
if ($fails -gt 0) { Say "RESULT: $fails check(s) FAILED. Fix the cause before any live step. Nothing was changed."; exit 1 }
Say 'RESULT: all hard checks passed. Nothing was changed.'
exit 0

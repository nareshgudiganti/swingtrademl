# 06-sx5-dry-run: runs backend/scripts/sx5_run.py WITHOUT the run switch. It prints the plan and every check. Nothing is trained.
# -WithData also reads the local database (SELECT only) to count rows and print the data hashes.
# There is deliberately NO helper for the real run: it needs the owner's approval and authorisation files.
param([switch]$WithData)
. (Join-Path $PSScriptRoot '_common.ps1')

if ($WithData) { Say 'SX5 DRY RUN with data: I read the local database (SELECT only, read-only) and print the row count and data hashes. Nothing is trained or written.' }
else { Say 'SX5 DRY RUN: I print the plan and every check (PASS/FAIL). Nothing is trained or written.' }
Say 'SECTOR_FEATURES_DSN is removed for this run, so the loader reads the local Docker database, never production.'
Say ''
$pyArgs = @('scripts/sx5_run.py')
if ($WithData) { $pyArgs += '--with-data' }
$rc = Invoke-CleanPython -WorkingDirectory (Join-Path $script:RepoRoot 'backend') -PythonPath (Join-Path $script:RepoRoot 'backend\src') -PyArgs $pyArgs
Assert-ExitZero $rc 'sx5_run dry run'
Say ''
Say 'NOT done by this helper: the real development run. It is allowed only from 2026-12-04, with the owner-signed protocol, the approval file'
Say 'and the separate training authorisation (see docs/brain/SX5-RUN.md). It is a typed command.'
exit 0

# 02-phase-b-dry-run: prints the plan of one Phase B candidate (dates, folds, stocks, split hash, the ledger row a
# real run would add). It reads no market data, scores nothing and writes nothing (phase_b.dry_run_plan).
param([Parameter(Mandatory = $true)][ValidateSet('B1', 'B2', 'B3')][string]$Candidate)
. (Join-Path $PSScriptRoot '_common.ps1')

Say "DRY RUN of Phase B candidate $Candidate. I only print the plan. Nothing is scored, trained or written."
Say 'The line near the end says whether a real run is allowed today (it is refused before 2026-11-09).'
Say ''
$code = "import swing_trade_ml.brain.service; from swing_trade_ml.brain import phase_b as pb; print(pb.dry_run_plan('$Candidate'))"
$rc = Invoke-CleanPython -WorkingDirectory $script:RepoRoot -PythonPath (Join-Path $script:RepoRoot 'backend\src') -PyArgs @('-c', $code)
Assert-ExitZero $rc 'The Phase B dry run'
Say ''
Say 'NOT done by this helper: the real run is deliberate and typed by you, from the signed branch, one candidate at a time,'
Say 'in the order B1, B2, B3, after gates G1-G15 pass. The module import must come first or the CLI hits a circular import:'
Say "  python -c `"import sys, swing_trade_ml.brain.service; from swing_trade_ml.cli import main; sys.argv=['swingtrade','brain','phase-b','--candidate','$Candidate']; raise SystemExit(main())`""
Say '  (set DATABASE_URL to the local Docker database on port 5433, never production; see DECEMBER-RUNBOOK.md)'
exit 0

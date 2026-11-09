# 05-lab-check: runs the 15-day lab start wrapper in --check-only mode. It can never start the lab.
# There is deliberately NO helper that starts the lab: the real start stays a typed command.
param([Parameter(Mandatory = $true)][ValidateSet('S0', 'S1', 'S2', 'S0M', 'S1M', 'S2M')][string]$Candidate)
. (Join-Path $PSScriptRoot '_common.ps1')

Say "LAB CHECK for $Candidate (check only). I run every start condition and print which ones fail. The lab is NOT started."
Say 'Exit 0 = every condition passes; exit 2 = refused, with the reasons. One audit line is added to backend/data/lab_start_audit.jsonl (git-ignored).'
Say ''
$rc = Invoke-CleanPython -WorkingDirectory $script:RepoRoot -PythonPath (Join-Path $script:RepoRoot 'backend\src') -PyArgs @('-m', 'swing_trade_ml.brain.selection_lab_start', $Candidate, '--check-only')
Say ''
if ($rc -eq 0) { Say 'All start conditions pass for this candidate.' } else { Say "Refused (exit $rc): the lab may not start yet. This is normal before 2026-12-05 and before the Phase B record exists." }
Say 'The real start is a typed command, from the signed branch, one candidate at a time (after the owner says start):'
Say "  python -m swing_trade_ml.brain.selection_lab_start $Candidate"
exit $rc

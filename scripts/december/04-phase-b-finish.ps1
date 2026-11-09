# 04-phase-b-finish: after B1, B2 and B3 are all committed, prepares the final Phase B record with phase_b_finish.
# Dry run by default. -Apply writes PHASE_B_RESULT.json, PHASE_B_RESULT.md and one ledger row. It never commits or tags.
param([switch]$Apply)
. (Join-Path $PSScriptRoot '_common.ps1')

if ($Apply) { Say 'APPLY: I will write PHASE_B_RESULT.json, its readable report PHASE_B_RESULT.md and one exposure-ledger row.' }
else { Say 'DRY RUN: I will check all three candidates and print the outcome the record would hold. Nothing is written. Add -Apply to write it.' }
Say 'Safe to run twice: if the record exists the tool only verifies it (ALREADY FINALIZED).'
Say ''
$pyArgs = @('-m', 'swing_trade_ml.brain.phase_b_finish', '--root', $script:RepoRoot)
if ($Apply) { $pyArgs += '--apply' }
$rc = Invoke-CleanPython -WorkingDirectory $script:RepoRoot -PythonPath (Join-Path $script:RepoRoot 'backend\src') -PyArgs $pyArgs
if ($rc -eq 2) { Say ''; Say 'The tool REFUSED (exit 2). The reasons are listed above. Nothing was written.'; exit 2 }
Assert-ExitZero $rc 'phase_b_finish'
Say ''
Say 'NOT done by this helper: committing the record and creating its annotated tag. The tool printed those commands above;'
Say 'you run them yourself. The tool never prints a wf-protocol-v2 command after NO_SURVIVOR.'
exit 0

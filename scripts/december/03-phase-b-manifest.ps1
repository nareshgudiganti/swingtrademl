# 03-phase-b-manifest: after ONE candidate has run, prepares its evidence manifest with phase_b_finish.
# Dry run by default. -Apply writes only MANIFEST_<Bn>.json. This helper never commits anything.
param(
    [Parameter(Mandatory = $true)][ValidateSet('B1', 'B2', 'B3')][string]$Candidate,
    [switch]$Apply
)
. (Join-Path $PSScriptRoot '_common.ps1')

if ($Apply) { Say "APPLY: I will write the evidence manifest MANIFEST_$Candidate.json (one small file) and nothing else." }
else { Say "DRY RUN: I will check candidate $Candidate and show what the manifest would contain. Nothing is written. Add -Apply to write it." }
Say ''
$pyArgs = @('-m', 'swing_trade_ml.brain.phase_b_finish', '--root', $script:RepoRoot, '--manifest', $Candidate)
if ($Apply) { $pyArgs += '--apply' }
$rc = Invoke-CleanPython -WorkingDirectory $script:RepoRoot -PythonPath (Join-Path $script:RepoRoot 'backend\src') -PyArgs $pyArgs
if ($rc -eq 2) { Say ''; Say 'The tool REFUSED (exit 2). The reasons are listed above. Nothing was written.'; exit 2 }
Assert-ExitZero $rc 'phase_b_finish --manifest'
Say ''
Say 'NOT done by this helper: committing. After -Apply, YOU run the commands the tool printed above (one commit with exactly'
Say "these four items: phase_b_${Candidate}_2025-02-01_2026-08-15.md and .json, MANIFEST_$Candidate.json, docs/brain/EXPOSURE-LEDGER.md)."
Say 'Then check the commit contents (nothing else in it), a clean tree, and only then start the next candidate.'
exit 0

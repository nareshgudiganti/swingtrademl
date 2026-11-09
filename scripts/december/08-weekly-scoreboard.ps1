# 08-weekly-scoreboard: the S1 / S2 research scoreboards (read-only, development data, needs the local database).
# It writes a small report under docs/brain/evidence/scoreboard/. It uses the import form that works
# (running the module with -m fails with a circular import, a known defect that is not fixed).
param(
    [Parameter(Mandatory = $true)][ValidateSet('s1', 's2')][string]$Report,
    [Parameter(Mandatory = $true)][ValidatePattern('^\d{4}-\d{2}-\d{2}$')][string]$From,
    [Parameter(Mandatory = $true)][ValidatePattern('^\d{4}-\d{2}-\d{2}$')][string]$To
)
. (Join-Path $PSScriptRoot '_common.ps1')

Say "WEEKLY SCOREBOARD $Report from $From to $To (research only, reads the local database, writes one report file)."
Say 'Never add backtest, forward-research and paper results together into one profit figure.'
Say ''
$code = "import swing_trade_ml.brain.service; from swing_trade_ml.brain.scoreboard import main; raise SystemExit(main(['$Report','--from','$From','--to','$To']))"
$rc = Invoke-CleanPython -WorkingDirectory $script:RepoRoot -PythonPath (Join-Path $script:RepoRoot 'backend\src') -PyArgs @('-c', $code)
Assert-ExitZero $rc 'The scoreboard'
exit 0

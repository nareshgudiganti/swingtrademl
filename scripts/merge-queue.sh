#!/usr/bin/env bash
# One central merge process (owner decisions 26 Nov 2026: decision 10 and the merge-gate plan).
#
# Approval lives in GitHub, not here:
#   * every PR needs the required checks (backend, frontend, e2e, gitleaks);
#   * a PR that touches sensitive files also needs the required `owner-gate` check, which passes only
#     after the OWNER ticks the "Owner approval" box in the PR description (#527, #543). Claude never
#     ticks it.
#
# This script only routes: a PR enters the queue when it carries the label
#   independent-review-passed  a developer who did not write the branch reviewed it
# and for each such PR it
#   1. skips drafts and reports PRs with conflicts (resolved by hand, never forced);
#   2. turns on GitHub auto-merge (squash). A sensitive PR then waits for the owner's tick.
#
# It does NOT update branches from main: main does not require up-to-date branches (strict off,
# owner 26 Nov), and a pushed update would untick an owner-gate approval on sensitive PRs.
# It never bypasses anything, does not deploy (a production deploy is a separate manual run), and
# never deletes branches.
#
# Usage: scripts/merge-queue.sh            # act
#        scripts/merge-queue.sh --dry-run  # report only
set -euo pipefail

DRY=0
[[ "${1:-}" == "--dry-run" ]] && DRY=1

REVIEWED="independent-review-passed"

# Filter labels locally: `gh pr list --label` uses GitHub search, which can lag minutes behind a new label.
prs=$(gh pr list --state open --limit 200 \
  --json number,title,isDraft,mergeable,mergeStateStatus,labels,autoMergeRequest \
  --jq '.[] | select([.labels[].name] | index("'"$REVIEWED"'") != null)
             | [.number, .isDraft, .mergeable, .mergeStateStatus,
               (.autoMergeRequest != null), .title] | @tsv')

if [[ -z "$prs" ]]; then
  echo "Queue empty: no open PR labelled '$REVIEWED'."
  exit 0
fi

while IFS=$'\t' read -r num draft mergeable state auto title; do
  line="#$num [$state] $title"
  if [[ "$draft" == "true" ]]; then echo "SKIP  $line (draft)"; continue; fi
  if [[ "$mergeable" == "CONFLICTING" || "$state" == "DIRTY" ]]; then
    echo "BLOCK $line (merge conflict: resolve by hand)"; continue
  fi
  if [[ "$auto" != "true" ]]; then
    echo "AUTO  $line (auto-merge on: merges when required checks pass; sensitive PRs wait for the owner's tick)"
    [[ $DRY -eq 0 ]] && gh pr merge "$num" --auto --squash >/dev/null
  else
    echo "OK    $line (auto-merge already on)"
  fi
done <<< "$prs"

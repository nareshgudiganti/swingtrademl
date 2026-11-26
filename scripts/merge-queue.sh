#!/usr/bin/env bash
# One central merge process for approved PRs (owner decision 10, 26 Nov 2026).
#
# A PR enters the queue only when it carries BOTH labels:
#   owner-approved             the owner approved this merge
#   independent-review-passed  a developer who did not write the branch reviewed it
#
# For each queued PR this script:
#   1. skips drafts and reports PRs with conflicts (resolved by hand, never forced);
#   2. turns on GitHub auto-merge (squash).
#
# It does NOT update branches from main: main does not require up-to-date branches (strict off,
# owner 26 Nov), and a pushed update would untick an owner-gate approval (#527) on sensitive PRs.
#
# Planned (once #527's owner-gate is a required check): drop the owner-approved label requirement;
# owner-gate then holds sensitive PRs and routine reviewed PRs merge on green.
#
# It never bypasses anything: GitHub merges only after every required check passes and branch
# protection allows it. It does not deploy (a production deploy is a separate manual run), never
# deletes branches, and never touches PRs without both labels.
#
# Usage: scripts/merge-queue.sh            # act
#        scripts/merge-queue.sh --dry-run  # report only
set -euo pipefail

DRY=0
[[ "${1:-}" == "--dry-run" ]] && DRY=1

APPROVED="owner-approved"
REVIEWED="independent-review-passed"

# Filter labels locally: `gh pr list --label` uses GitHub search, which can lag minutes behind a new label.
prs=$(gh pr list --state open --limit 200 \
  --json number,title,isDraft,mergeable,mergeStateStatus,labels,autoMergeRequest \
  --jq '.[] | select([.labels[].name] | index("'"$APPROVED"'") != null)
             | [.number, .isDraft, .mergeable, .mergeStateStatus,
               ([.labels[].name] | index("'"$REVIEWED"'") != null),
               (.autoMergeRequest != null), .title] | @tsv')

if [[ -z "$prs" ]]; then
  echo "Queue empty: no open PR labelled '$APPROVED'."
  exit 0
fi

while IFS=$'\t' read -r num draft mergeable state reviewed auto title; do
  line="#$num [$state] $title"
  if [[ "$draft" == "true" ]]; then echo "SKIP  $line (draft)"; continue; fi
  if [[ "$reviewed" != "true" ]]; then echo "WAIT  $line (needs label '$REVIEWED')"; continue; fi
  if [[ "$mergeable" == "CONFLICTING" || "$state" == "DIRTY" ]]; then
    echo "BLOCK $line (merge conflict: resolve by hand)"; continue
  fi
  if [[ "$auto" != "true" ]]; then
    echo "AUTO  $line (auto-merge on: merges when checks pass)"
    [[ $DRY -eq 0 ]] && gh pr merge "$num" --auto --squash >/dev/null
  else
    echo "OK    $line (auto-merge already on)"
  fi
done <<< "$prs"

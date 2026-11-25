# Feature status files

One JSON file per feature (`feature-<issue>-<slug>.json`), so a UI can show progress without calling GitHub.
GitHub (issues and project 2) remains the source of truth; these files are a snapshot, refreshed when a story changes state.

## Schema `trademind.feature-status/v1`

| Field | Meaning |
|---|---|
| `feature` | Parent issue number, title, state, url |
| `updated_at` | When the snapshot was taken (IST, ISO 8601) |
| `summary` | Story counts per `state` |
| `owner_decisions` | Open questions for the owner, each with a recommendation |
| `open_pull_requests` | PR numbers still open for this feature |
| `stories[]` | One entry per story: `issue`, `title`, `board_status` (the project 2 column), `state`, `blocked_by`, `pull_request`, `evidence`, `url` |

`state` values:
- `done`: closed.
- `awaiting_owner`: work finished, waiting for the owner to review, merge or close.
- `in_progress`: work remaining that can proceed.
- `blocked`: cannot proceed until `blocked_by` clears.
- `not_started`: future work, not yet due.
- `superseded`: replaced by another story, kept for history.

`board_status` is copied from the project board. `state` adds what the column cannot show: who or what the story is waiting on.

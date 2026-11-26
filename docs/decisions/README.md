# Decision records (ADR index)

One file per settled or proposed architecture decision. The target architecture they come from is
`docs/architecture/TARGET-ARCHITECTURE-PROPOSAL.md`; the permanent rules that follow from them are in `CLAUDE.md`
("Core platform standards") and `AGENTS.md`. `docs/README.md` stays the single map of all documents.

| ADR | Decision | Status | Built on `main` (checked 2026-11-26) |
|---|---|---|---|
| [ADR-001](ADR-001-service-01-gaps.md) | Service 1 gaps and the Service 1 / Brain split | Analysed; nothing implemented, no build list approved | No |
| [ADR-002](ADR-002-modular-monolith.md) | One modular monolith, enforced module boundaries | Proposed; Steps 0-1 approved 2026-11-22 | Yes: module registry, switches, import tests |
| [ADR-003](ADR-003-capability-registry.md) | One capability registry for switches, plans and roles | Proposed; Steps 2-3 await the owner | Partly: plans map onto modules only |
| [ADR-004](ADR-004-identity-and-score-ledger.md) | One `security_id` per stock, append-only score ledger | Proposed; each migration needs owner approval | Yes, phase 1 (#389) |
| [ADR-005](ADR-005-versioned-research-config.md) | Trading-rule and research numbers in one versioned place | Proposed; Steps 2-3 await the owner | Partly: code version, no database table or Admin selector |

Status words: **Proposed** means written but not (fully) approved by the owner, so follow it for new code and do not
claim it is final. **Built** means a file on `main` implements it; each ADR names the file. Nothing here approves a
merge, a deploy or a migration.

A new decision gets the next number (ADR-006 and on), the same headings (Context, Decision, Consequences), and a row
above.

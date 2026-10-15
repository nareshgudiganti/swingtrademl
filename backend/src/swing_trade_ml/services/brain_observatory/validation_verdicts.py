"""The reviewed verdict registry (spec section 6; plan correction C9a: a Python module so it ships in the
wheel). Changed only by commit after a frozen protocol run; tests/test_brain_observatory_verdicts_ci.py
checks every value against the git objects (tag, protocol blob, report blobs) in CI.

Values verified 2026-10-15 from git objects.
"""

REGISTRY: dict = {
    "schema": "validation-verdicts@1",
    "entries": [
        {
            "protocol_id": "wf-protocol-v1",
            "protocol_file": "docs/superpowers/specs/2026-10-12-walk-forward-protocol.md",
            "protocol_sha256": "63c71d054a27390b9dbb03123d48c4f9102f8c1de51a661314dd24de90e6e70e",
            "tag": "wf-protocol-v1",
            "tag_commit": "7b972916b1510676f05cd4ef7941003e7013ff6e",
            "evidence_commit": "e1602761c9fc3a2a609d6229bb59605b432d7a67",
            "tested_subject": (
                "Model top-5 ranking only (layer 1): a model retrained per 28-day fold by "
                "brain/walk_forward.py, next-day open entry, +8% / -4%, half out at +5%, 15 trading days, "
                "after costs. Not the exact production model and not the full brain."
            ),
            "sample": {
                "from": "2023-07-01",
                "to": "2025-01-31",
                "folds": 21,
                "kind": "confirmation",
                "independence": "audit_uncommitted",
                "audit_path": None,
                "audit_sha256": None,
                "independence_note": (
                    "An independence audit dated 2026-10-12 exists only as an uncommitted edit. It reports "
                    "that 2024-08-01 to 2025-01-31 was exposed to a feature-selection decision."
                ),
            },
            "report_files": {
                "md": {
                    "path": "docs/brain/evidence/wf_v1/walk_forward_2023-07-01_2025-01-31.md",
                    "sha256": "f656da864d89f3aca246c1861020b94c0aa4d350238a70d2290e883966608e37",
                },
                "json": {
                    "path": "docs/brain/evidence/wf_v1/walk_forward_2023-07-01_2025-01-31.json",
                    "sha256": "5ff084939bdc7af14f99db7404636c10fba9438998a2ca3139f62eaa10dd3ceb",
                },
            },
            "minimums": {"eligible_folds": 12, "finished_ideas": 100, "share": 0.6},
            "parts": {
                "predictive": {
                    "claim": "model_ranking_predictive",
                    "recorded_word": "fail",
                    "eligible_folds": 21,
                    "folds_won": 7,
                    "share": 0.3333333333333333,
                    "finished_ideas": 1980,
                    "extra_check": "lower bound of the daily edge over every-stock is above zero",
                    "extra_check_value": -0.00513018427018618,
                },
                "economic": {
                    "claim": "model_ranking_economic",
                    "recorded_word": "fail",
                    "eligible_folds": 21,
                    "folds_won": 9,
                    "share": 0.42857142857142855,
                    "finished_ideas": 1980,
                    "extra_check": "average result per trade after costs is above zero overall",
                    "extra_check_value": -0.002038939548709073,
                },
            },
        }
    ],
}

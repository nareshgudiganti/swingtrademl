"""Brain Observatory, Phase 1A: read-only views over what the brain already stored.

Spec: docs/superpowers/specs/2026-10-15-brain-observatory-design.md. Nothing here writes, runs the brain,
sends a message or talks to a broker; the API reads through its own READ ONLY transaction (db.py).
"""

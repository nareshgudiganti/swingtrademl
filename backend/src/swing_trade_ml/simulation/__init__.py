# ruff: noqa: E501  (long plain-English docstrings)
"""The 100-portfolio paper-trial simulation (#379, #321, #264): in memory, synthetic, no schema, no mail, no broker.

Pure code: nothing here writes a database row, places an order or sends a message. Real symbols arrive later
through the identity interface (services/identity); until then tests use fake symbols.
"""
